"""Tests for ``canvodpy.demo_data()``: download, check and unpack demo data.

The archives are small zips built in a temporary folder and served as
``file://`` URLs, so no test needs the network.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import canvodpy.demo as demo_module
import pytest
from canvodpy.demo import DemoArchive

from canvodpy import demo_data

CANOPY_RNX = "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
REFERENCE_RNX = "rinex_v3_04/01_Rosalia/01_reference/01_GNSS/01_raw/25001/ROSR01TUW_R_20250010000_15M_05S_AA.rnx"
CANOPY_SBF = "sbf/01_Rosalia/02_canopy/25001/ROSA01TUW_R_20250010000_15M_05S_AA.sbf"


def _zip(path: Path, members: dict[str, bytes]) -> str:
    """Write a zip with these members and return its sha256."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def archives(tmp_path, monkeypatch) -> Path:
    """Replace the published archives with local ones; return their folder."""
    served = tmp_path / "served"
    served.mkdir()
    specs = [
        ("rinex", "rinex-canopy.zip", {CANOPY_RNX: b"canopy"}),
        ("rinex", "rinex-reference.zip", {REFERENCE_RNX: b"reference"}),
        ("sbf", "sbf-canopy.zip", {CANOPY_SBF: b"sbf"}),
    ]
    local = []
    for kind, name, members in specs:
        digest = _zip(served / name, members)
        local.append(
            DemoArchive(
                name=name,
                kind=kind,
                url=(served / name).as_uri(),
                sha256=digest,
                members=(),
            )
        )
    monkeypatch.setattr(demo_module, "ARCHIVES", tuple(local))
    return served


def test_rinex_unpacks_both_receivers_in_the_test_data_layout(archives, tmp_path):
    root = demo_data("rinex", cache_dir=tmp_path / "cache")

    assert (root / CANOPY_RNX).read_bytes() == b"canopy"
    assert (root / REFERENCE_RNX).read_bytes() == b"reference"


def test_only_the_requested_kind_is_downloaded(archives, tmp_path):
    root = demo_data("rinex", cache_dir=tmp_path / "cache")

    assert not (root / CANOPY_SBF).exists()


def test_cached_data_needs_no_download(archives, tmp_path):
    cache = tmp_path / "cache"
    first = demo_data("sbf", cache_dir=cache)
    (archives / "sbf-canopy.zip").unlink()

    second = demo_data("sbf", cache_dir=cache)

    assert second == first
    assert (second / CANOPY_SBF).read_bytes() == b"sbf"


def test_wrong_checksum_is_refused_and_nothing_is_unpacked(
    archives, tmp_path, monkeypatch
):
    bad = DemoArchive(
        name="sbf-canopy.zip",
        kind="sbf",
        url=(archives / "sbf-canopy.zip").as_uri(),
        sha256="0" * 64,
        members=(),
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (bad,))
    cache = tmp_path / "cache"

    with pytest.raises(RuntimeError, match=r"sbf-canopy\.zip.*sha256"):
        demo_data("sbf", cache_dir=cache)

    assert not list(cache.rglob("*.sbf"))
    assert not list(cache.rglob("*.zip"))


def test_unknown_kind_names_the_known_ones(archives, tmp_path):
    with pytest.raises(ValueError, match=r"'nmea'.*'rinex'.*'sbf'"):
        demo_data("nmea", cache_dir=tmp_path / "cache")  # ty: ignore[invalid-argument-type]


def test_unpublished_archive_says_so(archives, tmp_path, monkeypatch):
    unpublished = DemoArchive(
        name="aux.zip", kind="aux", url=None, sha256="0" * 64, members=()
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (unpublished,))

    with pytest.raises(RuntimeError, match="not published yet"):
        demo_data("aux", cache_dir=tmp_path / "cache")


@pytest.fixture
def flaky_server(archives):
    """Serve the archives over HTTP; the first answer of each breaks off.

    Like Zenodo when it drops a connection: the next request asks for the
    rest with a Range header and gets it.
    """
    import http.server
    import threading

    broken: set[str] = set()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = (archives / self.path.lstrip("/")).read_bytes()
            start = 0
            if rng := self.headers.get("Range"):
                start = int(rng.removeprefix("bytes=").split("-")[0])
            body = data[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}"
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.path not in broken:
                broken.add(self.path)
                self.wfile.write(body[: len(body) // 2])
                return  # the connection closes before the rest
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_a_broken_download_resumes(flaky_server, tmp_path, monkeypatch):
    monkeypatch.setattr(demo_module.time, "sleep", lambda _: None)
    sbf = next(a for a in demo_module.ARCHIVES if a.kind == "sbf")
    served = DemoArchive(
        name=sbf.name,
        kind="sbf",
        url=f"{flaky_server}/{sbf.name}",
        sha256=sbf.sha256,
        members=(),
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (served,))

    root = demo_data("sbf", cache_dir=tmp_path / "cache")

    assert (root / CANOPY_SBF).read_bytes() == b"sbf"


def test_a_failed_download_names_the_url_and_not_ftp(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_module.time, "sleep", lambda _: None)
    missing = DemoArchive(
        name="gone.zip",
        kind="sbf",
        url=(tmp_path / "gone.zip").as_uri(),
        sha256="0" * 64,
        members=(),
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (missing,))

    with pytest.raises(RuntimeError) as info:
        demo_data("sbf", cache_dir=tmp_path / "cache")

    message = str(info.value) + str(info.value.__cause__)
    assert "gone.zip" in message
    assert "FTP" not in message
    assert "NASA" not in message


GNSS_STORE = "stores/rosalia_rinex_v3_04/gnss/repo"
VOD_STORE = "stores/rosalia_rinex_v3_04/vod/repo"


class _ServedReference(demo_module.PublishedReference):
    """Published reference stores served from a local folder."""

    def url(self, name: str) -> str:
        return (Path(self.dataset) / name).as_uri()


@pytest.fixture
def reference(tmp_path, monkeypatch) -> Path:
    """Replace the published reference stores with local zips; return their folder."""
    served = tmp_path / "served-reference"
    (served / "default").mkdir(parents=True)
    sums = {
        "default/rosalia_rinex_v3_04-gnss.zip": _zip(
            served / "default/rosalia_rinex_v3_04-gnss.zip", {GNSS_STORE: b"gnss"}
        ),
        "default/rosalia_rinex_v3_04-vod.zip": _zip(
            served / "default/rosalia_rinex_v3_04-vod.zip", {VOD_STORE: b"vod"}
        ),
    }
    published = _ServedReference(dataset=str(served), revision="r1", sums=sums)
    monkeypatch.setattr(demo_module, "published_reference", lambda: published)
    return served


def test_stores_unpacks_the_gnss_and_vod_store(reference, tmp_path):
    root = demo_data("stores", cache_dir=tmp_path / "cache")

    assert (root / GNSS_STORE).read_bytes() == b"gnss"
    assert (root / VOD_STORE).read_bytes() == b"vod"
    assert root == tmp_path / "cache" / "reference-stores" / "r1" / "default"


def test_cached_stores_need_no_download(reference, tmp_path):
    first = demo_data("stores", cache_dir=tmp_path / "cache")
    for zip_path in reference.rglob("*.zip"):
        zip_path.unlink()

    assert demo_data("stores", cache_dir=tmp_path / "cache") == first


def test_stores_with_a_wrong_sha256_are_refused(reference, tmp_path, monkeypatch):
    published = demo_module.published_reference()
    wrong = _ServedReference(
        dataset=published.dataset,
        revision=published.revision,
        sums={name: "0" * 64 for name in published.sums},
    )
    monkeypatch.setattr(demo_module, "published_reference", lambda: wrong)

    with pytest.raises(RuntimeError, match=r"rosalia_rinex_v3_04-gnss\.zip.*sha256"):
        demo_data("stores", cache_dir=tmp_path / "cache")

    assert not list((tmp_path / "cache").rglob("repo"))


def test_the_package_pins_the_published_stores_of_the_rinex_day():
    published = demo_module.published_reference()

    assert published.dataset == "nfb2021/canvodpy-reference-stores"
    assert len(published.revision) == 40
    assert {f"default/{name}" for name in demo_module._STORE_ZIPS} <= set(
        published.sums
    )
