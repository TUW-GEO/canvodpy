"""Read/write metadata to/from Icechunk store root attrs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import icechunk
import structlog
import zarr
from filelock import FileLock, Timeout
from pydantic import ValidationError
from zarr import errors as zarr_errors

from .schema import _METADATA_KEY, RepositoryMetadata, StoreMetadata

#: Name of the lock file in the store directory (see :func:`commit_lock`).
COMMIT_LOCK_NAME = ".canvodpy-commit.lock"

_logger = structlog.get_logger(__name__)
_locks: dict[Path, FileLock] = {}
_locks_guard = threading.Lock()


@contextmanager
def commit_lock(store_path: Path | str) -> Generator[None]:
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
    path = Path(store_path).resolve()
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
    store_path: Path | str,
    config: Any = None,
) -> str:
    """Commit a session, rebasing it if the branch moved since it was opened.

    The commit holds :func:`commit_lock` for ``store_path``, the store the
    session belongs to, so commits to one store run one after the other.
    Several writers may still work on one store at the same time (e.g. two
    receivers of a site): when the branch moved since a session was opened,
    ``icechunk.ConflictDetector`` rebases changes that do not overlap (e.g.
    different groups) onto the new tip; overlapping changes fail with
    ``icechunk.RebaseFailedError``.

    In a store with repository metadata (ADR 0014) the commit also writes
    the root copy and the snapshot summary of the rebased session, stores
    the lockfile text once per hash, and records software, environment and
    settings as commit metadata, next to ``metadata``. It refuses a root
    group that differs from the repository metadata.

    Every commit in canVODpy goes through this function.

    Parameters
    ----------
    config
        The settings recorded in the commit metadata: a settings object or a
        :class:`~canvod.store_metadata.schema.ConfigSnapshot`. ``None``
        loads the settings.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the root group last committed differs from the repository
        metadata (written by an older canvodpy or edited by hand).
    """
    with commit_lock(store_path):
        repository = _open_repo(Path(store_path)).get_metadata()
        if repository:
            from .snapshot import prepare_commit

            # Rebase first, so the summary describes everything the commit
            # will hold and the root group is changed by this commit only.
            session.rebase(icechunk.ConflictDetector())
            if config is None:
                from canvod.config import load_config

                config = load_config()
            root = zarr.open_group(session.store, mode="a")
            metadata = {
                **prepare_commit(
                    root, repository, store_path=store_path, config=config
                ),
                **(metadata or {}),
            }
        return session.commit(
            message, metadata=metadata, rebase_with=icechunk.ConflictDetector()
        )


def _open_repo(store_path: Path) -> icechunk.Repository:
    """Open an existing Icechunk repository."""
    storage = icechunk.local_filesystem_storage(str(store_path))
    return icechunk.Repository.open(storage=storage)


def write_metadata(
    store_path: Path,
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
        If the store already has repository metadata, or ``metadata``
        lacks a fixed field (build it with ``collect_metadata``).
    """
    try:
        repository_metadata = RepositoryMetadata.from_store_metadata(metadata)
    except ValidationError as exc:
        missing = sorted(
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()
        )
        msg = (
            f"The store metadata lacks fields a store needs when it is created "
            f"({', '.join(missing)}); build it with collect_metadata."
        )
        raise ValueError(msg) from exc

    with commit_lock(store_path):
        repo = _open_repo(store_path)
        existing = repo.get_metadata()
        if existing:
            store = existing.get("identity", {}).get("id", "unknown id")
            msg = (
                f"The store at {store_path} already has repository metadata "
                f"(store {store}); open it instead of creating it again."
            )
            raise ValueError(msg)
        repo.set_metadata(repository_metadata.model_dump(mode="json"))

        session = repo.writable_session(branch)
        zarr.open_group(session.store, mode="a")
        return commit_with_rebase(
            session,
            "Write store metadata",
            store_path=store_path,
            config=metadata.config,
        )


def read_metadata(
    store_path: Path,
    branch: str = "main",
) -> StoreMetadata:
    """Read the metadata of the tip of ``branch``.

    One :class:`StoreMetadata` from the snapshot's root copy, snapshot
    summary and commit metadata; a snapshot written before ADR 0014 is
    read from its old ``canvod_metadata`` attribute.

    Raises
    ------
    KeyError
        If no metadata found in store.
    """
    from .snapshot import REPOSITORY_METADATA_ATTR, combined_metadata

    repo = _open_repo(store_path)
    session = repo.readonly_session(branch=branch)
    root = zarr.open_group(session.store, mode="r")
    if REPOSITORY_METADATA_ATTR not in root.attrs:
        return StoreMetadata.from_root_attrs(dict(root.attrs))
    snapshot = next(iter(repo.ancestry(snapshot_id=session.snapshot_id)))
    return combined_metadata(root, snapshot.metadata)


def apply_updates(metadata: StoreMetadata, updates: dict[str, Any]) -> StoreMetadata:
    """Return a copy of ``metadata`` with dotted-key ``updates`` applied.

    Keys such as ``"temporal.updated"`` address nested fields.
    """
    data = metadata.model_dump(mode="json")

    for key, value in updates.items():
        parts = key.split(".")
        target = data
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value

    return StoreMetadata.model_validate(data)


def _repository_fields(key: str) -> bool:
    """Whether a dotted key names a field of the repository metadata."""
    model: Any = RepositoryMetadata
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
        model = annotation
    return True


def update_metadata(
    store_path: Path,
    updates: dict[str, Any],
    branch: str = "main",
) -> str:
    """Merge updates into existing metadata.

    Supports dotted keys for nested updates (e.g. "temporal.updated").

    In a store with repository metadata (ADR 0014) the snapshot summary
    and the commit metadata are written by every commit, so this only
    commits; a key naming a repository metadata field is refused.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If a key names a repository metadata field.
    """
    repo = _open_repo(store_path)
    if repo.get_metadata():
        refused = sorted(key for key in updates if _repository_fields(key))
        if refused:
            msg = (
                f"{', '.join(refused)} belong to the repository metadata of the "
                f"store at {store_path}; they change only by amendment."
            )
            raise ValueError(msg)
        session = repo.writable_session(branch)
        return commit_with_rebase(
            session, "Update store metadata", store_path=store_path
        )

    updated = apply_updates(read_metadata(store_path, branch), updates)
    session = repo.writable_session(branch)
    store = session.store
    try:
        root = zarr.open_group(store, mode="r+")
    except zarr_errors.GroupNotFoundError:
        root = zarr.open_group(store, mode="w")

    root.attrs.update(updated.to_root_attrs())
    return commit_with_rebase(session, "Update store metadata", store_path=store_path)


def metadata_exists(store_path: Path, branch: str = "main") -> bool:
    """Check if the store has repository metadata.

    ``branch`` is not used: repository metadata is on no branch. It stays
    for callers that pass it.
    """
    try:
        repo = _open_repo(store_path)
    except icechunk.IcechunkError:
        return False
    return bool(repo.get_metadata())


#: The command that moves a store to the metadata form of ADR 0014.
MIGRATE_COMMAND = "canvodpy store migrate-metadata"


def ensure_metadata(
    store_path: Path, collect: Callable[[], StoreMetadata]
) -> dict[str, Any]:
    """Return a store's repository metadata, writing it for a new store.

    Writers call this before they write data, so a store never holds data
    without its metadata. ``collect`` builds the metadata of a new store
    (``collect_metadata``); it is called only for a store that has none.

    Raises
    ------
    ValueError
        If the store holds data or old-form metadata but no repository
        metadata: it predates ADR 0014 and must be migrated first.
    """
    with commit_lock(store_path):
        repo = _open_repo(store_path)
        existing = repo.get_metadata()
        if existing:
            return existing
        session = repo.readonly_session(branch="main")
        try:
            root = zarr.open_group(session.store, mode="r")
        except zarr_errors.GroupNotFoundError:
            root = None
        if root is not None and (
            _METADATA_KEY in root.attrs or next(root.groups(), None) is not None
        ):
            msg = (
                f"The store at {store_path} was written before stores kept "
                "repository metadata; move it to the current form first:\n"
                f"  {MIGRATE_COMMAND} --store {store_path}"
            )
            raise ValueError(msg)
        write_metadata(store_path, collect())
    return _open_repo(store_path).get_metadata()


def _not_listed(names: Iterable[str], listed: Iterable[str]) -> list[str]:
    """Names that are not listed and not a listed name's pair group.

    A reference receiver is stored once per canopy it is paired with, in a
    group named ``{reference}_{canopy}``.
    """
    listed = set(listed)
    return sorted(
        name
        for name in set(names)
        if name not in listed and not any(name.startswith(f"{r}_") for r in listed)
    )


def check_receivers(
    repository: dict[str, Any], receivers: Iterable[str], *, store_path: Path | str
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
            f"  canvodpy store amend --store {store_path} --add-receiver {name} "
            '--reason "..."'
        )
        raise ValueError(msg)


def check_vod_analyses(
    repository: dict[str, Any], analyses: Iterable[str], *, store_path: Path | str
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
            f"  canvodpy store amend --store {store_path} --add-vod-analysis "
            f'{name} --reason "..."'
        )
        raise ValueError(msg)
