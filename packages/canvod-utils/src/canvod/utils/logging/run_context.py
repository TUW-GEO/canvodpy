"""Per-run identifier propagation for logging.

A run_id identifies a single pipeline invocation for one site: ``canvodpy
run`` sets one per site, and a pipeline created from Python sets one when
none is set. It is threaded automatically into every
log record via a structlog processor (``canvodpy.logging.logging_config``) and, where
possible, into Icechunk commit messages, so a human or an agent can
correlate "this run" across the human log, the agent-diagnostic log, and
the data it wrote -- without any call site needing to pass it explicitly.
"""

import contextvars
import secrets
from datetime import UTC, datetime

RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "RUN_ID", default=None
)


def new_run_id(site_name: str) -> str:
    """Return a run_id for *site_name*: the site, the start time in UTC, a random part.

    The random part keeps run IDs apart when two machines start a run of
    one site in the same second; each machine has its own run history, so
    neither can number its run against the other.

    Parameters
    ----------
    site_name : str
        Name of the site the run processes.

    Returns
    -------
    str
        ``{site_name}-{YYYYMMDD-HHMMSS}-{6 hex digits}``, for example
        ``ExampleSite-20261010-030000-3f9a1c``.
    """
    return f"{site_name}-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def get_run_id() -> str | None:
    """Return the run_id bound to the current context, if any."""
    return RUN_ID.get()


def set_run_id(run_id: str) -> contextvars.Token:
    """Bind ``run_id`` to the current context.

    Parameters
    ----------
    run_id : str
        Identifier for the current pipeline run, usually from
        :func:`new_run_id`.

    Returns
    -------
    contextvars.Token
        Token used to restore the previous value via ``reset_run_id``.
    """
    return RUN_ID.set(run_id)


def reset_run_id(token: contextvars.Token) -> None:
    """Reset RUN_ID to its previous value."""
    RUN_ID.reset(token)
