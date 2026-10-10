"""Tests for the shared ``deprecated`` decorator."""

import warnings

import pytest

from canvod.utils.tools import deprecated, deprecated_argument


def test_function_warns_and_returns_result():
    @deprecated("Use new_add instead.")
    def old_add(a, b):
        """Add two numbers."""
        return a + b

    with pytest.warns(FutureWarning, match="Use new_add instead."):
        assert old_add(1, 2) == 3
    assert old_add.__name__ == "old_add"
    assert old_add.__doc__ == "Add two numbers."


def test_class_warns_on_instantiation():
    @deprecated("Use NewThing instead.")
    class OldThing:
        def __init__(self, value):
            self.value = value

    with pytest.warns(FutureWarning, match="Use NewThing instead."):
        obj = OldThing(5)
    assert obj.value == 5
    assert isinstance(obj, OldThing)


def test_warning_points_at_caller():
    @deprecated("old")
    def old():
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        old()
    assert caught[0].filename == __file__


@pytest.mark.parametrize(
    ("args", "kwargs"), [((1, 2, True), {}), ((1, 2), {"exact": True})]
)
def test_argument_warns_when_passed(args, kwargs):
    @deprecated_argument("exact", "Remove the exact argument.")
    def add(a, b, exact=None):
        """Add two numbers."""
        return a + b

    with pytest.warns(FutureWarning, match="Remove the exact argument."):
        assert add(*args, **kwargs) == 3
    assert add.__name__ == "add"


def test_argument_silent_when_left_out():
    @deprecated_argument("exact", "old")
    def add(a, b, exact=None):
        return a + b

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert add(1, 2) == 3


def test_argument_on_classmethod_points_at_caller():
    class Calc:
        @classmethod
        @deprecated_argument("exact", "old")
        def add(cls, a, b, exact=None):
            return a + b

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert Calc.add(1, 2, exact=True) == 3
    assert caught[0].filename == __file__


def test_argument_must_exist():
    with pytest.raises(TypeError, match="no argument 'exact'"):

        @deprecated_argument("exact", "old")
        def add(a, b):
            return a + b


def test_argument_needs_a_function():
    with pytest.raises(TypeError, match="decorates functions"):
        deprecated_argument("exact", "old")(staticmethod(lambda exact=None: None))
