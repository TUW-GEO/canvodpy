"""The content settings of a store: the settings that shape its data.

Whoever creates a store sets its content settings; every run that writes
to the store must have the same ones, or it stops (ADR 0019; grilling on
two writers, 2026-10-16). They are a fixed field of the repository
metadata (ADR 0014), written when the store is created, or by
``canvodpy store migrate-metadata`` for a store created before, and never
amended. A change means a new store.

Which settings count is :data:`CONTENT_KEYS`, plus three settings of each
receiver (:data:`RECEIVER_KEYS`). Every other setting is free per run
(workers, memory, logs, caches, folders, store strategies) or kept in the
store as repository metadata (description, creator, references).

The stored form keeps the keys of ``canvod-settings.yaml`` with every
default written out, so ``canvodpy config init --from-store`` can write a
settings file from it. A run compares its own content settings with the
store's key by key, when it starts and at the tip before each commit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from .location import StoreLocation

#: Version of the stored form; a reader refuses a newer one.
CONTENT_SETTINGS_FORMAT = 1

#: The repository metadata field that holds them.
CONTENT_SETTINGS_FIELD = "content_settings"

#: Store types that keep content settings. The VOD store adds its own keys
#: (:data:`VOD_CONTENT_KEYS`) and the GNSS store's content-settings hash.
CONTENT_STORE_TYPES = ("gnss_store", "vod_store")

#: The settings that shape a GNSS store's data, as dotted keys of
#: ``canvod-settings.yaml``. A key that names a section takes all of it.
CONTENT_KEYS = (
    "sids.mode",
    "sids.preset",
    "sids.custom_sids",
    "processing.params.keep_gnss_observables",
    "processing.params.aggregate_glonass_fdma",
    "processing.params.store_radial_distance",
    "processing.params.store_delta_snr",
    "processing.params.store_radial_diff",
    "processing.params.store_sbf_raw_observables",
    "processing.params.store_sbf_metadata",
    "processing.params.rinex_v3_parser",
    "processing.params.file_pairing",
    "processing.params.receiver_position_mode",
    "processing.params.ephemeris_source",
    "processing.aux_data.agency",
    "processing.aux_data.product_type",
    "processing.aux_data.fetch_clock",
    "processing.preprocessing",
    "processing.icechunk.compression_algorithm",
    "processing.icechunk.compression_level",
    "processing.icechunk.inline_chunk_threshold_bytes",
    "processing.icechunk.manifest_splitting_enabled",
    "processing.icechunk.manifest_splitting_epoch_range",
    "processing.icechunk.chunk_strategies.gnss_store",
    "processing.storage.maintenance",
)

#: The settings that shape a VOD store's data, as dotted keys of
#: ``canvod-settings.yaml``. A VOD store keeps no SIDs, receivers or site
#: entries of its own; instead it records the content-settings hash of the
#: GNSS store the VOD was computed from (:data:`gnss_content_hash`).
VOD_CONTENT_KEYS = (
    "processing.params.store_delta_snr",
    "processing.params.store_radial_diff",
    "processing.icechunk.compression_algorithm",
    "processing.icechunk.compression_level",
    "processing.icechunk.inline_chunk_threshold_bytes",
    "processing.icechunk.manifest_splitting_enabled",
    "processing.icechunk.manifest_splitting_epoch_range",
    "processing.icechunk.chunk_strategies.vod_store",
    "processing.storage.maintenance",
)

#: The top-level keys of the settings file that content settings come from.
SETTINGS_ROOTS = ("sids", "processing", "sites")

#: The repository-metadata field that holds the GNSS store's content-settings
#: hash for a VOD store (a single hash replaces a SID list: a VOD store has no
#: SIDs of its own).
GNSS_CONTENT_HASH = "gnss_content_hash"
#: The settings of each receiver that count, below
#: ``sites.<site>.receivers.<receiver>``.
RECEIVER_KEYS = ("type", "reader_format", "paired_canopies")

#: The key of the resolved SID list (the preset's or custom list, ``None``
#: for all SIDs); not a key of the settings file.
RESOLVED_SIDS = "sids (resolved list)"


class ContentSettingsError(ValueError):
    """A run's settings don't fit the content settings of its store."""


class MissingContentSettingsError(ContentSettingsError):
    """The store has no content settings: it was created before they existed."""


@dataclass(frozen=True)
class Difference:
    """One content setting that differs between a store and a run."""

    key: str
    store: Any
    run: Any


def _get(data: Any, key: str) -> Any:
    """The value of a dotted ``key`` in a settings object or a dict."""
    for part in key.split("."):
        if data is None:
            return None
        data = data.get(part) if isinstance(data, Mapping) else getattr(data, part)
    return data


def _json(value: Any) -> Any:
    """``value`` in JSON form (settings models are dumped with their defaults)."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return json.loads(json.dumps(value, default=str))


def _put(data: dict[str, Any], key: str, value: Any) -> None:
    *parents, last = key.split(".")
    for part in parents:
        data = data.setdefault(part, {})
    data[last] = value


def _canvodpy_version() -> str | None:
    try:
        return importlib_metadata.version("canvodpy")
    except importlib_metadata.PackageNotFoundError:
        return None


def settings_hash(
    settings: Mapping[str, Any], resolved_sids: Any, gnss_hash: str | None = None
) -> str:
    """SHA-256 of the content settings, for display and a quick check.

    ``gnss_hash`` is the ``gnss_content_hash`` of a VOD store (ADR 0019 D1).
    It is included in the hash only when it is not ``None``, so a GNSS
    store's hash is what it was before this hash was recorded.
    """
    hashed: dict[str, Any] = {"settings": settings, "resolved_sids": resolved_sids}
    if gnss_hash is not None:
        hashed["gnss_content_hash"] = gnss_hash
    text = json.dumps(hashed, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def receiver_content_settings(receiver: Any) -> dict[str, Any]:
    """The content settings of one receiver, from its settings."""
    return {key: _json(getattr(receiver, key)) for key in RECEIVER_KEYS}


def run_content_settings(
    config: Any, site_name: str, store_type: str = "gnss_store"
) -> dict[str, Any]:
    """The content settings of a run: the settings part and the SID list.

    Returns ``{"settings": ..., "resolved_sids": ...}``, where ``settings``
    has the keys of ``canvod-settings.yaml``. For a VOD store the keys are
    :data:`VOD_CONTENT_KEYS` and ``resolved_sids`` is ``None``: a VOD store
    has no SIDs of its own, its GNSS store's SIDs are implied by
    ``gnss_content_hash``.

    Raises
    ------
    ValueError
        If the site is not in the settings.
    """
    sites = config.sites.sites
    if site_name not in sites:
        msg = f"Site {site_name!r} is not in the settings (sites.{site_name})."
        raise ValueError(msg)
    settings: dict[str, Any] = {}
    keys = CONTENT_KEYS if store_type == "gnss_store" else VOD_CONTENT_KEYS
    for key in keys:
        _put(settings, key, _json(_get(config, key)))
    resolved_sids: Any = None
    if store_type == "gnss_store":
        receivers = {
            name: receiver_content_settings(receiver)
            for name, receiver in sites[site_name].receivers.items()
        }
        _put(settings, f"sites.{site_name}.receivers", receivers)
        resolved_sids = _json(config.sids.get_sids())
    return {"settings": settings, "resolved_sids": resolved_sids}


def recorded_by(config: Any) -> str:
    """Who a store records as setting its content settings.

    ``processing.metadata.initials``, the name metadata changes record, or
    the author when no initials are set.
    """
    meta = config.processing.metadata
    return (getattr(meta, "initials", None) or "").strip() or meta.author


def new_content_settings(
    config: Any,
    site_name: str,
    *,
    store_type: str = "gnss_store",
    set_by: str | None = None,
    origin: str = "created",
    gnss_repository: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The content settings a new store records, from the run's settings.

    Parameters
    ----------
    store_type
        ``"gnss_store"`` or ``"vod_store"``; picks the keys that count.
    set_by
        Who sets them; ``None``: ``processing.metadata.initials``, or the
        author when no initials are set. Never the user or computer of the
        process: stores are shared.
    origin
        ``"created"`` (a new store) or ``"migrated"``
        (``canvodpy store migrate-metadata``).
    gnss_repository
        The GNSS store's repository metadata, for a VOD store: its
        content-settings hash is recorded as ``gnss_content_hash``. Not
        needed for a GNSS store.

    Raises
    ------
    MissingContentSettingsError
        For a VOD store whose GNSS store has no content settings.
    """
    content = run_content_settings(config, site_name, store_type)
    gnss_hash = (
        gnss_content_hash_from(gnss_repository) if store_type == "vod_store" else None
    )
    return stored_form(
        content["settings"],
        content["resolved_sids"],
        set_by=set_by or recorded_by(config),
        origin=origin,
        gnss_content_hash=gnss_hash,
    )


def stored_form(
    settings: Mapping[str, Any],
    resolved_sids: Any,
    *,
    set_by: str,
    origin: str,
    gnss_content_hash: str | None = None,
) -> dict[str, Any]:
    """The content settings as the repository metadata keeps them."""
    data = {
        "format": CONTENT_SETTINGS_FORMAT,
        "origin": origin,
        "set_by": set_by,
        "set_at": datetime.now(UTC).isoformat(),
        "canvodpy_version": _canvodpy_version(),
        "hash": settings_hash(settings, resolved_sids, gnss_content_hash),
        "settings": dict(settings),
        "resolved_sids": resolved_sids,
    }
    if gnss_content_hash is not None:
        data[GNSS_CONTENT_HASH] = gnss_content_hash
    return data


def gnss_content_hash_from(repository: Mapping[str, Any] | None) -> str:
    """The content-settings hash of a GNSS store, from its repository metadata.

    Raises
    ------
    MissingContentSettingsError
        If the GNSS store has no content settings (created before they
        existed): the hash cannot be known, and a VOD store cannot record it.
    """
    from .io import store_command

    if repository is None or not repository.get(CONTENT_SETTINGS_FIELD):
        site = (repository or {}).get("spatial", {}).get("site", {}).get("name", "SITE")
        msg = (
            "The GNSS store the VOD is computed from has no content settings, "
            "so its hash cannot be recorded with the VOD store. Write them "
            "once, from the settings recorded in the store's first commit:\n"
            f"  {store_command('migrate-metadata', site, 'gnss_store')}"
        )
        raise MissingContentSettingsError(msg)
    return repository[CONTENT_SETTINGS_FIELD]["hash"]


def check_gnss_hash(
    vod_repository: Mapping[str, Any],
    gnss_repository: Mapping[str, Any],
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse a VOD write from a GNSS store with other content settings.

    A VOD store records ``gnss_content_hash`` (ADR 0019 D1). A run whose
    GNSS store has a different content-settings hash would compute VOD from
    data this VOD store does not describe. A missing hash is refused instead
    of silently turning the check off (#355).

    Raises
    ------
    MissingContentSettingsError
        If the GNSS store has no content settings, or the VOD store records
        no ``gnss_content_hash``.
    ContentSettingsError
        If the hashes differ (both hashes and the two stores are named).
    """
    from .io import store_command

    stored_hash = vod_repository.get(CONTENT_SETTINGS_FIELD, {}).get(GNSS_CONTENT_HASH)
    current_hash = gnss_repository.get(CONTENT_SETTINGS_FIELD, {}).get("hash")
    if not current_hash:
        site = _site_name(gnss_repository)
        msg = (
            "The GNSS store this VOD run reads has no content settings, so "
            "its hash cannot be checked. Write them once, from the settings "
            "recorded in the store's first commit:\n"
            f"  {store_command('migrate-metadata', site, 'gnss_store')}"
        )
        raise MissingContentSettingsError(msg)
    if not stored_hash:
        site = _site_name(vod_repository)
        msg = (
            f"The VOD store at {store_path} records no gnss_content_hash, so "
            "its content settings cannot be checked against the GNSS store "
            "this run reads. Write it once, from the GNSS store's content "
            "settings:\n"
            f"  {store_command('migrate-metadata', site, 'vod_store')} "
            f"--set gnss_content_hash={current_hash}"
        )
        raise MissingContentSettingsError(msg)
    if stored_hash == current_hash:
        return
    msg = (
        f"The GNSS store this VOD run reads has content-settings hash "
        f"{current_hash}, but the VOD store at {store_path} records "
        f"gnss_content_hash {stored_hash}. The VOD store was computed from a "
        "GNSS store with other content settings; writing it would mix data. "
        "Use the GNSS store the VOD store was computed from, or write to a "
        "new VOD store (set processing.storage.vod_store_name to e.g. "
        "'vod-recompute')."
    )
    raise ContentSettingsError(msg)


def _site_name(repository: Mapping[str, Any]) -> str:
    """The site a repository metadata names, for an error message."""
    return str(repository.get("spatial", {}).get("site", {}).get("name", "SITE"))


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Dotted keys to values; lists and ``None`` are values."""
    if not isinstance(data, Mapping) or not data:
        return {prefix: data}
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    return flat


def differences(
    stored: Mapping[str, Any], run: Mapping[str, Any], site_name: str
) -> list[Difference]:
    """The content settings that differ between a store and a run, key by key.

    ``stored`` is the store's content settings, ``run`` the result of
    :func:`run_content_settings`. A receiver only one side lists is not
    compared: a receiver the store doesn't list is refused by its own check
    (it is added on purpose, with ``canvodpy store amend``), and a run may
    leave out receivers of its site.
    """
    receivers = f"sites.{site_name}.receivers"
    stored_settings = dict(stored["settings"])
    run_settings = dict(run["settings"])
    store_receivers = _get(stored_settings, receivers) or {}
    run_receivers = _get(run_settings, receivers) or {}
    shared = sorted(set(store_receivers) & set(run_receivers))
    left = _flatten({**stored_settings, "sites": None})
    right = _flatten({**run_settings, "sites": None})
    for name in shared:
        for key in RECEIVER_KEYS:
            left[f"{receivers}.{name}.{key}"] = store_receivers[name].get(key)
            right[f"{receivers}.{name}.{key}"] = run_receivers[name].get(key)
    left[RESOLVED_SIDS] = stored.get("resolved_sids")
    right[RESOLVED_SIDS] = run.get("resolved_sids")
    left.pop("sites", None)
    right.pop("sites", None)
    return [
        Difference(key, left.get(key), right.get(key))
        for key in sorted(set(left) | set(right))
        if left.get(key) != right.get(key)
    ]


def _short(value: Any) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 80 else f"{text[:77]}..."


def _set_when(stored: Mapping[str, Any]) -> str:
    origin = stored.get("origin", "created")
    when = str(stored.get("set_at", "?"))[:10]
    version = stored.get("canvodpy_version")
    action = "when the store was created" if origin == "created" else "by migration"
    with_version = f", canvodpy {version}" if version else ""
    return f"{action} on {when} by {stored.get('set_by', '?')}{with_version}"


def _store_label(repository: Mapping[str, Any]) -> str:
    kind = repository.get("identity", {}).get("store_type", "store")
    return {"gnss_store": "GNSS store", "vod_store": "VOD store"}.get(kind, kind)


def mismatch_message(
    found: Iterable[Difference],
    repository: Mapping[str, Any],
    store_path: StoreLocation | Path | str,
) -> str:
    """The error of a run whose settings differ from its store's."""
    found = list(found)
    stored = repository[CONTENT_SETTINGS_FIELD]
    store_type = repository.get("identity", {}).get("store_type", "")
    new_store = (
        "set processing.storage.vod_store_name to e.g. 'vod-recompute'"
        if store_type == "vod_store"
        else "set processing.storage.gnss_store_name to e.g. 'gnss-recompute'"
    )
    lines = "\n".join(
        f"  {d.key}: store {_short(d.store)}, this run {_short(d.run)}" for d in found
    )
    return (
        f"The settings of this run differ from the content settings of the "
        f"{_store_label(repository)} at {store_path} in {len(found)} "
        f"key(s); nothing was written. The store's content settings were set "
        f"{_set_when(stored)}:\n{lines}\n"
        "Every run that writes to a store must have its content settings. "
        "Either use the store's settings (canvodpy config init --from-store "
        f"{store_path}), or write to a new store "
        f"({new_store}, or set another stores_root_dir)."
    )


def check_content_settings(
    repository: Mapping[str, Any],
    config: Any,
    *,
    store_path: StoreLocation | Path | str,
    migrate_command: str,
    gnss_repository: Mapping[str, Any] | None = None,
) -> None:
    """Refuse a run whose content settings differ from its store's.

    A store type without content settings (:data:`CONTENT_STORE_TYPES`) passes.

    Parameters
    ----------
    repository
        The store's repository metadata.
    config
        The run's settings.
    migrate_command
        The command that gives an older store its content settings, named
        in the error.
    gnss_repository
        The GNSS store's repository metadata, for a VOD store
        (:data:`CONTENT_STORE_TYPES`): its content-settings hash is compared
        with the VOD store's ``gnss_content_hash`` (ADR 0019 D3).

    Raises
    ------
    MissingContentSettingsError
        If the store has no content settings (created before they existed).
    ContentSettingsError
        If a content setting differs (the message lists each with both
        values), or the store's form is newer than this canvodpy reads.
    """
    identity = repository.get("identity", {})
    store_type = identity.get("store_type")
    if store_type not in CONTENT_STORE_TYPES:
        return
    stored = repository.get(CONTENT_SETTINGS_FIELD)
    if not stored:
        msg = (
            f"The {_store_label(repository)} at {store_path} has no content "
            "settings: it was created before stores kept them, so a run cannot "
            "check that its settings match the data already stored. Write "
            "them once, from the settings recorded in the store's first "
            f"commit:\n  {migrate_command}"
        )
        raise MissingContentSettingsError(msg)
    if stored.get("format", 0) > CONTENT_SETTINGS_FORMAT:
        msg = (
            f"The content settings of the store at {store_path} have form "
            f"{stored.get('format')}; this canvodpy reads up to "
            f"{CONTENT_SETTINGS_FORMAT}. Update canvodpy."
        )
        raise ContentSettingsError(msg)
    if store_type == "vod_store" and gnss_repository is not None:
        check_gnss_hash(repository, gnss_repository, store_path)
    # The site's key in the settings, as the repository metadata names it
    # (a VOD store records no ``sites`` block of its own).
    site_name = repository["spatial"]["site"]["name"]
    found = differences(
        stored,
        run_content_settings(config, site_name, store_type),
        site_name,
    )
    if found:
        raise ContentSettingsError(mismatch_message(found, repository, store_path))


def is_settings_object(config: Any) -> bool:
    """Whether ``config`` is a run's full settings (not a recorded snapshot)."""
    return hasattr(config, "sites") and hasattr(config, "sids")
