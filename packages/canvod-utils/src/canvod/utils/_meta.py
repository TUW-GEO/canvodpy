"""Version of canvod-utils, read from the installed package."""

from importlib.metadata import version as _version

__version__ = _version("canvod-utils")
