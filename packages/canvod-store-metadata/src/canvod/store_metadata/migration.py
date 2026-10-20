"""Move a store written before ADR 0014 to repository metadata.

Such a store keeps all its metadata in one root attribute,
``canvod_metadata``. :func:`migrate_metadata` writes its fixed and
amendable fields into the repository metadata, with the store id, UUID and
catalog link of ADR 0015, and commits the root copy in the current form.
The old id is kept in the migration record; snapshots from before the
migration keep their old attribute and stay readable.

A migrated store must pass the standards checks like a new one
(``validate_all(meta, recommended=False)`` is empty): fields an old store
lacks, such as its description, are given at migration time. The caller
can also replace the attributes of variables older versions wrote wrong
(e.g. ``VOD``, which inherited SNR's and theta's attributes).

canVODpy 0.x stored epochs without recording their time scale.
:func:`label_epoch_time_system` labels those it can tell are GPS time;
a group it cannot tell is rebuilt from the raw files, never shifted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
import zarr
from canvod.config.store_names import store_folder_name
from pydantic import ValidationError
from zarr import errors as zarr_errors

from .amend import check_amendable
from .content import (
    CONTENT_KEYS,
    CONTENT_SETTINGS_FIELD,
    GNSS_CONTENT_HASH,
    RECEIVER_KEYS,
    VOD_CONTENT_KEYS,
    _put,
)
from .identity import check_naming_authority, new_uuid, stac_link, store_id
from .io import (
    _set_field,
    check_who,
    commit_lock,
    commit_with_rebase,
)
from .location import StoreLocation, open_repository, store_exists, store_location
from .schema import (
    _METADATA_KEY,
    COMPUTED_FIELDS,
    MigrationRecord,
    RepositoryMetadata,
    StoreMetadata,
    describe_rule_breaks,
    rule_breaks,
    validate_existing,
)
from .snapshot import RESERVED_GROUP, preview_metadata
from .validate import validate_all

#: Attributes xarray writes to encode a variable; kept when a variable's
#: attributes are replaced.
_ENCODING_ATTRS = frozenset({"_FillValue", "coordinates"})


def migrate_metadata(
    store_path: StoreLocation | Path | str,
    *,
    who: str,
    naming_authority: str | None = None,
    values: Mapping[str, Any] | None = None,
    variable_attrs: Mapping[str, Mapping[str, Any]] | None = None,
    branch: str = "main",
    set_option: str = "--set",
) -> str:
    """Move a store's metadata to repository metadata (ADR 0014).

    Parameters
    ----------
    who
        Who migrates the store, e.g. ``"NFB"``; recorded in the migration
        record.
    naming_authority
        The naming authority (reverse DNS) for a store whose metadata has
        none; otherwise the store's own is kept.
    values
        Amendable fields to set while migrating, by dotted path, e.g.
        ``{"identity.description": "..."}``: the fields an old store lacks
        to pass the standards checks.
    variable_attrs
        New attributes by variable name, e.g. ``{"VOD": VOD_ATTRS}``. Every
        array of that name gets them in place of its own; xarray's encoding
        attributes (``_FillValue``, ``coordinates``) are kept. The changed
        arrays are listed in the migration record.
    branch
        The branch whose metadata is migrated.
    set_option
        The command-line option an error names for giving a missing field:
        ``--gnss-set`` or ``--vod-set`` under ``canvodpy store migrate``.

    Returns
    -------
    str
        Snapshot ID of the migration commit.

    Raises
    ------
    ValueError
        If ``who`` is blank, the store is already migrated, holds no store
        metadata, has no
        valid naming authority and none is given, a value names a field
        that cannot be amended, or the migrated store would fail the
        standards checks (the message lists the failures). Nothing is
        written then.
    """
    who = check_who(who)
    store_path = store_location(store_path)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        existing = repo.get_metadata()
        if existing:
            msg = (
                f"The store at {store_path} is already migrated "
                f"(store {existing.get('identity', {}).get('id', 'unknown id')})."
            )
            raise ValueError(msg)

        session = repo.readonly_session(branch=branch)
        try:
            attrs = dict(zarr.open_group(session.store, mode="r").attrs)
        except zarr_errors.GroupNotFoundError:
            attrs = {}
        if _METADATA_KEY not in attrs:
            msg = (
                f"The store at {store_path} has no store metadata to migrate "
                f"(no {_METADATA_KEY} attribute on branch {branch!r})."
            )
            raise ValueError(msg)
        old = StoreMetadata._from_old_root_attrs(attrs)

        authority = naming_authority or old.identity.naming_authority
        try:
            authority = check_naming_authority(authority)
        except ValueError:
            msg = (
                f"The store at {store_path} has no valid naming authority "
                f"({authority!r}). Give one with --naming-authority (in Python: "
                "naming_authority=), your institution's domain in reverse order, "
                "e.g. 'at.ac.tuwien'."
            )
            raise ValueError(msg) from None

        store_type = old.identity.store_type
        new_id = store_id(
            old.spatial.site.name, store_type, store_folder_name(store_path)
        )
        for field in values or {}:
            check_amendable(field)
        given = _with_values(old, dict(values or {}), store_path, set_option)
        identity = given.identity.model_copy(
            update={
                "id": new_id,
                "uuid": new_uuid(),
                "naming_authority": authority,
                "stac_link": stac_link(authority, new_id, store_type),
            }
        )
        candidate = given.model_copy(update={"identity": identity})
        _refuse_failures(
            preview_metadata(
                zarr.open_group(repo.readonly_session(branch=branch).store, mode="r"),
                RepositoryMetadata.from_store_metadata(candidate).model_dump(
                    mode="json"
                ),
            ),
            store_path,
            set_option,
        )

        session = repo.writable_session(branch)
        replaced = _replace_variable_attrs(
            zarr.open_group(session.store, mode="a"), variable_attrs or {}
        )
        migrated = given.model_copy(
            update={
                "identity": identity,
                "migration": MigrationRecord(
                    old_id=old.identity.id,
                    old_metadata_version=old.metadata_version,
                    who=who,
                    when=datetime.now(UTC).isoformat(),
                    fields_given=sorted(values or {}),
                    variables_replaced=replaced,
                ),
            }
        )
        repository = RepositoryMetadata.from_store_metadata(migrated).model_dump(
            mode="json"
        )
        snapshot_id = commit_with_rebase(
            session,
            "Migrate store metadata to repository metadata (ADR 0014)",
            store_path=store_path,
            config=old.config,
            repository=repository,
        )
        repo.set_metadata(repository)
        return snapshot_id


#: Group attribute canVODpy 0.x copied from the header of a RINEX file.
#: Its readers kept RINEX epochs as the file gives them, GPS time for the
#: files canVODpy reads (GPS and mixed observation files); SBF and NMEA
#: epochs were stored in UTC, 18 s behind GPS time.
_RINEX_VERSION_ATTR = "RINEX Version"

#: The time scale every stored epoch is in (``epoch.attrs["time_system"]``).
_GPS = "GPS"


def epochs_to_label(
    store_path: StoreLocation | Path | str,
    *,
    gnss_store: StoreLocation | Path | str | None = None,
    branch: str = "main",
) -> list[str]:
    """The data groups whose epochs :func:`label_epoch_time_system` labels.

    canVODpy 0.x stored epochs without their time scale. A GNSS group read
    from RINEX files (it records the RINEX version) holds GPS time. A VOD
    group holds the epochs of the site's GNSS store, so it holds GPS time
    when every data group of ``gnss_store`` does or will after its own
    migration. A group that records its time scale already is not listed.

    Raises
    ------
    ValueError
        If a group does not record its time scale and is not known to hold
        GPS time: a GNSS group read from SBF or NMEA files (UTC in 0.x), or
        a VOD group whose GNSS store holds such groups, is missing or is not
        given. Its epochs are not shifted: the epoch grid and the satellite
        positions were computed for the old epochs, so the store is rebuilt
        from the raw files.
    """
    from .summary import _observation_groups

    store_path = store_location(store_path)
    root = _root_group(store_path, branch)
    unlabelled = {
        path: group
        for path, group in _observation_groups(root).items()
        if group["epoch"].attrs.get("time_system") is None
    }
    if not unlabelled:
        return []
    if _store_type(root, store_path) != "vod_store":
        not_rinex = sorted(
            path
            for path, group in unlabelled.items()
            if _RINEX_VERSION_ATTR not in group.attrs
        )
        if not_rinex:
            _refuse_unknown_time_system(
                store_path, not_rinex, "were not read from RINEX files"
            )
        return sorted(unlabelled)
    if gnss_store is None:
        _refuse_unknown_time_system(
            store_path, sorted(unlabelled), "come from a GNSS store that was not given"
        )
    gnss_store = store_location(gnss_store)
    try:
        epochs_to_label(gnss_store, branch=branch)
    except ValueError:
        _refuse_unknown_time_system(
            store_path,
            sorted(unlabelled),
            f"come from the GNSS store at {gnss_store}, which holds epochs not "
            "read from RINEX files",
        )
    except Exception:
        _refuse_unknown_time_system(
            store_path,
            sorted(unlabelled),
            f"come from the GNSS store at {gnss_store}, which cannot be read",
        )
    return sorted(unlabelled)


def label_epoch_time_system(
    store_path: StoreLocation | Path | str,
    *,
    gnss_store: StoreLocation | Path | str | None = None,
    branch: str = "main",
) -> tuple[list[str], str | None]:
    """Record GPS time on epochs canVODpy 0.x stored without a time scale.

    Every stored epoch is GPS time and records it
    (``epoch.attrs["time_system"]``); a write refuses a group whose epochs
    do not. :func:`epochs_to_label` says which groups are labelled and
    which are refused. Only the attribute changes; the epochs stay as
    stored. For a store with repository metadata (migrate it first).

    Parameters
    ----------
    gnss_store
        The site's GNSS store, for a VOD store: its epochs come from there.

    Returns
    -------
    tuple[list[str], str | None]
        The labelled groups and the snapshot ID of the commit; ``([],
        None)`` if every group records its time scale.

    Raises
    ------
    ValueError
        See :func:`epochs_to_label`. Nothing is written then.
    """
    store_path = store_location(store_path)
    with commit_lock(store_path):
        groups = epochs_to_label(store_path, gnss_store=gnss_store, branch=branch)
        if not groups:
            return [], None
        repo = open_repository(store_path)
        session = repo.writable_session(branch)
        root = zarr.open_group(session.store, mode="a")
        for path in groups:
            group = root[path]
            assert isinstance(group, zarr.Group)
            group["epoch"].attrs["time_system"] = _GPS
        snapshot_id = commit_with_rebase(
            session,
            "Record that the epochs are GPS time: "
            + ", ".join(groups)
            + " (stored by canVODpy 0.x without their time scale)",
            store_path=store_path,
            repository=repo.get_metadata(),
        )
        return groups, snapshot_id


def _root_group(store_path: StoreLocation, branch: str) -> zarr.Group:
    """The store's root group on ``branch``, read-only."""
    session = open_repository(store_path).readonly_session(branch=branch)
    return zarr.open_group(session.store, mode="r")


def _store_type(root: zarr.Group, store_path: StoreLocation) -> str:
    """The store type, from the repository metadata or the old root attribute."""
    repository = open_repository(store_path).get_metadata()
    if repository:
        return repository["identity"]["store_type"]
    old = root.attrs.get(_METADATA_KEY)
    if isinstance(old, dict):
        return old.get("identity", {}).get("store_type", "")
    return ""


def _refuse_unknown_time_system(
    store_path: StoreLocation, groups: list[str], why: str
) -> NoReturn:
    """Refuse groups whose epochs may not be GPS time."""
    listed = "\n".join(f"  - {group}" for group in groups)
    msg = (
        f"The epochs of these groups of the store at {store_path} record no "
        f"time scale and {why}:\n{listed}\n"
        "canVODpy 0.x stored SBF and NMEA epochs in UTC, 18 s behind GPS "
        "time. They are not shifted: the epoch grid and the satellite "
        "positions were computed for the old epochs. Rebuild the store from "
        "the raw files with the current canVODpy (canvodpy run, writing to "
        "a new stores_root_dir)."
    )
    raise ValueError(msg)


def first_recorded_settings(
    store_path: StoreLocation | Path | str, branch: str = "main"
) -> tuple[str, dict[str, Any]] | None:
    """The settings recorded in the store's first commit that records any.

    A commit records its settings in its commit metadata (ADR 0014); a
    commit from before, in the ``config`` section of the root attribute
    ``canvod_metadata``. Returns the snapshot ID and the settings, ``None``
    if no commit records settings.
    """
    repo = open_repository(store_path)
    for snapshot in reversed(list(repo.ancestry(branch=branch))):
        recorded = (snapshot.metadata or {}).get("config")
        if not recorded:
            session = repo.readonly_session(snapshot_id=snapshot.id)
            try:
                attrs = zarr.open_group(session.store, mode="r").attrs
            except zarr_errors.GroupNotFoundError:
                continue
            old_form = attrs.get(_METADATA_KEY)
            recorded = old_form.get("config") if isinstance(old_form, dict) else None
        # A store created with made-up metadata records empty settings.
        if isinstance(recorded, dict) and any(
            v for k, v in recorded.items() if k != "config_hash"
        ):
            return snapshot.id, recorded
    return None


def _recorded(settings: Mapping[str, Any], key: str) -> Any:
    """A content setting in recorded settings (a ``ConfigSnapshot``).

    The snapshot keeps ``sids`` and ``processing`` (with its sections) at
    the top. Raises ``KeyError`` if the key is not recorded.
    """
    data: Any = settings
    for part in key.split("."):
        if not isinstance(data, Mapping) or part not in data:
            raise KeyError(key)
        data = data[part]
    return data


def _gnss_content_settings(
    recorded: Mapping[str, Any],
    values: Mapping[str, Any],
    repository: Mapping[str, Any],
    site: str,
    store_path: StoreLocation | Path | str,
    vod_store: StoreLocation | Path | str | None = None,
) -> tuple[dict[str, Any], list[str], list[str], Any]:
    """The content settings a migrated GNSS store records.

    Returns ``(settings, missing, unknown, gnss_hash)``; ``gnss_hash`` is
    ``None`` for a GNSS store.

    The settings the data show are taken from the data
    (:func:`_settings_from_data`), not from the recorded settings; those
    of the VOD data from ``vod_store``, the site's VOD store, if it is
    given and readable.
    """
    settings: dict[str, Any] = {}
    missing: list[str] = []
    from_data = _settings_from_data(store_path, _GNSS_SWITCHES, preprocessing=True)
    if vod_store is not None:
        try:
            from_data |= _settings_from_data(
                vod_store, _VOD_SWITCHES, preprocessing=False
            )
        except Exception:  # no VOD store: the recorded settings count
            pass
    for key in CONTENT_KEYS:
        if key in values:
            value = values[key]
        elif key in from_data:
            value = from_data[key]
            if value is _UNCLEAR:
                missing.append(key)
                continue
        else:
            try:
                value = _recorded(recorded, key)
            except KeyError:
                missing.append(key)
                continue
        _put(settings, key, value)
    receivers: dict[str, dict[str, Any]] = {}
    listed = repository.get("instruments", {}).get("receivers", {})
    for name, receiver in listed.items():
        entry: dict[str, Any] = {}
        for key in RECEIVER_KEYS:
            dotted = f"sites.{site}.receivers.{name}.{key}"
            if dotted in values:
                entry[key] = values[dotted]
            elif key in receiver:
                entry[key] = receiver[key]
            elif key == "paired_canopies" and receiver.get("type") == "canopy":
                entry[key] = None  # never set for a canopy receiver
            else:
                missing.append(dotted)
        receivers[name] = entry
    _put(settings, f"sites.{site}.receivers", receivers)
    unknown = sorted(
        set(values)
        - set(CONTENT_KEYS)
        - {
            f"sites.{site}.receivers.{name}.{key}"
            for name in listed
            for key in RECEIVER_KEYS
        }
    )
    return settings, missing, unknown, None


#: Content settings that say whether a GNSS store holds a variable.
_GNSS_SWITCHES = {"processing.params.store_radial_distance": "r"}

#: Content settings that say whether a VOD store holds a variable. The GNSS
#: store records them too (ADR 0019), read from the site's VOD store.
_VOD_SWITCHES = {
    "processing.params.store_delta_snr": "delta_snr",
    "processing.params.store_radial_diff": "radial_diff",
}

#: The content setting of a GNSS store's preprocessing steps.
_PREPROCESSING_KEY = "processing.preprocessing"

#: Group attribute canVODpy 0.x wrote when its preprocessing pipeline ran.
_OLD_PREPROCESSING_ATTR = "preprocessing_ops"

#: A setting the data groups disagree on: it must be given.
_UNCLEAR = object()


def _settings_from_data(
    store_path: StoreLocation | Path | str,
    switches: Mapping[str, str],
    *,
    preprocessing: bool,
) -> dict[str, Any]:
    """Content settings the store's data groups show, by key.

    canVODpy 0.x recorded settings its runs did not follow: the
    preprocessing settings with every run, though ``canvodpy run`` never
    applied them, and ``store_delta_snr``, though VOD always held
    ``delta_snr``. So a setting the data show is read from the data:

    - each ``store_*`` switch of ``switches`` (:data:`_GNSS_SWITCHES`,
      :data:`_VOD_SWITCHES`): whether the data groups hold its variable;
    - ``processing.preprocessing``, if ``preprocessing``: none (``null``)
      when no data group
      shows a preprocessing step, in its attributes (``preprocessing_ops``,
      canVODpy 0.x; ``Preprocessing``) or its log book (``preprocessing``
      column). Steps that did run are taken from the recorded settings.

    A switch whose variable some groups hold and others don't maps to
    :data:`_UNCLEAR`. A store without data groups shows nothing.
    """
    from canvod.config.models.preprocessing import PREPROCESSING_ATTR

    from .summary import _observation_groups

    groups = list(
        _observation_groups(_root_group(store_location(store_path), "main")).values()
    )
    if not groups:
        return {}
    shown: dict[str, Any] = {}
    for key, variable in switches.items():
        held = {variable in group for group in groups}
        shown[key] = held.pop() if len(held) == 1 else _UNCLEAR
    if preprocessing and not any(
        _shows_preprocessing(group, PREPROCESSING_ATTR) for group in groups
    ):
        shown[_PREPROCESSING_KEY] = None
    return shown


def _shows_preprocessing(group: zarr.Group, attr: str) -> bool:
    """Whether a data group shows a preprocessing step."""
    if group.attrs.get(_OLD_PREPROCESSING_ATTR) or group.attrs.get(attr):
        return True
    table = group.get("metadata/table")
    if isinstance(table, zarr.Group) and "preprocessing" in table:
        column = table["preprocessing"]
        return isinstance(column, zarr.Array) and any(
            str(record) for record in np.asarray(column[...])
        )
    return False


def _vod_content_settings(
    recorded: Mapping[str, Any],
    values: Mapping[str, Any],
    store_path: StoreLocation | Path | str,
    site: str,
    gnss_store: StoreLocation | Path | str | None = None,
) -> tuple[dict[str, Any], list[str], list[str], Any]:
    """The content settings a migrated VOD store records (D1 keys + GNSS hash).

    Returns ``(settings, missing, unknown, gnss_hash)``. The per-group
    calculator parameters of a VOD group are recorded in the group's
    attributes, not in the content settings (ADR 0019 D2). The settings the
    data show are taken from the data (:func:`_settings_from_data`).
    """
    settings: dict[str, Any] = {}
    missing: list[str] = []
    from_data = _settings_from_data(store_path, _VOD_SWITCHES, preprocessing=False)
    for key in VOD_CONTENT_KEYS:
        if key in values:
            value = values[key]
        elif key in from_data:
            value = from_data[key]
            if value is _UNCLEAR:
                missing.append(key)
                continue
        else:
            try:
                value = _recorded(recorded, key)
            except KeyError:
                missing.append(key)
                continue
        _put(settings, key, value)
    gnss_hash: Any = None
    if GNSS_CONTENT_HASH in values:
        gnss_hash = values[GNSS_CONTENT_HASH]
    else:
        derived, err = _derive_gnss_hash(recorded, gnss_store)
        if err is None:
            gnss_hash = derived
        else:
            missing.append(GNSS_CONTENT_HASH)
    unknown = sorted(set(values) - set(VOD_CONTENT_KEYS) - {GNSS_CONTENT_HASH})
    return settings, missing, unknown, gnss_hash


def _derive_gnss_hash(
    recorded: Mapping[str, Any],
    gnss_store: StoreLocation | Path | str | None = None,
) -> tuple[Any, str | None]:
    """The GNSS store's content-settings hash.

    Read from ``gnss_store``, the site's GNSS store where the settings put
    it now; if it is not given or not readable, from the GNSS store at the
    path the recorded settings name (the stores may have moved since).
    Returns ``(hash, None)`` on success or ``(None, reason)`` when no GNSS
    store is readable or it has no content settings.
    """
    from .io import read_repository_metadata

    candidates: list[StoreLocation | Path | str] = []
    if gnss_store is not None:
        candidates.append(gnss_store)
    try:
        root = _recorded(recorded, "processing.storage.stores_root_dir")
        name = _recorded(recorded, "processing.storage.gnss_store_name")
    except KeyError:
        pass
    else:
        candidates.append(
            f"{str(root).rstrip('/')}/{name}"
            if isinstance(root, str) and root.startswith("s3://")
            else Path(str(root)) / name
        )
    if not candidates:
        return None, "no GNSS store path given or recorded"
    repository = None
    for candidate in candidates:
        try:
            repository = read_repository_metadata(store_location(candidate))
        except Exception:
            continue
        break
    else:
        return None, "GNSS store not readable"
    hash_ = (
        (repository.get(CONTENT_SETTINGS_FIELD) or {}).get("hash")
        if repository
        else None
    )
    if not hash_:
        return None, "GNSS store has no content settings"
    return hash_, None


def migrate_content_settings(
    store_path: StoreLocation | Path | str,
    *,
    who: str,
    values: Mapping[str, Any] | None = None,
    gnss_store: StoreLocation | Path | str | None = None,
    vod_store: StoreLocation | Path | str | None = None,
    branch: str = "main",
    command: str | None = None,
    set_option: str = "--set",
) -> str:
    """Give a store its content settings, from the settings of its first commit.

    For a store created before stores kept content settings (ADR 0019).
    Every content setting is taken from the settings recorded in the
    store's first commit (:func:`first_recorded_settings`), each receiver's
    type and reader format from the repository metadata. A setting not
    recorded there (an older canvodpy, or a reference receiver's
    ``paired_canopies``, which no commit records) is not guessed: it must
    be given in ``values``, or nothing is written and the error lists what
    is missing.

    Parameters
    ----------
    who
        Who migrates the store, e.g. ``"NFB"``; recorded with the content
        settings.
    values
        Content settings by their key in ``canvod-settings.yaml``, e.g.
        ``{"sites.rosalia.receivers.reference_01.paired_canopies":
        ["canopy_01"]}``: those the first commit doesn't record. A value
        given replaces a recorded one.
    gnss_store
        The site's GNSS store, for a VOD store: its content-settings hash
        is recorded (``gnss_content_hash``). Not given, or not readable:
        the GNSS store at the path the first commit's settings name.
    vod_store
        The site's VOD store, for a GNSS store: whether its groups hold
        ``delta_snr`` and ``radial_diff`` gives ``store_delta_snr`` and
        ``store_radial_diff``, which the GNSS store records too.
    branch
        The branch whose first commit is read.
    command, set_option
        The command line and option an error names for giving a missing
        setting; by default ``canvodpy store migrate-metadata`` and
        ``--set``.

    Returns
    -------
    str
        Snapshot ID of the commit that carries the new root copy.

    Raises
    ------
    ValueError
        If ``who`` is blank, the store has no repository metadata (migrate
        it first), already has content settings, is a store type without
        them, no commit records settings, or settings are missing.
    """
    from canvod.config.models import SidsConfig

    from .content import CONTENT_STORE_TYPES, stored_form
    from .io import store_command
    from .schema import ConfigSnapshot

    who = check_who(who)
    values = dict(values or {})
    store_path = store_location(store_path)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        repository = repo.get_metadata()
        if not repository:
            msg = (
                f"The store at {store_path} has no repository metadata; migrate "
                "it to the current form first (migrate_metadata)."
            )
            raise ValueError(msg)
        store_type = repository["identity"]["store_type"]
        if store_type not in CONTENT_STORE_TYPES:
            msg = f"A {store_type} keeps no content settings."
            raise ValueError(msg)
        if repository.get(CONTENT_SETTINGS_FIELD):
            msg = f"The store at {store_path} already has content settings."
            raise ValueError(msg)
        first = first_recorded_settings(store_path, branch)
        if first is None:
            msg = (
                f"No commit of the store at {store_path} records its settings, "
                "so its content settings are unknown; write the data to a new "
                "store."
            )
            raise ValueError(msg)
        snapshot_id, recorded = first

        site = repository["spatial"]["site"]["name"]
        if store_type == "vod_store":
            settings, missing, unknown, gnss_hash = _vod_content_settings(
                recorded, values, store_path, site, gnss_store
            )
        else:
            settings, missing, unknown, gnss_hash = _gnss_content_settings(
                recorded, values, repository, site, store_path, vod_store
            )
        if unknown:
            msg = f"{', '.join(unknown)}: not a content setting of this store."
            raise ValueError(msg)
        if missing:
            given = " ".join(f"{set_option} {key}=VALUE" for key in missing)
            command = command or store_command("migrate-metadata", site, store_type)
            msg = (
                f"The first commit of the store at {store_path} (snapshot "
                f"{snapshot_id[:12]}) does not record these content settings, "
                f"and they are not guessed:\n"
                + "\n".join(f"  - {key}" for key in missing)
                + f"\nGive each with the value the store's data was written "
                f"with:\n  {command} "
                f"{given}"
            )
            raise ValueError(msg)

        resolved_sids = None
        if store_type == "gnss_store":
            resolved_sids = SidsConfig.model_validate(settings["sids"]).get_sids()
        content = stored_form(
            settings,
            resolved_sids,
            set_by=who,
            origin="migrated",
            gnss_content_hash=gnss_hash,
        )
        content["migrated_from_snapshot"] = snapshot_id
        content["values_given"] = sorted(values)
        updated = {**repository, CONTENT_SETTINGS_FIELD: content}
        session = repo.writable_session(branch)
        if store_type == "vod_store":
            unknown_calculators = _record_vod_calculator_params(session)
            if unknown_calculators:
                listed = "\n".join(
                    f"  - {name!r}" for name in sorted(unknown_calculators)
                )
                msg = (
                    f"The VOD store at {store_path} has groups of a "
                    "calculator whose parameters the migration cannot "
                    "record (ADR 0019 D2):\n"
                    f"{listed}\n"
                    "A group written before the parameters were recorded "
                    "is otherwise never checked. Record its parameters by "
                    "writing it again, or use a calculator whose parameters "
                    "are empty (tau_omega)."
                )
                raise ValueError(msg)
        commit_id = commit_with_rebase(
            session,
            "Write content settings from the first commit (ADR 0019)",
            store_path=store_path,
            config=ConfigSnapshot.model_validate(recorded),
            repository=updated,
        )
        repo.set_metadata(updated)
        return commit_id


#: Group attributes of a VOD data group that record its calculator and its
#: parameters. The names match ``canvod.store.store`` (ADR 0019 D2);
#: canvod-store-metadata cannot import it, so they are kept in step here.
_VOD_CALCULATOR_ATTR = "calculator"
_VOD_CALCULATOR_PARAMS_ATTR = "calculator_params"

#: Calculators whose parameters are always empty (ADR 0019 D2): the migration
#: records ``{}`` for them. Any other calculator's parameters cannot be
#: derived, so the migration lists its groups as unknown.
_EMPTY_PARAMS_CALCULATORS = {"tau_omega"}


def _record_vod_calculator_params(
    session: Any,
) -> set[str]:
    """Record a VOD store's per-group calculator parameters (ADR 0019 D2).

    A group written before the parameters were recorded is otherwise never
    checked. Each VOD data group is ``{calculator}/{analysis}``; the
    calculator's parameters are recorded on the group. A calculator whose
    parameters are always empty (``tau_omega``) is recorded as ``{}``; any
    other calculator is returned, so the migration can list its groups as
    unknown (its parameters cannot be derived from the store).

    Returns
    -------
    set[str]
        Calculator names whose groups the migration cannot record.
    """
    root = zarr.open_group(session.store, mode="a")
    unknown: set[str] = set()
    for calc_name, calc in root.groups():
        if calc_name == RESERVED_GROUP:
            continue
        for analysis, group in calc.groups():
            if analysis == RESERVED_GROUP:
                continue
            if calc_name in _EMPTY_PARAMS_CALCULATORS:
                group.attrs[_VOD_CALCULATOR_ATTR] = calc_name
                group.attrs[_VOD_CALCULATOR_PARAMS_ATTR] = json.dumps({})
            else:
                unknown.add(calc_name)
    return unknown


def _with_values(
    old: StoreMetadata,
    values: dict[str, Any],
    store_path: StoreLocation | Path | str,
    set_option: str,
) -> StoreMetadata:
    """``old`` with ``values`` set; refused if it breaks a rule of a standard.

    Reading an old store only warns about a broken rule; the migrated
    store's repository metadata is new metadata, so the value must be
    fixed now. A field the migration commit computes again only warns.
    """
    data = old.model_dump(mode="json")
    for field, value in values.items():
        _set_field(data, field, value)
    try:
        return StoreMetadata.model_validate(data)
    except ValidationError as error:
        breaks = rule_breaks(error)
        if len(breaks) < error.error_count():
            raise
    refused = [b for b in breaks if b.field not in COMPUTED_FIELDS]
    if refused:
        fields = sorted({b.field for b in refused})
        msg = (
            f"The store at {store_path} cannot be migrated: "
            f"{describe_rule_breaks(refused)}. Give the value with "
            f"{' '.join(f'{set_option} {f}=VALUE' for f in fields)} (in Python: "
            "values=)."
        )
        raise ValueError(msg)
    return validate_existing(StoreMetadata, data)


def _refuse_failures(
    preview: StoreMetadata, store_path: StoreLocation | Path | str, set_option: str
) -> None:
    """Refuse a migration whose result would fail the standards checks."""
    failures = [
        issue
        for issues in validate_all(preview, recommended=False).values()
        for issue in issues
    ]
    if failures:
        listed = "\n".join(f"  - {issue}" for issue in failures)
        msg = (
            f"The store at {store_path} would fail the standards checks after "
            f"migration:\n{listed}\n"
            f"Give the missing fields with {set_option} FIELD=VALUE (in Python: "
            "values=). ACDD `summary` comes from identity.description, "
            "spatial.bbox from spatial.geospatial_lat and spatial.geospatial_lon."
        )
        raise ValueError(msg)


def _replace_variable_attrs(
    root: zarr.Group, variable_attrs: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Give every array named in ``variable_attrs`` its new attributes.

    Returns the paths of the changed arrays.
    """
    if not variable_attrs:
        return []
    changed = []
    for path, node in root.members(max_depth=None):
        name = path.rsplit("/", 1)[-1]
        if isinstance(node, zarr.Array) and name in variable_attrs:
            kept = {k: v for k, v in node.attrs.items() if k in _ENCODING_ATTRS}
            node.attrs.put({**kept, **variable_attrs[name]})
            changed.append(path)
    return sorted(changed)


#: The variable a GNSS store holds when its runs read CLK files.
CLOCK_VARIABLE = "clock"
#: The content setting that turns the CLK files on.
FETCH_CLOCK_KEY = "processing.aux_data.fetch_clock"


def _fetch_clock(repository: Mapping[str, Any]) -> Any:
    # The field is None while the content settings are not written yet.
    settings = (repository.get(CONTENT_SETTINGS_FIELD) or {}).get("settings") or {}
    return settings.get("processing", {}).get("aux_data", {}).get("fetch_clock")


def _clock_groups(root: zarr.Group) -> list[str]:
    return sorted(
        name
        for name, group in root.groups()
        if name != RESERVED_GROUP and CLOCK_VARIABLE in set(group.array_keys())
    )


def clock_to_drop(
    store_path: StoreLocation | Path | str, branch: str = "main"
) -> list[str] | None:
    """The groups whose ``clock`` variable :func:`drop_clock` removes.

    ``None``: nothing to do, no group holds the variable and the store
    doesn't record ``fetch_clock: true``. An empty list: no group holds the
    variable, but the content settings record ``fetch_clock: true``.
    """
    store_path = store_location(store_path)
    groups = _clock_groups(_root_group(store_path, branch))
    repository = open_repository(store_path).get_metadata() or {}
    if not groups and _fetch_clock(repository) is not True:
        return None
    return groups


def drop_clock(
    store_path: StoreLocation | Path | str,
    *,
    who: str,
    config: Any = None,
    branch: str = "main",
) -> str | None:
    """Remove the ``clock`` variable of a GNSS store; record ``fetch_clock: false``.

    Since v1.0.0 runs read no CLK files by default, and VOD doesn't use the
    clock. A store made with ``fetch_clock: true`` holds a ``clock``
    variable, and a run without it is refused twice: its content settings
    differ, and its data lack a variable of the groups. This removes the
    variable from every group and records ``fetch_clock: false`` in the
    content settings, with the old value and hash
    (:func:`~.content.changed_content_settings`). Snapshots from before
    keep the variable.

    Parameters
    ----------
    who
        Who migrates the store, e.g. ``"NFB"``.
    config
        The settings recorded in the commit metadata; ``None`` loads them.

    Returns
    -------
    str or None
        Snapshot ID of the commit, or ``None`` if there was nothing to do
        (:func:`clock_to_drop`).

    Raises
    ------
    ValueError
        If ``who`` is blank, or the store is not a GNSS store with content
        settings (migrate them first).
    """
    from .content import changed_content_settings

    who = check_who(who)
    store_path = store_location(store_path)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        repository = repo.get_metadata() or {}
        if repository.get("identity", {}).get("store_type") != "gnss_store":
            msg = f"The store at {store_path} is not a GNSS store with metadata."
            raise ValueError(msg)
        content = repository.get(CONTENT_SETTINGS_FIELD)
        if not content:
            msg = (
                f"The store at {store_path} has no content settings; migrate "
                "them first (migrate_content_settings)."
            )
            raise ValueError(msg)
        session = repo.writable_session(branch)
        root = zarr.open_group(session.store, mode="r+")
        groups = _clock_groups(root)
        fetch_clock = _fetch_clock(repository)
        if not groups and fetch_clock is not True:
            return None
        for name in groups:
            group = root[name]
            assert isinstance(group, zarr.Group)  # _clock_groups lists groups
            del group[CLOCK_VARIABLE]
        updated = dict(repository)
        if fetch_clock is not False:
            updated[CONTENT_SETTINGS_FIELD] = changed_content_settings(
                content,
                key=FETCH_CLOCK_KEY,
                new=False,
                who=who,
                reason=(
                    "canvodpy v1.0.0 reads no CLK files by default; the "
                    f"'{CLOCK_VARIABLE}' variable was removed"
                ),
            )
        commit_id = commit_with_rebase(
            session,
            f"Remove the '{CLOCK_VARIABLE}' variable; record fetch_clock: false",
            store_path=store_path,
            config=config,
            repository=updated,
        )
        repo.set_metadata(updated)
        return commit_id


def gnss_content_hash_behind(
    store_path: StoreLocation | Path | str,
    gnss_store: StoreLocation | Path | str,
) -> bool:
    """Whether a VOD store records a hash its GNSS store had before a change.

    True if :func:`follow_gnss_content_hash` would commit: the VOD store's
    ``gnss_content_hash`` is not the GNSS store's hash but one the GNSS
    store had before a migration changed its content settings.
    """
    from .content import CHANGES_FIELD

    if not store_exists(store_location(store_path)) or not store_exists(
        store_location(gnss_store)
    ):
        return False
    gnss = open_repository(store_location(gnss_store)).get_metadata() or {}
    gnss_content = gnss.get(CONTENT_SETTINGS_FIELD) or {}
    repository = open_repository(store_location(store_path)).get_metadata() or {}
    recorded = (repository.get(CONTENT_SETTINGS_FIELD) or {}).get(GNSS_CONTENT_HASH)
    if not recorded or not gnss_content or recorded == gnss_content["hash"]:
        return False
    earlier = {change["old_hash"] for change in gnss_content.get(CHANGES_FIELD, [])}
    return recorded in earlier


def follow_gnss_content_hash(
    store_path: StoreLocation | Path | str,
    gnss_store: StoreLocation | Path | str,
    *,
    who: str,
    config: Any = None,
    branch: str = "main",
) -> str | None:
    """Record a GNSS store's new content-settings hash in its VOD store.

    A VOD store records the content-settings hash of its GNSS store
    (``gnss_content_hash``, ADR 0019 D1). When a migration changed the GNSS
    store's content settings (:func:`drop_clock`), the VOD store follows,
    but only if the hash it records is one the GNSS store had before such
    a change: a VOD store computed from other GNSS data is refused.

    Returns
    -------
    str or None
        Snapshot ID of the commit, or ``None`` if the VOD store records the
        GNSS store's hash already.

    Raises
    ------
    ValueError
        If ``who`` is blank, either store has no content settings, or the
        VOD store records a hash the GNSS store never had.
    """
    from .content import CHANGES_FIELD, changed_content_settings

    who = check_who(who)
    store_path = store_location(store_path)
    gnss = open_repository(store_location(gnss_store)).get_metadata() or {}
    gnss_content = gnss.get(CONTENT_SETTINGS_FIELD)
    if not gnss_content:
        msg = f"The GNSS store at {gnss_store} has no content settings."
        raise ValueError(msg)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        repository = repo.get_metadata() or {}
        content = repository.get(CONTENT_SETTINGS_FIELD)
        if not content or not content.get(GNSS_CONTENT_HASH):
            msg = (
                f"The VOD store at {store_path} records no gnss_content_hash; "
                "migrate its content settings first (migrate_content_settings)."
            )
            raise ValueError(msg)
        recorded = content[GNSS_CONTENT_HASH]
        if recorded == gnss_content["hash"]:
            return None
        earlier = {change["old_hash"] for change in gnss_content.get(CHANGES_FIELD, [])}
        if recorded not in earlier:
            msg = (
                f"The VOD store at {store_path} records gnss_content_hash "
                f"{recorded}, a hash the GNSS store at {gnss_store} never had: "
                "the VOD was computed from a GNSS store with other content "
                "settings. Compute it again, in a new VOD store."
            )
            raise ValueError(msg)
        updated = {
            **repository,
            CONTENT_SETTINGS_FIELD: changed_content_settings(
                content,
                key=GNSS_CONTENT_HASH,
                new=gnss_content["hash"],
                who=who,
                reason="the GNSS store's content settings were migrated",
            ),
        }
        commit_id = commit_with_rebase(
            repo.writable_session(branch),
            "Record the GNSS store's migrated content-settings hash",
            store_path=store_path,
            config=config,
            repository=updated,
        )
        repo.set_metadata(updated)
        return commit_id
