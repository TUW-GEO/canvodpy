"""Store locations and the one function that opens a store's repository.

Every repository in canVODpy is opened through :func:`open_repository`, so a
new kind of storage is added in one place: a new :class:`StoreLocation`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import icechunk

#: The command that moves a store to the metadata form of ADR 0014.
MIGRATE_COMMAND = "canvodpy store migrate-metadata"


class StoreLocation(ABC):
    """Where a store's repository lives."""

    @abstractmethod
    def storage(self) -> icechunk.Storage:
        """The Icechunk storage for this location."""

    @abstractmethod
    def __truediv__(self, relative: str | Path) -> StoreLocation:
        """The location ``relative`` below this one, of the same kind."""

    @property
    @abstractmethod
    def needs_commit_lock(self) -> bool:
        """Whether commits here must hold :func:`~.io.commit_lock`."""

    @property
    @abstractmethod
    def local_path(self) -> Path | None:
        """The directory on this machine, or ``None`` for remote storage."""


@dataclass(frozen=True)
class LocalStoreLocation(StoreLocation):
    """A store in a directory on a local file system."""

    path: Path

    def storage(self) -> icechunk.Storage:
        return icechunk.local_filesystem_storage(str(self.path))

    def __truediv__(self, relative: str | Path) -> LocalStoreLocation:
        return LocalStoreLocation(self.path / relative)

    @property
    def needs_commit_lock(self) -> bool:
        """Yes: Icechunk on a local file system can lose one of two
        concurrent commits without an error."""
        return True

    @property
    def local_path(self) -> Path:
        return self.path

    def __str__(self) -> str:
        return str(self.path)


def store_location(location: StoreLocation | Path | str) -> StoreLocation:
    """The store location ``location`` names.

    A :class:`StoreLocation` is returned as it is; a path or a string is a
    local directory (``~`` expanded).
    """
    if isinstance(location, StoreLocation):
        return location
    return LocalStoreLocation(Path(location).expanduser())


def open_repository(
    location: StoreLocation | Path | str,
    *,
    create: bool = False,
    config: icechunk.RepositoryConfig | None = None,
    expected_uuid: str | None = None,
) -> icechunk.Repository:
    """Open the repository of the store at ``location``.

    Opening never creates a repository, and creating never opens one, so a
    mistyped location fails instead of leaving an empty store behind.

    Parameters
    ----------
    create
        Create a new repository instead of opening one.
    config
        The repository configuration (compression, caching, concurrency);
        ``None`` uses Icechunk's defaults.
    expected_uuid
        The UUID of the store the caller expects, for example from a
        catalog item.
        A store with another UUID, or without repository metadata, is
        refused, so a store replaced behind the same location is never
        taken for the old one.

    Raises
    ------
    FileNotFoundError
        If ``create`` is false and no repository is at ``location``.
    FileExistsError
        If ``create`` is true and a repository is already at ``location``.
    ValueError
        If ``expected_uuid`` is given and the store has another UUID or no
        repository metadata.
    """
    where = store_location(location)
    storage = where.storage()
    exists = icechunk.Repository.exists(storage)
    if create:
        if exists:
            msg = f"A store already exists at {where}; it was not created again."
            raise FileExistsError(msg)
        return icechunk.Repository.create(storage=storage, config=config)
    if not exists:
        msg = (
            f"No store at {where}. Check the path; a run creates a store "
            "when it first writes data to it."
        )
        raise FileNotFoundError(msg)
    repo = icechunk.Repository.open(storage=storage, config=config)
    if expected_uuid is not None:
        found = _uuid(repo, where)
        if found != expected_uuid:
            msg = (
                f"The store at {where} is not the store expected: its UUID is "
                f"{found}, expected {expected_uuid}. The store at this location "
                "was replaced; nothing was opened."
            )
            raise ValueError(msg)
    return repo


def read_store_uuid(location: StoreLocation | Path | str) -> str:
    """The UUID of the store at ``location``, from its repository metadata.

    Raises
    ------
    ValueError
        If the store has no repository metadata.
    """
    where = store_location(location)
    return _uuid(open_repository(where), where)


def _uuid(repo: icechunk.Repository, where: StoreLocation) -> str:
    uuid = repo.get_metadata().get("identity", {}).get("uuid")
    if not uuid:
        msg = (
            f"The store at {where} has no repository metadata, so it has no "
            "UUID. Move it to the current form with:\n"
            f"  {MIGRATE_COMMAND} SITE --store gnss|vod"
        )
        raise ValueError(msg)
    return uuid
