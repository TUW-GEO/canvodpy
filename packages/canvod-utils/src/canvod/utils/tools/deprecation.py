"""Shared deprecation-warning decorators for canVODpy packages."""

from __future__ import annotations

import functools
import inspect
import types
import warnings
from collections.abc import Callable
from typing import Any


def deprecated(message: str) -> Callable[[Any], Any]:
    """Emit a ``FutureWarning`` when the decorated object is used.

    ``FutureWarning`` rather than ``DeprecationWarning``, because Python
    shows it by default, also when the call comes from library code.

    Applied to a function, wraps the call. Applied to a class, wraps
    ``__init__`` so the warning fires on instantiation.
    """

    def decorator(obj: Any) -> Any:
        if inspect.isclass(obj):
            original_init = obj.__init__

            def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
                warnings.warn(message, FutureWarning, stacklevel=2)
                original_init(self, *args, **kwargs)

            obj.__init__ = functools.wraps(original_init)(new_init)
            return obj

        @functools.wraps(obj)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, FutureWarning, stacklevel=2)
            return obj(*args, **kwargs)

        return wrapper

    return decorator


def deprecated_argument(name: str, message: str) -> Callable[[Any], Any]:
    """Emit a ``FutureWarning`` when the argument *name* is passed.

    For an argument that is left over from development while the function
    itself stays. The warning fires whether the argument is passed by
    position or by keyword, also with its default value. Leave the
    argument out of the docstring: the API reference hides it.

    Decorates functions only; on a method, put it below ``@classmethod``
    or ``@staticmethod``. Anything else raises ``TypeError``.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not isinstance(func, types.FunctionType):
            msg = f"deprecated_argument decorates functions, not {func!r}"
            raise TypeError(msg)
        signature = inspect.signature(func)
        if name not in signature.parameters:
            msg = f"{func.__qualname__}() has no argument {name!r}"
            raise TypeError(msg)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if name in signature.bind_partial(*args, **kwargs).arguments:
                warnings.warn(message, FutureWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper

    return decorator
