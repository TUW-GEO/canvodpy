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
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import zarr
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
from .location import StoreLocation, open_repository, store_location
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
        new_id = store_id(old.spatial.site.name, store_type)
        for field in values or {}:
            check_amendable(field)
        given = _with_values(old, dict(values or {}), store_path)
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
) -> tuple[dict[str, Any], list[str], list[str], Any]:
    """The content settings a migrated GNSS store records.

    Returns ``(settings, missing, unknown, gnss_hash)``; ``gnss_hash`` is
    ``None`` for a GNSS store.
    """
    settings: dict[str, Any] = {}
    missing: list[str] = []
    for key in CONTENT_KEYS:
        if key in values:
            value = values[key]
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


def _vod_content_settings(
    recorded: Mapping[str, Any],
    values: Mapping[str, Any],
    store_path: StoreLocation | Path | str,
    site: str,
) -> tuple[dict[str, Any], list[str], list[str], Any]:
    """The content settings a migrated VOD store records (D1 keys + GNSS hash).

    Returns ``(settings, missing, unknown, gnss_hash)``. The per-group
    calculator parameters of a VOD group are recorded in the group's
    attributes, not in the content settings (ADR 0019 D2).
    """
    settings: dict[str, Any] = {}
    missing: list[str] = []
    for key in VOD_CONTENT_KEYS:
        if key in values:
            value = values[key]
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
        derived, err = _derive_gnss_hash(recorded)
        if err is None:
            gnss_hash = derived
        else:
            missing.append(GNSS_CONTENT_HASH)
    unknown = sorted(set(values) - set(VOD_CONTENT_KEYS) - {GNSS_CONTENT_HASH})
    return settings, missing, unknown, gnss_hash


def _derive_gnss_hash(recorded: Mapping[str, Any]) -> tuple[Any, str | None]:
    """The GNSS store's content-settings hash, from the recorded settings.

    Returns ``(hash, None)`` on success or ``(None, reason)`` when the GNSS
    store path is not recorded, not readable, or has no content settings.
    """
    from .location import store_location

    try:
        root = _recorded(recorded, "processing.storage.stores_root_dir")
        name = _recorded(recorded, "processing.storage.gnss_store_name")
    except KeyError:
        return None, "no GNSS store path recorded"
    try:
        gnss_path = (
            f"{str(root).rstrip('/')}/{name}"
            if isinstance(root, str) and root.startswith("s3://")
            else Path(str(root)) / name
        )
        from .io import read_repository_metadata

        repository = read_repository_metadata(store_location(gnss_path))
    except Exception:
        return None, "GNSS store not readable"
    hash_ = (
        repository.get(CONTENT_SETTINGS_FIELD, {}).get("hash") if repository else None
    )
    if not hash_:
        return None, "GNSS store has no content settings"
    return hash_, None


def migrate_content_settings(
    store_path: StoreLocation | Path | str,
    *,
    who: str,
    values: Mapping[str, Any] | None = None,
    branch: str = "main",
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
    branch
        The branch whose first commit is read.

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
                recorded, values, store_path, site
            )
        else:
            settings, missing, unknown, gnss_hash = _gnss_content_settings(
                recorded, values, repository, site, store_path
            )
        if unknown:
            msg = f"{', '.join(unknown)}: not a content setting of this store."
            raise ValueError(msg)
        if missing:
            given = " ".join(f"--set {key}=VALUE" for key in missing)
            msg = (
                f"The first commit of the store at {store_path} (snapshot "
                f"{snapshot_id[:12]}) does not record these content settings, "
                f"and they are not guessed:\n"
                + "\n".join(f"  - {key}" for key in missing)
                + f"\nGive each with the value the store's data was written "
                f"with:\n  {store_command('migrate-metadata', site, store_type)} "
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
            f"{' '.join(f'--set {f}=VALUE' for f in fields)} (in Python: "
            "values=)."
        )
        raise ValueError(msg)
    return validate_existing(StoreMetadata, data)


def _refuse_failures(
    preview: StoreMetadata, store_path: StoreLocation | Path | str
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
            "Give the missing fields with --set FIELD=VALUE (in Python: "
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
