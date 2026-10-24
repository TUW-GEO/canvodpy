"""Read/write metadata to/from Icechunk store root attrs."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import icechunk
import structlog
import zarr
from canvod.config.store_names import OLD_GNSS_STORE_NAME, STORE_TYPE_KINDS
from canvod.utils.tools import deprecated
from filelock import FileLock, Timeout
from pydantic import ValidationError
from zarr import errors as zarr_errors

from .icechunk_logs import apply_icechunk_log_filter
from .identity import check_store_folder
from .layout import DAY_BLOCK_INDEX_ATTR, is_day_block_group
from .location import (
    SITE_MIGRATE_COMMAND,
    StoreLocation,
    open_repository,
    repository_config,
    store_exists,
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

#: Tries in all of a commit that lost a conflict to another run's commit.
#: Before the n-th try again it waits ``CONFLICT_WAIT_SECONDS * 2**(n-1)``
#: plus up to half of that at random, so two runs that collided do not try
#: again at the same moment (grilling on concurrent writers, Q10; #339).
CONFLICT_TRIES = 5
CONFLICT_WAIT_SECONDS = 1.0


#: How long a run that lost the creation of a store to another run waits
#: for that run's repository metadata (:func:`ensure_metadata`, #358).
CREATION_WAIT_SECONDS = 60.0


class StoreCreatedByAnotherRunError(ValueError):
    """Another run created the store after this run found it without metadata."""


def wait_after_conflict(retry: int) -> float:
    """Wait before try ``retry + 1`` of a commit that lost a conflict.

    Returns
    -------
    float
        The seconds waited: they double with every retry and have a
        random part.
    """
    base = CONFLICT_WAIT_SECONDS * 2 ** (retry - 1)
    seconds = base * (1 + random.random() / 2)  # noqa: S311 (not for security)
    time.sleep(seconds)
    return seconds


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
    rebase: bool = True,
    keep_summary: bool = False,
) -> str:
    """Commit a session, rebasing it if the branch moved since it was opened.

    The commit holds :func:`commit_lock` for ``store_path``, the store the
    session belongs to, so commits to one store run one after the other.
    Several writers may still work on one store at the same time (e.g. two
    receivers of a site): when the branch moved since a session was opened,
    ``icechunk.ConflictDetector`` rebases changes that do not overlap (e.g.
    different groups) onto the new tip; overlapping changes fail with
    ``icechunk.RebaseFailedError``.

    A commit of data checks the run's content settings against the
    store's at the tip, after the rebase (ADR 0019): another run may have
    created the store or written first. A commit that changes the
    repository metadata (creation, amendment, migration) is not checked.

    The commit also writes the root copy and the snapshot summary of the
    rebased session (ADR 0014); the summary is updated from the log-book
    rows added since this process's last commit to the branch, and rebuilt
    from the whole store at its first (ADR 0021,
    :mod:`~canvod.store_metadata.summary_state`). It records software, environment and
    settings as commit metadata, next to ``metadata``. The lockfile text is
    stored once per hash: before a commit of data, in a commit of its own
    when the branch does not hold it yet (:func:`store_lockfile`), so two
    runs' data commits don't both write it and conflict (#352); a commit
    that changes the repository metadata carries it itself.

    It refuses a store without repository metadata, so no store holds data
    without it, and a root group that differs from the repository
    metadata.

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
    rebase
        ``False`` commits only onto the snapshot the session was opened
        on: if the branch moved, the commit fails with
        ``icechunk.ConflictError`` instead of rebasing. The creation of a
        store uses it, so of two runs that create one store at the same
        time only one commit lands (:func:`write_metadata`).
    keep_summary
        ``True`` keeps the snapshot summary of the snapshot before, with
        only its time updated, instead of computing it from the data: for a
        commit that writes no data, such as growing day blocks
        (``MyIcechunkStore.grow_day_blocks``). It writes the same summary a
        computation would (ADR 0014), without reading every group's log
        book. The commit is refused unless its only changes are new day
        blocks in day-block groups: epoch axes grown at the end, epoch
        chunks and new block-index entries. It is also refused together
        with ``repository``, and if the root group holds no summary.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the store has no repository metadata and ``repository`` is not
        given, or the root group last committed differs from the repository
        metadata (written by an older canvodpy or edited by hand), or
        ``keep_summary`` is set and the commit is more than new day blocks.
    ContentSettingsError
        If the run's content settings differ from the store's.
    """
    changes_repository = repository is not None
    if keep_summary and changes_repository:
        msg = (
            f"A commit to {store_path} that changes the repository metadata "
            "cannot keep the snapshot summary: the summary's spatial extent "
            "and receivers come from it. Commit it with a summary computed "
            "from the data."
        )
        raise ValueError(msg)
    parts: dict[str, float] = {}
    started = mark = time.perf_counter()

    def lap(part: str) -> None:
        nonlocal mark
        now = time.perf_counter()
        parts[f"{part}_seconds"] = now - mark
        mark = now

    with commit_lock(store_path):
        lap("lock_wait")
        repo = open_repository(store_path)
        if keep_summary:
            _check_writes_no_data(session, repo, store_path)
        if repository is None:
            repository = repo.get_metadata()
        if not repository:
            msg = (
                f"The store at {store_path} has no repository metadata, so it "
                "takes no data; nothing was committed. A run gives a new store "
                "its metadata before it writes data (canvodpy run, Site(...)"
                ".pipeline(), VodComputer). A store written before stores kept "
                "repository metadata is moved to the current form with:\n"
                f"  {SITE_MIGRATE_COMMAND} SITE"
            )
            raise ValueError(msg)
        from .snapshot import prepare_commit
        from .summary_state import forget_summary_state, summary_state

        if config is None:
            from canvod.config import load_config

            config = load_config()
        branch = session.branch
        stores_lockfile_first = not changes_repository and branch is not None
        lap("open")
        if not changes_repository:
            _check_content_at_tip(repository, config, store_path)
        lap("content_check")
        if stores_lockfile_first:
            store_lockfile(
                repo, branch, repository, store_path=store_path, config=config
            )
        lap("lockfile_check")
        # Rebase first, if the branch moved, so the summary describes
        # everything the commit will hold and the root group is changed by
        # this commit only.
        if rebase and (
            branch is None or repo.lookup_branch(branch) != session.snapshot_id
        ):
            session.rebase(icechunk.ConflictDetector())
        lap("rebase")
        root = zarr.open_group(session.store, mode="a")
        # The summary is updated from the rows this commit adds (ADR 0021);
        # if the commit fails, the next one reads the store again.
        state = (
            summary_state(store_path, branch)
            if branch is not None and not keep_summary
            else None
        )
        try:
            metadata = {
                **prepare_commit(
                    root,
                    repository,
                    store_path=store_path,
                    config=config,
                    write_environment=not stores_lockfile_first,
                    keep_summary=keep_summary,
                    summarize=(
                        (lambda receivers: state.summarize(session, repo, receivers))
                        if state is not None
                        else None
                    ),
                ),
                **(metadata or {}),
            }
            lap("summary")
            if not rebase:
                snapshot_id = session.commit(message, metadata=metadata)
            else:
                snapshot_id = session.commit(
                    message,
                    metadata=metadata,
                    rebase_with=icechunk.ConflictDetector(),
                )
        except BaseException:
            if state is not None and branch is not None:
                forget_summary_state(store_path, branch)
            raise
        lap("icechunk_commit")
    lap("lock_release")
    _log_commit_parts(store_path, message, time.perf_counter() - started, parts)
    return snapshot_id


def _check_writes_no_data(
    session: icechunk.Session,
    repo: icechunk.Repository,
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse a session whose changes are more than new day blocks.

    A day-block growth resizes arrays of day-block groups along the epoch
    axis, writes the epoch values of the new blocks and adds the new days
    to the groups' block index. The summary of a day-block group reads its
    cadences from the block index and its time span from the log book, not
    from the epoch values. Anything else could change the snapshot summary,
    so the session is compared with the snapshot it was opened on.

    Raises
    ------
    ValueError
        Naming the changes that are not day-block growth.
    """
    diff = session.status()
    before = zarr.open_group(
        repo.readonly_session(snapshot_id=session.snapshot_id).store, mode="r"
    )
    after = zarr.open_group(session.store, mode="r")

    # The layout marker is read after the changes only: a changed marker
    # is refused by _group_changes.
    def day_block_group(path: str) -> bool:
        group = path.rsplit("/", 1)[0].strip("/")
        return bool(group) and is_day_block_group(after[group].attrs)

    other = [
        *(f"new array {path}" for path in diff.new_arrays),
        *(f"new group {path}" for path in diff.new_groups),
        *(f"deleted array {path}" for path in diff.deleted_arrays),
        *(f"deleted group {path}" for path in diff.deleted_groups),
        *(f"moved {move}" for move in diff.moved_nodes),
        *(
            f"chunks of {path}"
            for path in diff.updated_chunks
            if path.rsplit("/", 1)[-1] != "epoch" or not day_block_group(path)
        ),
        *(
            change
            for path in diff.updated_groups
            for change in _group_changes(before, after, path.strip("/"))
        ),
        *(
            change
            for path in diff.updated_arrays
            for change in _array_changes(
                before, after, path.strip("/"), day_block_group(path)
            )
        ),
    ]
    if other:
        msg = (
            f"A commit to {store_path} that keeps the snapshot summary may "
            "only grow day blocks, but this one also changes: "
            f"{', '.join(sorted(other))}. Commit it with a summary computed "
            "from the data."
        )
        raise ValueError(msg)


def _group_changes(before: zarr.Group, after: zarr.Group, path: str) -> list[str]:
    """What changed in a group's attributes, besides new block-index days."""
    if not path:
        return ["the root group"]
    old, new = dict(before[path].attrs), dict(after[path].attrs)
    if not (is_day_block_group(old) and is_day_block_group(new)):
        return [f"the attributes of {path}"]
    old_index = old.pop(DAY_BLOCK_INDEX_ATTR, {})
    new_index = new.pop(DAY_BLOCK_INDEX_ATTR, {})
    changes = [f"the attributes of {path}"] if old != new else []
    changes += [
        f"the block of {day} in {path}"
        for day in old_index
        if new_index.get(day) != old_index[day]
    ]
    return changes


def _array_changes(
    before: zarr.Group, after: zarr.Group, path: str, in_day_block_group: bool
) -> list[str]:
    """What changed in an array's metadata, besides growing its epoch axis."""
    old, new = before[path], after[path]
    assert isinstance(old, zarr.Array) and isinstance(new, zarr.Array)
    old_meta, new_meta = old.metadata.to_dict(), new.metadata.to_dict()
    old_meta.pop("shape"), new_meta.pop("shape")
    dims = [str(d) for d in getattr(new.metadata, "dimension_names", None) or ()]
    grows_epoch = (
        in_day_block_group
        and "epoch" in dims
        and all(
            n >= o if dim == "epoch" else n == o
            for dim, o, n in zip(dims, old.shape, new.shape, strict=True)
        )
    )
    return [] if grows_epoch and old_meta == new_meta else [f"the array {path}"]


#: Commits of this process per store, for :func:`_log_commit_parts`.
_commit_counts: dict[str, int] = {}


def _log_commit_parts(
    store_path: StoreLocation | Path | str,
    message: str,
    seconds: float,
    parts: Mapping[str, float],
) -> None:
    """Log the seconds of a commit's parts as the event ``commit_parts``.

    Into the JSON log only (``machine/performance.json``), not as a stage
    of the run history. ``commit_number`` counts this process's commits to
    the store, so slow first commits can be told from slow commits.
    """
    store = str(store_location(store_path))
    with _locks_guard:
        number = _commit_counts[store] = _commit_counts.get(store, 0) + 1
    _logger.info(
        "commit_parts",
        store=store,
        message=message,
        commit_number=number,
        duration_seconds=round(seconds, 4),
        **{part: round(value, 4) for part, value in parts.items()},
    )


def store_lockfile(
    repo: icechunk.Repository,
    branch: str,
    repository: dict[str, Any],
    *,
    store_path: StoreLocation | Path | str,
    config: Any,
) -> str | None:
    """Store the lockfile text in use in a commit of its own, unless ``branch`` has it.

    The text is stored once per hash (ADR 0014). Two runs that start with
    the same new lockfile may both find it missing: the second commit then
    conflicts, finds the text stored by the first, and goes on.

    Returns
    -------
    str | None
        Snapshot ID of the new commit; ``None`` if the text was stored
        already, or no lockfile is in use.
    """
    from .snapshot import commit_metadata, lockfile_stored, prepare_commit

    _, texts = commit_metadata(
        repository, config, store_path, datetime.now(UTC).isoformat()
    )
    lock_hash = texts["uv_lock_hash"]

    def stored() -> bool:
        tip = repo.readonly_session(branch=branch)
        return lockfile_stored(zarr.open_group(tip.store, mode="r"), lock_hash)

    if stored():
        return None
    session = repo.writable_session(branch)
    root = zarr.open_group(session.store, mode="a")
    metadata = prepare_commit(root, repository, store_path=store_path, config=config)
    try:
        return session.commit(
            "Store the lockfile in use",
            metadata=metadata,
            rebase_with=icechunk.ConflictDetector(),
        )
    except icechunk.ConflictError, icechunk.RebaseFailedError:
        if stored():
            return None
        raise


def _check_content_at_tip(
    repository: dict[str, Any], config: Any, store_path: StoreLocation | Path | str
) -> None:
    """Refuse a commit whose settings differ from the store's content settings.

    Checked only for a run's full settings (not a recorded snapshot) and a
    store that has content settings: a store without them is refused when
    the run starts (:func:`ensure_store_metadata`).
    """
    from .content import (
        CONTENT_SETTINGS_FIELD,
        check_content_settings,
        is_settings_object,
    )

    if not is_settings_object(config) or not repository.get(CONTENT_SETTINGS_FIELD):
        return
    check_content_settings(
        repository,
        config,
        store_path=store_path,
        migrate_command=_migrate_command(repository),
    )


def _migrate_command(repository: dict[str, Any]) -> str:
    return store_command(
        "migrate-metadata",
        repository["spatial"]["site"]["name"],
        repository["identity"]["store_type"],
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
            from .snapshot import commit_metadata

            if config is None:
                from canvod.config import load_config

                config = load_config()
            metadata, _ = commit_metadata(
                repository, config, store_path, datetime.now(UTC).isoformat()
            )
            store_lockfile(
                repo, branch, repository, store_path=store_path, config=config
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
    StoreCreatedByAnotherRunError
        If the store already has repository metadata, or another run
        committed its creation first. A store on S3 has no commit lock, so
        two runs may both find it without metadata; the creation commit
        does not rebase, so only one of them creates it (#358).
    ValueError
        If ``metadata`` lacks a fixed field (build it with
        ``collect_metadata``), or a field breaks a rule of its standard
        (e.g. a license outside SPDX).
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

    from .snapshot import REPOSITORY_METADATA_ATTR

    with commit_lock(store_path):
        repo = open_repository(store_path)
        existing = repo.get_metadata()
        if existing:
            store = existing.get("identity", {}).get("id", "unknown id")
            msg = (
                f"The store at {store_path} already has repository metadata "
                f"(store {store}); open it instead of creating it again."
            )
            raise StoreCreatedByAnotherRunError(msg)
        repository = repository_metadata.model_dump(mode="json")
        session = repo.writable_session(branch)
        root = zarr.open_group(session.store, mode="a")
        created_meanwhile = (
            f"Another run created the store at {store_path} first; nothing "
            "was committed."
        )
        if REPOSITORY_METADATA_ATTR in root.attrs:
            # Committed, but its repository metadata is not written yet.
            raise StoreCreatedByAnotherRunError(created_meanwhile)
        try:
            snapshot_id = commit_with_rebase(
                session,
                "Write store metadata",
                store_path=store_path,
                config=metadata.config,
                repository=repository,
                rebase=False,
            )
        except icechunk.ConflictError as exc:
            raise StoreCreatedByAnotherRunError(created_meanwhile) from exc
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


def store_command(command: str, site_name: str, store_type: str) -> str:
    """A ``canvodpy store`` command line for one site's store."""
    kind = STORE_TYPE_KINDS.get(store_type, store_type)
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

    Two runs may create one store at the same time (on S3, which has no
    commit lock): the run that loses waits up to
    :data:`CREATION_WAIT_SECONDS` for the other run's repository metadata
    and returns it, so it goes on with the other run's store; its own
    settings are then checked against that store's content settings
    (#358).

    Raises
    ------
    ValueError
        If the store holds data or old-form metadata but no repository
        metadata: it predates ADR 0014 and must be migrated first. Also if
        the location holds files but no store, or another run created the
        store but wrote no repository metadata in time.
    """
    # Created before the lock: Icechunk creates a store only in an empty
    # location, and the lock file lives in the store's directory.
    with suppress(FileExistsError):
        open_repository(store_path, create=True, config=config)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        existing = repo.get_metadata()
        if existing:
            mismatch = check_store_folder(existing, store_path)
            if mismatch:
                raise ValueError(mismatch)
            return existing
        if _written_before_metadata(repo):
            msg = (
                f"The store at {store_path} was written before stores kept "
                "repository metadata; move it to the current form first:\n"
                f"  {SITE_MIGRATE_COMMAND} {site_name}"
            )
            raise ValueError(msg)
        try:
            write_metadata(store_path, collect())
        except StoreCreatedByAnotherRunError:
            _logger.info("store_created_by_another_run", store=str(store_path))
        else:
            return open_repository(store_path).get_metadata()
    return _wait_for_repository_metadata(store_path)


def _wait_for_repository_metadata(
    store_path: StoreLocation | Path | str,
) -> dict[str, Any]:
    """The repository metadata another run writes after its creation commit.

    The creating run writes it right after the commit
    (:func:`write_metadata`); this waits up to
    :data:`CREATION_WAIT_SECONDS`.
    """
    deadline = time.monotonic() + CREATION_WAIT_SECONDS
    while True:
        existing = open_repository(store_path).get_metadata()
        if existing:
            return existing
        if time.monotonic() > deadline:
            msg = (
                f"Another run created the store at {store_path} but wrote no "
                f"repository metadata within {CREATION_WAIT_SECONDS:.0f} s; it "
                "may have stopped. This run wrote nothing. The store holds no "
                "data yet; ask whoever started the other run before you "
                "remove it and run again."
            )
            raise ValueError(msg)
        time.sleep(0.5)


def refuse_old_gnss_folder(
    store_path: StoreLocation | Path | str, site_name: str
) -> None:
    """Refuse a GNSS store write while the site's old GNSS folder holds a store.

    Before v1.0.0 the GNSS store's folder was ``rinex``. A run writing to
    the GNSS store next to it would start a second GNSS store, or write to
    one while the old one waits for its migration (#456).

    Raises
    ------
    ValueError
        If ``rinex`` next to the GNSS store holds a store; names
        ``canvodpy store migrate SITE``.
    """
    where = store_location(store_path)
    # A local path resolves '..' only through folders that exist, and the
    # GNSS store's folder may not exist yet.
    old = (
        store_location(where.local_path.parent / OLD_GNSS_STORE_NAME)
        if where.local_path is not None
        else where / f"../{OLD_GNSS_STORE_NAME}"
    )
    if not store_exists(old):
        return
    msg = (
        f"The site {site_name!r} still has its GNSS store in {old}, the GNSS "
        "store's folder before v1.0.0; this run wrote nothing, so that no "
        f"second GNSS store starts next to it at {where}. Move the store "
        f"with:\n  {SITE_MIGRATE_COMMAND} {site_name}"
    )
    raise ValueError(msg)


def ensure_store_metadata(
    store_path: StoreLocation | Path | str,
    *,
    config: Any,
    site_name: str,
    store_type: str,
    source_format: str | None,
    names: Iterable[str],
    dask_workers: int | None = None,
    dask_threads_per_worker: int | None = None,
    gnss_repository: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a store ready for a run's data: the step every run takes first.

    Gives a new store its repository metadata from the settings, then
    refuses ``names`` the metadata doesn't list: receivers and their pair
    groups for a GNSS store, VOD analyses for a VOD store. Then refuses
    settings that differ from the store's content settings, and a store
    without them (ADR 0019). Runs from the
    command line, Python and Airflow all take this step, so they behave
    the same.

    Parameters
    ----------
    config
        The settings of the run.
    source_format
        The format of the reader that read the data (GNSS store) or the
        VOD calculator (VOD store) a new store records. ``None`` when it
        is unknown: then only a store that already has its metadata is
        accepted.
    names
        The groups the run will write.

    Returns
    -------
    dict
        The store's repository metadata.

    Raises
    ------
    ValueError
        If the site is not in the settings, the store is new and
        ``source_format`` is ``None``, the store predates repository
        metadata (names the migrate command), a name is not listed in
        the metadata, or a GNSS store's naming recipe differs from the
        settings' (both name the amend command).
    ContentSettingsError
        If the settings differ from the store's content settings, or the
        store has none (names the migrate command).
    """
    from .collectors import collect_metadata
    from .content import check_content_settings

    names = list(names)

    site_config = config.sites.sites.get(site_name)
    if site_config is None:
        msg = f"Site {site_name!r} is not in the settings (sites.{site_name})."
        raise ValueError(msg)

    def collect() -> StoreMetadata:
        if source_format is None:
            msg = (
                f"The new {store_type} at {store_path} cannot record its "
                f"source_format: no format is known for {', '.join(names)}."
            )
            raise ValueError(msg)
        return collect_metadata(
            config=config,
            site_name=site_name,
            site_config=site_config,
            store_type=store_type,
            source_format=source_format,
            store_path=store_path,
            dask_workers=dask_workers,
            dask_threads_per_worker=dask_threads_per_worker,
            gnss_repository=gnss_repository,
        )

    if store_type == "gnss_store":
        refuse_old_gnss_folder(store_path, site_name)
        # Before a new store is created: it must record each recipe's sha256.
        current_recipes(site_config, site_name)
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
        check_recipes(repository, site_config, site_name, store_path=store_path)
    check_content_settings(
        repository,
        config,
        store_path=store_path,
        migrate_command=store_command("migrate-metadata", site_name, store_type),
        gnss_repository=gnss_repository,
    )
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


def check_recipes(
    repository: dict[str, Any],
    site_config: Any,
    site_name: str,
    *,
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse naming recipes that differ from the ones the store was made with.

    A store records, per receiver, its naming recipe and the sha256 of the
    recipe file. A run finds files with the recipe of the settings; a
    different recipe, or the same one with other content, would find other
    files than the days already stored. Receivers without a recipe in the
    settings and in the store are not checked.

    Raises
    ------
    ValueError
        Naming the receiver, both sha256s and the amend command that
        records the new recipe.
    """
    from canvod.utils.remote_file import recorded_name

    listed = repository.get("instruments", {}).get("receivers", {})
    for name, (recipe, sha256) in current_recipes(site_config, site_name).items():
        entry = listed.get(name)
        if entry is None or (recipe is None and entry.get("recipe") is None):
            continue
        stored_recipe = entry.get("recipe")
        # A store made before stores kept only the file name of a recipe
        # URL holds the whole URL.
        if stored_recipe is not None:
            stored_recipe = recorded_name(stored_recipe)
        stored = (stored_recipe, entry.get("recipe_sha256"))
        if stored == (recipe, sha256):
            continue
        msg = (
            f"Receiver {name!r} of the store at {store_path} was made with "
            f"naming recipe {_recipe_label(*stored)}; the settings give "
            f"{_recipe_label(recipe, sha256)}. A run finds files with the "
            "recipe of the settings, so it would find other files than the "
            "days the store holds. If the new recipe is meant, record it, "
            "with a reason:\n"
            f"  {_amend_command(repository)} --update-recipe {name} "
            '--reason "..."'
        )
        raise ValueError(msg)


def current_recipes(
    site_config: Any, site_name: str
) -> dict[str, tuple[str | None, str | None]]:
    """Each receiver's naming recipe in the settings and the sha256 of its file.

    The recipe is given as a store records it: a recipe URL by its file name.

    Raises
    ------
    ValueError
        If a recipe is not found, so its sha256 is unknown.
    """
    from canvod.utils.remote_file import recorded_name

    from .collectors import recipe_sha256_of

    recipes: dict[str, tuple[str | None, str | None]] = {}
    for name, receiver_config in site_config.receivers.items():
        recipe = getattr(receiver_config, "recipe", None)
        sha256 = recipe_sha256_of(site_name, recipe) if recipe else None
        if recipe and sha256 is None:
            msg = (
                f"Found no naming recipe {recipe!r} of receiver {name!r}. "
                "If canvod-filemap is missing, install it with: uv add "
                "canvod-filemap (in a clone of the canvodpy repository: uv "
                "sync --group filemap). Then check that `canvodpy config "
                f"validate --site {site_name}` finds it."
            )
            raise ValueError(msg)
        recipes[name] = (recorded_name(recipe) if recipe else None, sha256)
    return recipes


def _recipe_label(recipe: str | None, sha256: str | None) -> str:
    """A recipe and its short sha256, for a message."""
    if recipe is None:
        return "none"
    if sha256 is None:
        return f"{recipe!r} (no sha256 recorded)"
    return f"{recipe!r} (sha256 {sha256[:12]})"


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
