"""The dates of a run: ``--start``/``--end`` or ``--update-to-latest``.

A run is given its dates, or told to update the site to the latest files
(``--update-to-latest``, ``update_to_latest=True`` in Python). There is no
default: a run without either stops, so no run processes days nobody
asked for.
"""

from __future__ import annotations


class NothingStoredError(ValueError):
    """``--update-to-latest`` on a site whose GNSS store holds nothing yet."""

    def __init__(self, site: str) -> None:
        super().__init__(
            f"Nothing is stored yet for site '{site}': give the first day with "
            "--start (start= in Python)."
        )


def check_run_dates(
    start: str | None, end: str | None, *, update_to_latest: bool
) -> None:
    """Refuse a run without dates, or with dates and ``--update-to-latest``.

    Parameters
    ----------
    start, end : str or None
        The run's first and last day (YYYYDOY), as given.
    update_to_latest : bool
        Whether the run updates the site to the latest files.

    Raises
    ------
    ValueError
        If neither ``start`` nor ``update_to_latest`` is given, or
        ``update_to_latest`` comes with ``start`` or ``end``.
    """
    if update_to_latest and (start or end):
        msg = (
            "--update-to-latest chooses the dates itself: leave out --start "
            "and --end (start= and end= in Python)."
        )
        raise ValueError(msg)
    if not update_to_latest and not start:
        msg = (
            "Give the first day with --start, or --update-to-latest to process "
            "the days since the last stored day (start= or update_to_latest=True "
            "in Python)."
        )
        raise ValueError(msg)
