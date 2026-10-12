"""Tests for the fluent workflow API with deferred execution."""

from unittest.mock import patch

from canvodpy.fluent import FluentWorkflow, step, terminal

# ---------------------------------------------------------------------------
# Minimal stub workflow to test decorator mechanics without real data
# ---------------------------------------------------------------------------


class _StubWorkflow:
    """Minimal workflow using the decorators for testing."""

    def __init__(self):
        self._plan: list[tuple] = []
        self.call_log: list[str] = []

    @step
    def alpha(self, value: int = 1):
        self.call_log.append(f"alpha({value})")

    @step
    def beta(self, tag: str = "x"):
        self.call_log.append(f"beta({tag})")

    @terminal
    def run(self) -> list[str]:
        return list(self.call_log)

    def explain(self) -> list[dict]:
        return [
            {"step": fn.__name__, "args": args, "kwargs": kwargs}
            for fn, args, kwargs in self._plan
        ]


# ---------------------------------------------------------------------------
# Decorator tests
# ---------------------------------------------------------------------------


class TestStepDecorator:
    """Verify that @step defers execution and enables chaining."""

    def test_step_returns_self(self):
        w = _StubWorkflow()
        ret = w.alpha(42)
        assert ret is w

    def test_step_does_not_execute(self):
        w = _StubWorkflow()
        w.alpha(1)
        assert w.call_log == [], "step body should not run until terminal"

    def test_steps_accumulate_in_plan(self):
        w = _StubWorkflow()
        w.alpha(1).beta("y").alpha(2)
        assert len(w._plan) == 3

    def test_chaining_preserves_order(self):
        w = _StubWorkflow()
        w.alpha(1).beta("y").alpha(2)
        names = [fn.__name__ for fn, _, _ in w._plan]
        assert names == ["alpha", "beta", "alpha"]

    def test_step_preserves_args(self):
        w = _StubWorkflow()
        w.alpha(42)
        _, args, kwargs = w._plan[0]
        assert args == (42,)

    def test_step_preserves_kwargs(self):
        w = _StubWorkflow()
        w.beta(tag="hello")
        _, args, kwargs = w._plan[0]
        assert kwargs == {"tag": "hello"}


class TestTerminalDecorator:
    """Verify that @terminal executes the plan then itself."""

    def test_terminal_executes_all_steps(self):
        w = _StubWorkflow()
        w.alpha(1).beta("y").alpha(2)
        result = w.run()
        assert result == ["alpha(1)", "beta(y)", "alpha(2)"]

    def test_terminal_clears_plan(self):
        w = _StubWorkflow()
        w.alpha(1).run()
        assert w._plan == []

    def test_terminal_execution_order(self):
        w = _StubWorkflow()
        w.beta("first").alpha(99).beta("last")
        result = w.run()
        assert result == ["beta(first)", "alpha(99)", "beta(last)"]

    def test_empty_plan_runs_terminal_only(self):
        w = _StubWorkflow()
        result = w.run()
        assert result == []


class TestReusability:
    """Verify that a workflow can be reused after a terminal call."""

    def test_reuse_after_terminal(self):
        w = _StubWorkflow()
        first = w.alpha(1).run()
        second = w.alpha(2).beta("z").run()
        assert first == ["alpha(1)"]
        assert second == ["alpha(1)", "alpha(2)", "beta(z)"]


class TestExplain:
    """Verify that explain() returns the plan without executing."""

    def test_explain_returns_plan(self):
        w = _StubWorkflow()
        w.alpha(1).beta("y")
        plan = w.explain()
        assert len(plan) == 2
        assert plan[0]["step"] == "alpha"
        assert plan[1]["step"] == "beta"

    def test_explain_does_not_execute(self):
        w = _StubWorkflow()
        w.alpha(1).beta("y")
        w.explain()
        assert w.call_log == [], "explain must not trigger execution"

    def test_explain_does_not_clear_plan(self):
        w = _StubWorkflow()
        w.alpha(1)
        w.explain()
        assert len(w._plan) == 1, "explain must not clear the plan"


# ---------------------------------------------------------------------------
# FluentWorkflow instantiation (mocked Site — no external drives needed)
# ---------------------------------------------------------------------------


class _FakeSite:
    """Minimal stand-in for :class:`canvodpy.api.Site`."""

    def __init__(self, name: str = "Fangorn"):
        self.name = name


def _make_workflow(**kwargs) -> FluentWorkflow:
    """Create a FluentWorkflow with a fake Site (no I/O)."""
    kwargs.setdefault("keep_vars", ["SNR"])
    return FluentWorkflow(site=_FakeSite(), **kwargs)


class TestFluentWorkflowInit:
    """Test FluentWorkflow creation."""

    def test_creates_with_site_object(self):
        fw = _make_workflow()
        assert fw._site.name == "Fangorn"

    def test_creates_with_empty_plan(self):
        fw = _make_workflow()
        assert fw._plan == []
        assert fw._datasets == {}
        assert fw._vod_result is None

    def test_chaining_returns_self(self):
        fw = _make_workflow()
        ret = fw.read("2025001").preprocess().grid()
        assert ret is fw

    def test_explain_without_execution(self):
        fw = _make_workflow()
        fw.read("2025001").preprocess().grid().vod("canopy_01", "reference_01")
        plan = fw.explain()
        assert len(plan) == 4
        assert [s["step"] for s in plan] == ["read", "preprocess", "grid", "vod"]
        assert fw._datasets == {}, "explain must not trigger execution"

    def test_repr(self):
        fw = _make_workflow()
        fw.read("2025001").grid()
        r = repr(fw)
        assert "Fangorn" in r
        assert "pending_steps=2" in r


class TestWorkflowConvenienceFunction:
    """Test the top-level canvodpy.workflow() factory."""

    def test_workflow_returns_fluent(self):
        import canvodpy

        with patch("canvodpy.fluent.Site", side_effect=lambda name: _FakeSite(name)):
            fw = canvodpy.workflow("Fangorn", keep_vars=["SNR"])
        assert isinstance(fw, FluentWorkflow)
        assert fw._site.name == "Fangorn"
