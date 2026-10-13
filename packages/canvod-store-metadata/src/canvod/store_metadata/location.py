"""Store locations and the one function that opens a store's repository.

Every repository in canVODpy is opened through :func:`open_repository`, so a
new kind of storage is added in one place: a new :class:`StoreLocation`.
"""

from __future__ import annotations

import posixpath
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import icechunk

if TYPE_CHECKING:
    from canvod.config.models.compression import IcechunkConfig

#: The command that moves a store to the metadata form of ADR 0014.
MIGRATE_COMMAND = "canvodpy store migrate-metadata"


class StoreLocation(ABC):
    """Where a store's repository lives."""

    @abstractmethod
    def storage(self) -> icechunk.Storage:
        """The Icechunk storage for this location."""

    @abstractmethod
    def __truediv__(self, relative: str | Path) -> StoreLocation:
        """The location ``relative`` below this one, of the same kind.

        Raises
        ------
        ValueError
            If ``relative`` is an absolute path.
        """

    @property
    @abstractmethod
    def needs_commit_lock(self) -> bool:
        """Whether commits here must hold :func:`~.io.commit_lock`."""

    @property
    @abstractmethod
    def local_path(self) -> Path | None:
        """The directory on this machine, or ``None`` for remote storage."""

    @property
    @abstractmethod
    def access_hint(self) -> str:
        """What to check when the storage can't be reached."""


@dataclass(frozen=True)
class LocalStoreLocation(StoreLocation):
    """A store in a directory on a local file system."""

    path: Path

    def storage(self) -> icechunk.Storage:
        return icechunk.local_filesystem_storage(str(self.path))

    def __truediv__(self, relative: str | Path) -> LocalStoreLocation:
        return LocalStoreLocation(self.path / _relative(self, relative))

    @property
    def needs_commit_lock(self) -> bool:
        """Yes: Icechunk on a local file system can lose one of two
        concurrent commits without an error."""
        return True

    @property
    def local_path(self) -> Path:
        return self.path

    @property
    def access_hint(self) -> str:
        return "Check that the directory exists and can be read."

    def __str__(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class S3StoreLocation(StoreLocation):
    """A store under a prefix in an S3 bucket.

    Credentials come only from the environment (the ``AWS_*`` variables,
    ``AWS_PROFILE``) or the shared AWS files (``~/.aws/credentials``,
    ``~/.aws/config``), as do region and endpoint (``AWS_REGION``,
    ``AWS_ENDPOINT_URL``): never from the settings or the store metadata,
    and they are never logged.
    """

    bucket: str
    prefix: str

    def storage(self) -> icechunk.Storage:
        return icechunk.s3_storage(
            bucket=self.bucket, prefix=self.prefix, from_env=True
        )

    def __truediv__(self, relative: str | Path) -> S3StoreLocation:
        """The location ``relative`` below this one, ``..`` resolved.

        S3 keys are plain names: S3 itself doesn't resolve ``..``, so a
        catalog item's relative href is resolved here.

        Raises
        ------
        ValueError
            If ``relative`` is an absolute path, or leads to the bucket's
            root or out of the bucket.
        """
        prefix = posixpath.normpath(
            posixpath.join(self.prefix, str(_relative(self, relative)))
        )
        if prefix == "." or prefix.startswith(".."):
            msg = (
                f"{relative} leads out of {self} to the root of the bucket "
                "or outside it, where no store can be."
            )
            raise ValueError(msg)
        return S3StoreLocation(self.bucket, prefix)

    @property
    def needs_commit_lock(self) -> bool:
        """No: Icechunk's conditional writes on S3 keep two commits from
        overwriting each other, and there is no local directory to hold a
        lock file."""
        return False

    @property
    def local_path(self) -> None:
        return None

    @property
    def access_hint(self) -> str:
        return (
            "Credentials come from the AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY environment variables, AWS_PROFILE or "
            "~/.aws/credentials; region and endpoint from AWS_REGION and "
            "AWS_ENDPOINT_URL."
        )

    def __str__(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


def _relative(location: StoreLocation, relative: str | Path) -> PurePosixPath:
    """``relative`` as a path below ``location``; an absolute one is refused."""
    path = PurePosixPath(str(relative))
    if path.is_absolute():
        msg = (
            f"{relative} can't be joined to {location}: give a relative path, "
            "such as a site or a catalog item's href."
        )
        raise ValueError(msg)
    return path


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$")


def store_location(location: StoreLocation | Path | str) -> StoreLocation:
    """The store location ``location`` names.

    A :class:`StoreLocation` is returned as it is; ``s3://bucket/prefix``
    is a store on S3; any other path or string is a local directory (``~``
    expanded).

    Raises
    ------
    ValueError
        If an ``s3://`` URL lacks the bucket or the prefix (Icechunk creates
        no repository at a bucket's root), or the URL has another scheme.
    """
    if isinstance(location, StoreLocation):
        return location
    match = _SCHEME.match(str(location)) if isinstance(location, str) else None
    if match is None:
        return LocalStoreLocation(Path(location).expanduser())
    scheme, rest = match.groups()
    if scheme.lower() != "s3":
        msg = (
            f"Stores can't be opened at {location}: only local directories "
            "and s3://bucket/prefix are supported."
        )
        raise ValueError(msg)
    bucket, _, prefix = rest.partition("/")
    prefix = prefix.strip("/")
    if not bucket or not prefix:
        msg = (
            f"{location} names no store: give it as s3://bucket/prefix, with "
            "both a bucket and a prefix."
        )
        raise ValueError(msg)
    return S3StoreLocation(bucket, prefix)


def repository_config(
    settings: IcechunkConfig, *, compression_level: int | None = None
) -> icechunk.RepositoryConfig:
    """The repository configuration ``processing.icechunk`` asks for.

    A store's repository and the step that creates it use this one
    configuration, so a new store records the settings, not Icechunk's
    defaults.

    Parameters
    ----------
    settings
        The ``processing.icechunk`` settings.
    compression_level
        A compression level other than the one in ``settings``.
    """
    config = icechunk.RepositoryConfig.default()
    config.compression = icechunk.CompressionConfig(
        level=compression_level or settings.compression_level,
        algorithm=icechunk.CompressionAlgorithm.Zstd,
    )
    config.inline_chunk_threshold_bytes = settings.inline_chunk_threshold_bytes
    config.get_partial_values_concurrency = settings.get_partial_values_concurrency
    if settings.max_concurrent_requests is not None:
        config.max_concurrent_requests = settings.max_concurrent_requests

    if (
        settings.cache_num_chunk_refs is not None
        or settings.cache_num_bytes_chunks is not None
    ):
        # None keeps Icechunk's default for that cache
        config.caching = icechunk.CachingConfig(
            num_chunk_refs=settings.cache_num_chunk_refs,
            num_bytes_chunks=settings.cache_num_bytes_chunks,
        )

    preload = None
    if settings.manifest_preload_enabled:
        preload = icechunk.ManifestPreloadConfig(
            max_total_refs=settings.manifest_preload_max_refs,
            max_arrays_to_scan=settings.manifest_preload_max_arrays_to_scan,
            preload_if=icechunk.ManifestPreloadCondition.name_matches(
                settings.manifest_preload_pattern
            ),
        )

    splitting = None
    if settings.manifest_splitting_enabled:
        # Split every array with an "epoch" dimension every
        # manifest_splitting_epoch_range indices; arrays without that
        # dimension (for example coordinates) are left whole.
        splitting = icechunk.ManifestSplittingConfig.from_dict(
            {
                icechunk.ManifestSplitCondition.name_matches(".*"): {
                    icechunk.ManifestSplitDimCondition.DimensionName(
                        "epoch"
                    ): settings.manifest_splitting_epoch_range,
                },
            }
        )

    if settings.num_updates_per_repo_info_file is not None:
        config.num_updates_per_repo_info_file = settings.num_updates_per_repo_info_file

    if (
        settings.repo_update_max_tries is not None
        or settings.repo_update_initial_backoff_ms is not None
        or settings.repo_update_max_backoff_ms is not None
    ):
        # RepoUpdateRetryConfig is documented as
        # `icechunk.config.RepoUpdateRetryConfig` but not re-exported there
        # or at `icechunk` as of icechunk==2.1.1, an upstream gap. Prefer
        # the public path in case a later release adds it.
        try:
            from icechunk import RepoUpdateRetryConfig
        except ImportError:
            from icechunk._icechunk_python import RepoUpdateRetryConfig
        config.repo_update_retries = RepoUpdateRetryConfig(
            default=icechunk.StorageRetriesSettings(
                max_tries=settings.repo_update_max_tries,
                initial_backoff_ms=settings.repo_update_initial_backoff_ms,
                max_backoff_ms=settings.repo_update_max_backoff_ms,
            )
        )

    if preload is not None or splitting is not None:
        config.manifest = icechunk.ManifestConfig(preload=preload, splitting=splitting)
    return config


def _exists(where: StoreLocation, storage: icechunk.Storage) -> bool:
    try:
        return icechunk.Repository.exists(storage)
    except icechunk.StorageError as error:
        msg = f"The storage at {where} can't be reached. {where.access_hint}"
        raise OSError(msg) from error


def store_exists(location: StoreLocation | Path | str) -> bool:
    """Whether a store's repository is at ``location``.

    A run creates a site's stores when it first writes data, so checks
    made before that, such as a resume or a comparison with stored
    results, ask this first instead of opening a store that isn't there.

    Raises
    ------
    OSError
        If the storage at ``location`` can't be reached.
    """
    where = store_location(location)
    return _exists(where, where.storage())


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
        The repository configuration (compression, caching, concurrency).
        ``None`` creates a store with the defaults of the
        ``processing.icechunk`` settings (:func:`repository_config`), so it
        matches a store a run creates, and opens one with the configuration
        Icechunk kept with the store.
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
        If ``create`` is true and ``location`` holds files but no
        repository, or if ``expected_uuid`` is given and the store has
        another UUID or no repository metadata.
    """
    where = store_location(location)
    storage = where.storage()
    exists = _exists(where, storage)
    if create:
        if config is None:
            from canvod.config.models.compression import IcechunkConfig

            config = repository_config(IcechunkConfig())
        refused = None
        if not exists:
            try:
                return icechunk.Repository.create(storage=storage, config=config)
            except icechunk.InvalidInputError as error:
                # Icechunk creates only in an empty location. Another
                # process may have created the store since the check above.
                if not icechunk.Repository.exists(storage):
                    msg = (
                        f"{where} holds files but no store; a store is created "
                        "only in an empty location. Nothing was created."
                    )
                    raise ValueError(msg) from error
                refused = error
        msg = f"A store already exists at {where}; it was not created again."
        raise FileExistsError(msg) from refused
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
