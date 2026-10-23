"""Context-local logging helpers.

.. deprecated::
    Unused, left over from development. Use ``structlog.get_logger(__name__)``
    and ``structlog.contextvars.bound_contextvars(file=...)`` instead.
"""

import contextvars
from pathlib import Path

from canvod.utils.tools import deprecated
from canvodpy.logging.logging_config import LOGGER, get_file_logger

# ContextVar to store the active logger
CURRENT_LOGGER = contextvars.ContextVar("CURRENT_LOGGER", default=LOGGER)

_MESSAGE = (
    "`canvodpy.logging.context` is left over from development and will be "
    "removed with the next major version. Use `structlog.get_logger` and "
    "`structlog.contextvars.bound_contextvars` instead."
)


@deprecated(_MESSAGE)
def get_logger() -> object:
    """Return the logger bound to the current context."""
    return CURRENT_LOGGER.get()


@deprecated(_MESSAGE)
def set_file_context(fname: Path) -> contextvars.Token:
    """Set the current logger context to a file-specific logger.

    Parameters
    ----------
    fname : Path
        File path to bind into the logging context.

    Returns
    -------
    contextvars.Token
        Token used to restore the previous context.

    """
    flog = get_file_logger(fname)
    return CURRENT_LOGGER.set(flog)


@deprecated(_MESSAGE)
def reset_context(token: contextvars.Token) -> None:
    """Reset CURRENT_LOGGER to its previous value."""
    CURRENT_LOGGER.reset(token)
