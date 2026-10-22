"""Made-up data for tests, from Tolkien's Middle-earth.

Tests never use real people or real research sites. When a test needs a
person, a site or a position, it takes them from here:

    from canvod.utils import testing

    meta = Creator(name=testing.PERSON_NAME, email=testing.PERSON_EMAIL, ...)

The position is Tolkien's birthplace, Bloemfontein.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The person who runs the made-up site.
PERSON_NAME = "John Ronald Reuel Tolkien"
#: How the person signs changes of store metadata.
PERSON_INITIALS = "JRRT"
PERSON_EMAIL = "j.r.r.tolkien@the.inklings.org"
INSTITUTION = "University of Oxford"
#: A made-up ORCID iD with a valid check digit (ORCID issues none from
#: 0000-0000), and one whose check digit is X.
PERSON_ORCID = "0000-0000-0000-1231"
OTHER_ORCID = "0000-0000-0000-001X"
#: A made-up ROR id in the ROR format.
INSTITUTION_ROR = "0mddrth01"
DEPARTMENT = "English Faculty"
RESEARCH_GROUP = "The Inklings"
PUBLISHER = "The Inklings"
WEBSITE = "https://the.inklings.org"
#: A made-up software repository and its documentation.
REPOSITORY = "https://github.com/the-inklings/red-book"
DOCUMENTATION = "https://github.com/the-inklings/red-book/tree/main/docs"
#: A valid naming authority (reverse DNS).
NAMING_AUTHORITY = "org.middle-earth"

#: The site as a key of the settings (``sites.fangorn``) and in store ids.
SITE_KEY = "fangorn"
#: The site in file names: 3-letter site ID and 3-letter agency of the
#: canVOD file name convention (``FANA01INK_R_...`` for a canopy receiver).
SITE_ID = "FAN"
AGENCY = "INK"
#: A second site for file names (``ORTA01MEA_R_...``).
OTHER_SITE_ID = "ORT"
OTHER_AGENCY = "MEA"

#: The below-canopy site or receiver.
CANOPY_SITE = "Fangorn"
#: The reference (open sky) site or receiver.
REFERENCE_SITE = "Orthanc"
#: The tree species below which the canopy receiver sits.
SPECIES = "Ent"
#: The canopy site's description, Gandalf in The Two Towers.
SITE_DESCRIPTION = (
    "Certainly the forest of Fangorn is perilous — not least to those that "
    "are too ready with their axes; and Fangorn himself, he is perilous "
    "too; yet he is wise and kindly nonetheless. But now his long slow "
    "wrath is brimming over, and all the forest is filled with it."
)

#: Bloemfontein: WGS84 decimal degrees, and its elevation in meters
#: (approximate).
LATITUDE = -29.12
LONGITUDE = 26.21
ALTITUDE_M = 1395.0

#: The same position in WGS84 ECEF (meters), taking ALTITUDE_M as the height
#: above the ellipsoid. From PROJ (pyproj, EPSG:4979 to EPSG:4978) and the
#: closed-form WGS84 formula, which agree to the millimeter.
ECEF_X = 5004115.301
ECEF_Y = 2463414.934
ECEF_Z = -3086206.104


def write_settings(folder: Path) -> Path:
    """Write a settings file for the made-up person and site.

    For tests of code that loads the settings itself: point
    ``CANVOD_CONFIG_DIR`` at ``folder``. Stores, auxiliary files and logs
    go below ``folder``. Returns the settings file (JSON, which YAML
    reads).
    """
    folder.mkdir(parents=True, exist_ok=True)
    settings = {
        "processing": {
            "metadata": {
                "author": PERSON_NAME,
                "email": PERSON_EMAIL,
                "institution": INSTITUTION,
                "publisher": PUBLISHER,
                "naming_authority": NAMING_AUTHORITY,
                "initials": PERSON_INITIALS,
                "license": "CC-BY-4.0",
            },
            "storage": {
                "stores_root_dir": str(folder / "stores"),
                "aux_data_dir": str(folder / "aux"),
            },
            "logging": {"log_dir": str(folder / "logs")},
        },
        "sites": {
            SITE_KEY: {
                "gnss_site_data_root": str(folder / "data"),
                "receivers": {
                    "canopy_01": {"type": "canopy", "directory": "02_canopy"},
                },
            }
        },
    }
    path = folder / "canvod-settings.yaml"
    path.write_text(json.dumps(settings, indent=2))
    return path


#: A made-up commit of :data:`REPOSITORY`, for pinned URLs.
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class PinnedFileServer:
    """A local HTTP server that stands in for ``raw.githubusercontent.com``.

    It answers per URL path and records each request's path and headers.
    Tests point :mod:`canvod.utils.pinned` at it, so no test reaches the
    network::

        server = testing.PinnedFileServer()
        monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", server.origin)
        server.serve(url, b"...")
        ...
        server.close()
    """

    def __init__(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.routes: dict[str, tuple[int, bytes, dict[str, str]]] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.requests.append((self.path, dict(self.headers)))
                status, body, headers = server.routes.get(
                    self.path, (404, b"404: Not Found", {})
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        # A larger backlog than the default 5: parallel fetches connect at once.
        server_class = type(
            "Server", (ThreadingHTTPServer,), {"request_queue_size": 64}
        )
        self.httpd = server_class(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, args=(0.05,), daemon=True
        )
        self.thread.start()

    def serve(self, url: str, body: bytes, status: int = 200, **headers: str) -> None:
        """Answer requests for ``url`` with ``status``, ``body`` and ``headers``."""
        self.routes[url.removeprefix("https://raw.githubusercontent.com")] = (
            status,
            body,
            headers,
        )

    def close(self) -> None:
        """Stop the server."""
        self.httpd.shutdown()
        self.httpd.server_close()
