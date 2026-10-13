"""Store locations and the one function that opens a store's repository.

Every repository in canVODpy is opened through :func:`open_repository`, so a
new kind of storage is added in one place: a new :class:`StoreLocation`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import icechunk


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

    Raises
    ------
    FileNotFoundError
        If ``create`` is false and no repository is at ``location``.
    FileExistsError
        If ``create`` is true and a repository is already at ``location``.
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
    return icechunk.Repository.open(storage=storage, config=config)
