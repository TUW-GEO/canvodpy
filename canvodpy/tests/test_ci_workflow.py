"""The CI workflow gates every pull request through one check, ``ci-ok`` (#633).

``main`` requires ``ci-ok`` only, so ``ci-ok`` must wait for every other
job and fail when any of them failed or was cancelled. The expensive
jobs run unless the ``changes`` job found a docs-only pull request, the
S3 tests only when it found a change to store code (#634); pushes to
``main`` and runs by hand always run everything.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

#: The condition of a job that a docs-only pull request skips: only an
#: explicit 'false' skips it, an empty output runs it.
FULL = "needs.changes.outputs.full != 'false'"


def _load(name: str) -> dict:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text())
    # YAML 1.1 reads the key `on` as True.
    workflow["on"] = workflow.pop(True)
    return workflow


CI = _load("ci.yml")
JOBS = CI["jobs"]


def _needs(job: dict) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def test_triggers():
    assert set(CI["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert CI["on"]["push"]["branches"] == ["main"]


def test_ci_ok_needs_every_job_and_always_runs():
    ci_ok = JOBS["ci-ok"]
    assert _needs(ci_ok) == set(JOBS) - {"ci-ok"}
    assert ci_ok["if"] == "always()"


def test_ci_ok_fails_on_a_failed_or_cancelled_job():
    (step,) = JOBS["ci-ok"]["steps"]
    assert "contains(needs.*.result, 'failure')" in step["if"]
    assert "contains(needs.*.result, 'cancelled')" in step["if"]
    assert step["run"] == "exit 1"


def test_main_and_runs_by_hand_bypass_the_classification():
    for output in JOBS["changes"]["outputs"].values():
        assert output.startswith("${{ github.event_name != 'pull_request' ||")
    for step in JOBS["changes"]["steps"]:
        assert step["if"] == "github.event_name == 'pull_request'"


def test_platform_tests_skipped_on_docs_only():
    job = JOBS["platform-tests"]
    assert "changes" in _needs(job)
    assert job["if"] == FULL
    assert job["uses"] == "./.github/workflows/test_platforms.yml"


def test_s3_tests_only_for_store_changes():
    job = JOBS["s3"]
    assert "changes" in _needs(job)
    assert job["if"] == "needs.changes.outputs.s3 != 'false'"
    assert job["uses"] == "./.github/workflows/test_s3.yml"
    assert "workflow_call" in _load("test_s3.yml")["on"]


def test_docs_quality_always_runs_with_the_offline_link_check():
    job = JOBS["docs-quality"]
    assert "if" not in job
    assert job["uses"] == "./.github/workflows/docs_quality.yml"
    assert job["with"]["offline_links"] is True
    # The weekly run keeps the external link check; a run by hand of ci.yml
    # must not fail on an outside server.
    called = _load("docs_quality.yml")
    assert "workflow_call" in called["on"]
    assert "!inputs.offline_links" in called["jobs"]["links"]["env"]["FULL"]


def test_platform_tests_report_the_coverage_on_ubuntu():
    job = JOBS["platform-tests"]
    assert job["with"]["coverage"] is True
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    steps = _load("test_platforms.yml")["jobs"]["build"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    on_ubuntu = "inputs.coverage && matrix.os == 'ubuntu-latest'"
    for name in ("Run Tests with Coverage", "Upload to Coveralls", "Coverage comment"):
        assert by_name[name]["if"] == on_ubuntu, name
    assert by_name["Run Tests"]["if"] == f"${{{{ !({on_ubuntu}) }}}}"


def test_code_quality_skips_its_expensive_jobs_on_docs_only():
    job = JOBS["code-quality"]
    assert "changes" in _needs(job)
    assert job["uses"] == "./.github/workflows/code_quality.yml"
    assert job["with"]["docs_only"] == "${{ needs.changes.outputs.full == 'false' }}"

    called = _load("code_quality.yml")
    assert "workflow_call" in called["on"]
    expensive = {"type_consistency", "build", "package_imports"}
    for name, step in called["jobs"].items():
        if name in expensive:
            # Started by its own trigger, the input is null: it runs.
            assert step["if"] == "${{ !inputs.docs_only }}", name
        else:
            assert "if" not in step, name


def test_concurrency_cancels_only_pull_request_runs():
    group = CI["concurrency"]["group"]
    assert "github.event_name == 'pull_request'" in group
    assert "github.run_id" in group
    assert CI["concurrency"]["cancel-in-progress"] is True
    for name in (
        "code_quality.yml",
        "docs_quality.yml",
        "test_platforms.yml",
        "test_s3.yml",
    ):
        assert "concurrency" not in _load(name), name
