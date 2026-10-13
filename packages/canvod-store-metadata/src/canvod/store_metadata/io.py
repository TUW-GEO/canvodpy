"""Read/write metadata to/from Icechunk store root attrs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import icechunk
import structlog
import zarr
from canvod.utils.tools import deprecated
from filelock import FileLock, Timeout
from pydantic import ValidationError
from zarr import errors as zarr_errors

from .icechunk_logs import apply_icechunk_log_filter
from .location import (
    MIGRATE_COMMAND,
    StoreLocation,
    open_repository,
    repository_config,
    store_location,
)
from .schema import (
    _METADATA_KEY,
    Amendment,
    RepositoryMetadata,
    StoreMetadata,
    describe_rule_breaks,
    rule_breaks,
)

apply_icechunk_log_filter()

#: Name of the lock file in the store directory (see :func:`commit_lock`).
COMMIT_LOCK_NAME = ".canvodpy-commit.lock"

_logger = structlog.get_logger(__name__)
_locks: dict[Path, FileLock] = {}
_locks_guard = threading.Lock()


@contextmanager
def commit_lock(store_path: StoreLocation | Path | str) -> Generator[None]:
    """Let only one commit at a time change the store at ``store_path``.

    Icechunk on a local file system is not safe for concurrent commits:
    when two commits run at the same time, both can return successfully
    while one of them is lost. This lock, a file in the store directory,
    makes every other commit wait, in this process (other threads) and in
    other processes on the same machine. A commit that waits then sees the
    commit before it, and :func:`commit_with_rebase` rebases onto it.

    The lock is re-entrant in one thread. The operating system releases it
    when the process that holds it ends.
    """
    location = store_location(store_path)
    if not location.needs_commit_lock:
        yield
        return
    if location.local_path is None:
        msg = f"The commit lock needs a local directory; {location} is not one."
        raise ValueError(msg)
    path = location.local_path.resolve()
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = _locks[path] = FileLock(path / COMMIT_LOCK_NAME)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        _logger.info("waiting_for_commit_lock", store=str(path))
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def commit_with_rebase(
    session: icechunk.Session,
    message: str,
    metadata: dict[str, Any] | None = None,
    *,
    store_path: StoreLocation | Path | str,
    config: Any = None,
    repository: dict[str, Any] | None = None,
) -> str:
    """Commit a session, rebasing it if the branch moved since it was opened.

    The commit holds :func:`commit_lock` for ``store_path``, the store the
    session belongs to, so commits to one store run one after the other.
    Several writers may still work on one store at the same time (e.g. two
    receivers of a site): when the branch moved since a session was opened,
    ``icechunk.ConflictDetector`` rebases changes that do not overlap (e.g.
    different groups) onto the new tip; overlapping changes fail with
    ``icechunk.RebaseFailedError``.

    The commit also writes the root copy and the snapshot summary of the
    rebased session (ADR 0014), stores the lockfile text once per hash, and
    records software, environment and settings as commit metadata, next to
    ``metadata``. It refuses a store without repository metadata, so no
    store holds data without it, and a root group that differs from the
    repository metadata.

    Every commit in canVODpy goes through this function, except manifest
    compaction, which goes through :func:`rewrite_manifests`.

    Parameters
    ----------
    config
        The settings recorded in the commit metadata: a settings object or a
        :class:`~canvod.store_metadata.schema.ConfigSnapshot`. ``None``
        loads the settings.
    repository
        The repository metadata the commit carries, when it is about to
        change (creation, amendment, migration): the caller writes it with
        ``Repository.set_metadata`` only after the commit succeeded, so a
        failed commit leaves the repository metadata as it was. ``None``
        uses the store's current repository metadata.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the store has no repository metadata and ``repository`` is not
        given, or the root group last committed differs from the repository
        metadata (written by an older canvodpy or edited by hand).
    """
    with commit_lock(store_path):
        repo = open_repository(store_path)
        if repository is None:
            repository = repo.get_metadata()
        if not repository:
            msg = (
                f"The store at {store_path} has no repository metadata, so it "
                "takes no data; nothing was committed. A run gives a new store "
                "its metadata before it writes data (canvodpy run, Site(...)"
                ".pipeline(), VodComputer). A store written before stores kept "
                "repository metadata is moved to the current form with:\n"
                f"  {MIGRATE_COMMAND} SITE --store gnss|vod"
            )
            raise ValueError(msg)
        from .snapshot import prepare_commit

        # Rebase first, if the branch moved, so the summary describes
        # everything the commit will hold and the root group is changed by
        # this commit only.
        branch = session.branch
        if branch is None or repo.lookup_branch(branch) != session.snapshot_id:
            session.rebase(icechunk.ConflictDetector())
        if config is None:
            from canvod.config import load_config

            config = load_config()
        root = zarr.open_group(session.store, mode="a")
        metadata = {
            **prepare_commit(root, repository, store_path=store_path, config=config),
            **(metadata or {}),
        }
        return session.commit(
            message, metadata=metadata, rebase_with=icechunk.ConflictDetector()
        )


def rewrite_manifests(
    store_path: StoreLocation | Path | str,
    message: str,
    *,
    branch: str = "main",
    config: Any = None,
) -> str:
    """Compact a branch's manifests in a commit that carries commit metadata.

    ``Repository.rewrite_manifests`` commits without a session, so it can
    write no lockfile text: when the lockfile in use is not stored in the
    store yet, a commit through :func:`commit_with_rebase` stores it first.
    In a store without repository metadata the compaction records only
    Icechunk's own metadata, as :func:`commit_with_rebase` does.

    Parameters
    ----------
    config
        The settings recorded in the commit metadata; ``None`` loads them.

    Returns
    -------
    str
        Snapshot ID of the compaction commit.
    """
    with commit_lock(store_path):
        repo = open_repository(store_path)
        repository = repo.get_metadata()
        metadata = None
        if repository:
            from .snapshot import commit_metadata, lockfile_stored

            if config is None:
                from canvod.config import load_config

                config = load_config()
            metadata, texts = commit_metadata(
                repository, config, store_path, datetime.now(UTC).isoformat()
            )
            root = zarr.open_group(repo.readonly_session(branch=branch).store, mode="r")
            if not lockfile_stored(root, texts["uv_lock_hash"]):
                commit_with_rebase(
                    repo.writable_session(branch),
                    "Store the lockfile in use",
                    store_path=store_path,
                    config=config,
                )
        return repo.rewrite_manifests(
            message, branch=branch, metadata=metadata, commit_method="new_commit"
        )


def read_repository_metadata(store_path: StoreLocation | Path | str) -> dict[str, Any]:
    """The store's repository metadata as stored (empty for a store without)."""
    return open_repository(store_path).get_metadata()


def write_metadata(
    store_path: StoreLocation | Path | str,
    metadata: StoreMetadata,
    branch: str = "main",
) -> str:
    """Write a new store's metadata.

    The repository metadata (fixed and amendable fields, ADR 0014) is
    written once; a first commit writes its root copy and the snapshot
    summary, with ``metadata.config`` as the settings in the commit
    metadata.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the store already has repository metadata, ``metadata`` lacks a
        fixed field (build it with ``collect_metadata``), or a field breaks
        a rule of its standard (e.g. a license outside SPDX).
    """
    try:
        repository_metadata = RepositoryMetadata.from_store_metadata(metadata)
    except ValidationError as exc:
        broken = rule_breaks(exc)
        if broken:
            msg = (
                f"{describe_rule_breaks(broken)}. A store is not created with "
                "metadata that breaks a rule of its standard."
            )
            raise ValueError(msg) from exc
        missing = sorted(
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()
        )
        msg = (
            f"The store metadata lacks fields a store needs when it is created "
            f"({', '.join(missing)}); build it with collect_metadata."
        )
        raise ValueError(msg) from exc

    with commit_lock(store_path):
        repo = open_repository(store_path)
        existing = repo.get_metadata()
        if existing:
            store = existing.get("identity", {}).get("id", "unknown id")
            msg = (
                f"The store at {store_path} already has repository metadata "
                f"(store {store}); open it instead of creating it again."
            )
            raise ValueError(msg)
        repository = repository_metadata.model_dump(mode="json")
        session = repo.writable_session(branch)
        zarr.open_group(session.store, mode="a")
        snapshot_id = commit_with_rebase(
            session,
            "Write store metadata",
            store_path=store_path,
            config=metadata.config,
            repository=repository,
        )
        repo.set_metadata(repository)
        return snapshot_id


def read_metadata(
    store_path: StoreLocation | Path | str,
    branch: str = "main",
    *,
    snapshot_id: str | None = None,
) -> StoreMetadata:
    """Read the metadata of a snapshot as it was when it was committed.

    One :class:`StoreMetadata` from the snapshot's root copy, snapshot
    summary and commit metadata. A snapshot written before the store kept
    repository metadata is read from its old ``canvod_metadata`` attribute
    and marked ``written_before_migration``.

    Parameters
    ----------
    branch
        Read the tip of this branch.
    snapshot_id
        Read this snapshot instead of a branch tip (e.g. one a release
        pins).

    Raises
    ------
    KeyError
        If no metadata found in store.
    """
    from .snapshot import REPOSITORY_METADATA_ATTR, combined_metadata

    repo = open_repository(store_path)
    session = (
        repo.readonly_session(snapshot_id=snapshot_id)
        if snapshot_id is not None
        else repo.readonly_session(branch=branch)
    )
    root = zarr.open_group(session.store, mode="r")
    if REPOSITORY_METADATA_ATTR not in root.attrs:
        return StoreMetadata._from_old_root_attrs(dict(root.attrs))
    snapshot = next(iter(repo.ancestry(snapshot_id=session.snapshot_id)))
    return combined_metadata(root, snapshot.metadata)


def amendments_since(
    store_path: StoreLocation | Path | str, metadata: StoreMetadata
) -> list[Amendment]:
    """Amendments made to the store after the snapshot ``metadata`` was read from."""
    current = open_repository(store_path).get_metadata().get("amendments", [])
    return [Amendment.model_validate(a) for a in current[len(metadata.amendments) :]]


@deprecated(
    "apply_updates() is left over from development and will be removed with the "
    "next major version. Change a store's description with amend_metadata()."
)
def apply_updates(metadata: StoreMetadata, updates: dict[str, Any]) -> StoreMetadata:
    """Return a copy of ``metadata`` with dotted-key ``updates`` applied.

    Keys such as ``"temporal.updated"`` address nested fields.
    """
    return _apply_updates(metadata, updates)


def _set_field(data: dict[str, Any], key: str, value: Any) -> Any:
    """Set the dotted ``key`` in ``data`` to ``value``; return the old value.

    A section on the way that is missing or unset (``None``, e.g. a
    receiver's ``antenna``) is created empty; the model check that follows
    refuses it if it cannot be.
    """
    *parents, leaf = key.split(".")
    target = data
    for part in parents:
        if target.get(part) is None:
            target[part] = {}
        target = target[part]
    old = target.get(leaf)
    target[leaf] = value
    return old


def _apply_updates(metadata: StoreMetadata, updates: dict[str, Any]) -> StoreMetadata:
    data = metadata.model_dump(mode="json")
    for key, value in updates.items():
        _set_field(data, key, value)
    return StoreMetadata.model_validate(data)


def _field_exists(model: Any, key: str) -> bool:
    """Whether a dotted key names a field of a pydantic model.

    A dict field (receivers, VOD analyses) takes any entry name, followed
    by the entry's fields.
    """
    parts = key.split(".")
    while parts:
        part = parts.pop(0)
        fields = getattr(model, "model_fields", None)
        if fields is None or part not in fields:
            return False
        annotation = fields[part].annotation
        if getattr(annotation, "__origin__", None) is dict:
            if not parts:
                return True
            parts.pop(0)  # the dict key, e.g. a receiver name
            annotation = annotation.__args__[1]
        elif (
            getattr(annotation, "__args__", None) and type(None) in annotation.__args__
        ):
            annotation = next(a for a in annotation.__args__ if a is not type(None))
        model = annotation
    return True


def _repository_fields(key: str) -> bool:
    """Whether a dotted key names a field of the repository metadata."""
    return _field_exists(RepositoryMetadata, key)


@deprecated(
    "update_metadata() is left over from development and will be removed with "
    "the next major version. Every commit now writes the snapshot summary; "
    "change a store's description with amend_metadata()."
)
def update_metadata(
    store_path: StoreLocation | Path | str,
    updates: dict[str, Any],
    branch: str = "main",
) -> str:
    """Merge updates into existing metadata.

    Supports dotted keys for nested updates (e.g. "temporal.updated").

    In a store with repository metadata (ADR 0014) the snapshot summary
    and the commit metadata are written by every commit, so this only
    commits, and only without ``updates``: every key is refused.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the store has repository metadata and ``updates`` is not empty.
    """
    repo = open_repository(store_path)
    if repo.get_metadata():
        refused = sorted(key for key in updates if _repository_fields(key))
        if refused:
            msg = (
                f"{', '.join(refused)} belong to the repository metadata of the "
                f"store at {store_path}; they change only by amendment."
            )
            raise ValueError(msg)
        if updates:
            msg = (
                f"{', '.join(sorted(updates))} are computed by every commit "
                f"to the store at {store_path} (snapshot summary, commit "
                "metadata) and cannot be set; nothing was committed."
            )
            raise ValueError(msg)
        session = repo.writable_session(branch)
        return commit_with_rebase(
            session, "Update store metadata", store_path=store_path
        )

    updated = _apply_updates(read_metadata(store_path, branch), updates)
    session = repo.writable_session(branch)
    store = session.store
    try:
        root = zarr.open_group(store, mode="r+")
    except zarr_errors.GroupNotFoundError:
        root = zarr.open_group(store, mode="w")

    root.attrs.update(updated.to_root_attrs())
    return commit_with_rebase(session, "Update store metadata", store_path=store_path)


def metadata_exists(
    store_path: StoreLocation | Path | str, branch: str = "main"
) -> bool:
    """Check if the store has repository metadata.

    ``branch`` is not used: repository metadata is on no branch. It stays
    for callers that pass it.
    """
    try:
        repo = open_repository(store_path)
    except FileNotFoundError, icechunk.IcechunkError:
        return False
    return bool(repo.get_metadata())


#: The settings field that says how a metadata change records who made it.
INITIALS_SETTING = "processing.metadata.initials"


def check_who(who: str | None) -> str:
    """Return who changes a store's metadata, refusing a missing name.

    Raises
    ------
    ValueError
        If ``who`` is missing or blank.
    """
    if not who or not who.strip():
        msg = (
            "A change of store metadata records who made it: set "
            f"{INITIALS_SETTING} in the settings (e.g. 'NFB')."
        )
        raise ValueError(msg)
    return who.strip()


_STORE_KINDS = {"gnss_store": "gnss", "vod_store": "vod", "geodesy_store": "geodesy"}


def store_command(command: str, site_name: str, store_type: str) -> str:
    """A ``canvodpy store`` command line for one site's store."""
    kind = _STORE_KINDS.get(store_type, store_type)
    return f"canvodpy store {command} {site_name} --store {kind}"


def _written_before_metadata(repo: icechunk.Repository) -> bool:
    """Whether a store without repository metadata holds data or old-form
    metadata, so it predates ADR 0014 and needs migration.
    """
    session = repo.readonly_session(branch="main")
    try:
        root = zarr.open_group(session.store, mode="r")
    except zarr_errors.GroupNotFoundError:
        return False
    return _METADATA_KEY in root.attrs or next(root.groups(), None) is not None


def ensure_metadata(
    store_path: StoreLocation | Path | str,
    collect: Callable[[], StoreMetadata],
    *,
    site_name: str,
    store_type: str,
    config: icechunk.RepositoryConfig | None = None,
) -> dict[str, Any]:
    """Return a store's repository metadata; create a missing store first.

    Writers call this before they write data, so a store never holds data
    without its metadata, and this is the only step that creates a store.
    ``collect`` builds the metadata of a new store (``collect_metadata``);
    it is called only for a store that has none.

    Parameters
    ----------
    config
        The repository configuration a new store is created with
        (:func:`~.location.repository_config`); Icechunk keeps it with the
        store. ``None`` uses the defaults of the ``processing.icechunk``
        settings.

    Raises
    ------
    ValueError
        If the store holds data or old-form metadata but no repository
        metadata: it predates ADR 0014 and must be migrated first. Also if
        the location holds files but no store.
    """
    # Created before the lock: Icechunk creates a store only in an empty
    # location, and the lock file lives in the store's directory.
    with suppress(FileExistsError):
        open_repository(store_path, create=True, config=config)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        existing = repo.get_metadata()
        if existing:
            return existing
        if _written_before_metadata(repo):
            msg = (
                f"The store at {store_path} was written before stores kept "
                "repository metadata; move it to the current form first:\n"
                f"  {store_command('migrate-metadata', site_name, store_type)}"
            )
            raise ValueError(msg)
        write_metadata(store_path, collect())
    return open_repository(store_path).get_metadata()


def ensure_store_metadata(
    store_path: Path,
    *,
    config: Any,
    site_name: str,
    store_type: str,
    source_format: str,
    names: Iterable[str],
    dask_workers: int | None = None,
    dask_threads_per_worker: int | None = None,
) -> dict[str, Any]:
    """Make a store ready for a run's data: the step every run takes first.

    Gives a new store its repository metadata from the settings, then
    refuses ``names`` the metadata doesn't list: receivers and their pair
    groups for a GNSS store, VOD analyses for a VOD store. Runs from the
    command line, Python and Airflow all take this step, so they behave
    the same.

    Parameters
    ----------
    config
        The settings of the run.
    source_format
        The reader format (GNSS store) or VOD calculator (VOD store) a new
        store records.
    names
        The groups the run will write.

    Returns
    -------
    dict
        The store's repository metadata.

    Raises
    ------
    ValueError
        If the site is not in the settings, the store predates repository
        metadata (names the migrate command), or a name is not listed in
        the metadata (names the amend command).
    """
    from .collectors import collect_metadata

    site_config = config.sites.sites.get(site_name)
    if site_config is None:
        msg = f"Site {site_name!r} is not in the settings (sites.{site_name})."
        raise ValueError(msg)

    def collect() -> StoreMetadata:
        return collect_metadata(
            config=config,
            site_name=site_name,
            site_config=site_config,
            store_type=store_type,
            source_format=source_format,
            store_path=store_path,
            dask_workers=dask_workers,
            dask_threads_per_worker=dask_threads_per_worker,
        )

    repository = ensure_metadata(
        store_path,
        collect,
        site_name=site_name,
        store_type=store_type,
        config=repository_config(config.processing.icechunk),
    )
    if store_type == "vod_store":
        check_vod_analyses(repository, names, store_path=store_path)
    else:
        check_receivers(repository, names, store_path=store_path)
    return repository


def _amend_command(repository: dict[str, Any]) -> str:
    return store_command(
        "amend",
        repository["spatial"]["site"]["name"],
        repository["identity"]["store_type"],
    )


def _not_listed(names: Iterable[str], listed: Mapping[str, Any]) -> list[str]:
    """Names that are neither a listed receiver nor one of its groups.

    A reference receiver is stored once per listed canopy receiver it is
    paired with (see :func:`~canvod.store_metadata.summary.receiver_groups`).
    """
    from .summary import receiver_groups

    groups = set().union(
        *receiver_groups(
            {name: receiver["type"] for name, receiver in listed.items()}
        ).values()
    )
    return sorted(set(names) - groups)


def check_receivers(
    repository: dict[str, Any],
    receivers: Iterable[str],
    *,
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse receivers the store's repository metadata does not list.

    Raises
    ------
    ValueError
        Naming the amend command that adds a receiver.
    """
    listed = repository.get("instruments", {}).get("receivers", {})
    missing = _not_listed(receivers, listed)
    if missing:
        name = missing[0]
        msg = (
            f"The store at {store_path} lists the receivers {sorted(listed)}; "
            f"{', '.join(map(repr, missing))} from the settings "
            "(sites.<site>.receivers) is not one of them. Receivers are added "
            "on purpose, with a reason:\n"
            f"  {_amend_command(repository)} --add-receiver {name} "
            '--reason "..."'
        )
        raise ValueError(msg)


def check_vod_analyses(
    repository: dict[str, Any],
    analyses: Iterable[str],
    *,
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse VOD analyses the VOD store's repository metadata does not list.

    Raises
    ------
    ValueError
        Naming the amend command that adds a VOD analysis.
    """
    listed = repository.get("vod_analyses", {})
    missing = sorted(set(analyses) - set(listed))
    if missing:
        name = missing[0]
        msg = (
            f"The VOD store at {store_path} lists the VOD analyses "
            f"{sorted(listed)}; {', '.join(map(repr, missing))} from the "
            "settings (sites.<site>.vod_analyses) is not one of them. VOD "
            "analyses are added on purpose, with a reason:\n"
            f"  {_amend_command(repository)} --add-vod-analysis "
            f'{name} --reason "..."'
        )
        raise ValueError(msg)
