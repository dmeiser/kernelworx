"""Guards for the dev deploy path: a deploy you can start by hand, and a drift signal.

A merge into `dev` whose push event GitHub never emits produces no `Deploy Dev`
run: the branch claims a fix `https://dev.kernelworx.app` does not serve, the
project's "merged to dev with a green Deploy Dev run" step cannot be satisfied,
and no job says so. The recovery must not require writing to `dev`, and the next
wave cannot branch on a tree that was never deployed.

These tests drive the real script through a fake GitHub transport, so the decisions
under test are the ones the workflows act on. The workflow-shape tests pin the
contract the scripts depend on - and the rule that the drift check may never deploy.

Incident shape, reproduced by `test_dev_head_with_no_deploy_run_is_drift`:
`dev` at 526690b0 with its newest workflow run being the pull request's CI, and
the last successful `Deploy Dev` on the parent b85f2e7d.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev_deploy_gate.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPLOY_DEV = WORKFLOWS / "deploy-dev.yml"
DEPLOY_SHARED = WORKFLOWS / "deploy-shared.yml"
DRIFT_WORKFLOW = WORKFLOWS / "dev-drift-check.yml"

NOW = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)
DEV_SHA = "526690b03bb88e09c88a5d786de30bd89716bf2c"
PARENT_SHA = "b85f2e7d3d1e63a1dc6d09cd1e7fdbbf79459ea6"
OLDER_SHA = "2f457c5e433f5fc27ede300dbf2c3521c290839b"


def _gate() -> ModuleType:
    """Load the script under test - it is a script, not an importable package module."""
    spec = importlib.util.spec_from_file_location("dev_deploy_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(
    sha: str,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 1,
    created_at: str = "2026-11-16T07:59:45Z",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "created_at": created_at,
        "event": "push",
        "html_url": f"https://github.com/dmeiser/kernelworx/actions/runs/{run_id}",
    }


class FakeTransport:
    """Answers the GitHub endpoints the guard calls, from a routed table."""

    def __init__(self, routes: dict[str, tuple[int, Any]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, str]:
        self.calls.append(url)
        assert headers.get("Authorization", "").startswith("Bearer "), "the guard must authenticate as the workflow"
        for needle, (status, payload) in self.routes.items():
            if needle in url:
                return status, json.dumps(payload)
        raise AssertionError(f"unexpected URL called: {url}")


def _api(routes: dict[str, tuple[int, Any]]) -> Any:
    gate = _gate()
    transport = FakeTransport(routes)
    api = gate.GitHubApi("dmeiser/kernelworx", "token", "https://api.github.com", transport)
    return api, gate, transport


def _drift_routes(runs: list[dict[str, Any]], total: int | None = None) -> dict[str, tuple[int, Any]]:
    return {
        "/commits/dev": (
            200,
            {"sha": DEV_SHA, "commit": {"committer": {"date": "2026-11-16T12:07:57Z"}}},
        ),
        "/actions/workflows/deploy-dev.yml/runs": (
            200,
            {"workflow_runs": runs, "total_count": total if total is not None else len(runs)},
        ),
    }


# --- drift detection -------------------------------------------------------


def test_dev_head_with_no_deploy_run_is_drift() -> None:
    """The incident: the ref moved, no workflow run exists for the new head."""
    api, gate, _ = _api(_drift_routes([_run(PARENT_SHA), _run(OLDER_SHA, run_id=2)]))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is False
    assert report.state == "no_run_for_head"
    assert report.dev_sha == DEV_SHA
    assert report.deploy_sha == PARENT_SHA
    assert DEV_SHA in report.headline and PARENT_SHA[:12] in report.headline
    assert "DEPLOY DRIFT" in report.headline


def test_deployed_head_is_clean() -> None:
    """After the recovery deploy lands, the same check must pass."""
    api, gate, _ = _api(_drift_routes([_run(DEV_SHA), _run(PARENT_SHA, run_id=2)]))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is True
    assert report.state == "aligned"
    assert report.deploy_sha == DEV_SHA


def test_deploy_in_flight_is_not_drift() -> None:
    """A queued or running deploy is a pause, not an alarm.

    `Post-deploy smoke tests (dev)` runs 45-48 minutes, so a schedule finer than
    that would otherwise go red on every merge.
    """
    api, gate, _ = _api(_drift_routes([_run(DEV_SHA, status="in_progress", conclusion=None), _run(PARENT_SHA, run_id=2)]))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is True
    assert report.state == "deploy_in_progress"
    assert len(report.open_runs) == 1


def test_queued_deploy_is_not_drift() -> None:
    api, gate, _ = _api(_drift_routes([_run(DEV_SHA, status="queued", conclusion=None), _run(PARENT_SHA, run_id=2)]))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is True
    assert report.state == "deploy_in_progress"


def test_failed_deploy_for_the_head_is_drift() -> None:
    """A failed deploy leaves the head not deployed, just as a missing run does."""
    api, gate, _ = _api(
        _drift_routes([_run(DEV_SHA, status="completed", conclusion="failure"), _run(PARENT_SHA, run_id=2)])
    )
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is False
    assert report.state == "failed_deploy"
    assert report.deploy_sha == PARENT_SHA
    assert len(report.failed_runs) == 1


def test_no_successful_run_in_the_window_is_drift() -> None:
    """Nothing successful in the inspected window: still drift, and it says so."""
    api, gate, _ = _api(_drift_routes([_run(OLDER_SHA, status="completed", conclusion="failure")]))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.ok is False
    assert report.state == "no_successful_run"
    assert report.deploy_sha is None
    assert report.failed_runs == (), "a failed run for another commit is not a failed run for dev's head"


def test_only_the_fetched_window_is_claimed() -> None:
    """The report says how many runs it saw, so an old deploy is not read as recent."""
    runs = [_run(OLDER_SHA, run_id=index) for index in range(1, 6)]
    api, gate, _ = _api(_drift_routes(runs, total=242))
    report = gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)

    assert report.window == 5
    assert report.total_count == 242


def test_api_failure_is_inconclusive_not_drift() -> None:
    """A transport or API fault must not be reported as a drift verdict."""
    api, gate, _ = _api({"/commits/dev": (500, {"message": "server error"})})
    try:
        gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)
    except gate.GateError as exc:
        assert "500" in str(exc)
        return
    raise AssertionError("an API failure must raise, not classify")


def test_malformed_head_sha_is_rejected() -> None:
    api, gate, _ = _api({"/commits/dev": (200, {"sha": "not-a-sha"})})
    try:
        gate.check_drift(api, "dev", "deploy-dev.yml", 50, NOW)
    except gate.GateError as exc:
        assert "full commit SHA" in str(exc)
        return
    raise AssertionError("a head SHA that is not a full SHA must fail loudly")


# --- dispatch ref resolution -----------------------------------------------


def _compare_routes(status: str, sha: str = OLDER_SHA) -> dict[str, tuple[int, Any]]:
    return {
        "/commits/": (200, {"sha": sha}),
        "/compare/": (200, {"status": status}),
    }


def test_dev_head_is_deployable() -> None:
    api, gate, _ = _api(_compare_routes("identical", DEV_SHA))
    assert gate.resolve_ref(api, "dev", "dev") == DEV_SHA


def test_commit_already_merged_into_dev_is_deployable() -> None:
    """Re-deploying an older dev commit is a legitimate recovery."""
    api, gate, _ = _api(_compare_routes("ahead"))
    assert gate.resolve_ref(api, OLDER_SHA, "dev") == OLDER_SHA


def test_branch_ahead_of_dev_is_refused() -> None:
    """An unmerged branch must not be pushed onto the dev environment."""
    api, gate, _ = _api(_compare_routes("behind"))
    try:
        gate.resolve_ref(api, "agent/dev-local-1/822533361188", "dev")
    except gate.GateError as exc:
        assert "behind" in str(exc) and "may only target" in str(exc)
        return
    raise AssertionError("a ref ahead of dev must be refused")


def test_diverged_ref_is_refused() -> None:
    api, gate, _ = _api(_compare_routes("diverged"))
    try:
        gate.resolve_ref(api, "some-branch", "dev")
    except gate.GateError as exc:
        assert "diverged" in str(exc)
        return
    raise AssertionError("a diverged ref must be refused")


def test_unsafe_ref_never_reaches_the_api() -> None:
    api, gate, transport = _api(_compare_routes("identical"))
    for ref in ("../main", "..", "-x", "a b", ""):
        try:
            gate.resolve_ref(api, ref, "dev")
        except gate.GateError:
            continue
        raise AssertionError(f"ref {ref!r} must be refused before any API call")
    assert transport.calls == []


def test_missing_ref_is_reported() -> None:
    api, gate, _ = _api({"/commits/": (404, {"message": "No commit found for SHA: nope"})})
    try:
        gate.resolve_ref(api, "nope", "dev")
    except gate.GateError as exc:
        assert "No commit found" in str(exc)
        return
    raise AssertionError("a ref that does not exist must fail loudly")


# --- command behaviour -----------------------------------------------------


def test_check_drift_command_exits_nonzero_on_drift(monkeypatch: Any, capsys: Any, tmp_path: Path) -> None:
    """The drift job goes red, names both SHAs, and offers the recovery."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_REPOSITORY", "dmeiser/kernelworx")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    gate = _gate()
    gate._http_get = FakeTransport(_drift_routes([_run(PARENT_SHA)])).__call__

    assert gate.main(["check-drift"]) == 1
    printed = capsys.readouterr().out
    assert f"::error::DEPLOY DRIFT: dev head {DEV_SHA[:12]}" in printed
    assert PARENT_SHA[:12] in printed
    assert "gh workflow run deploy-dev.yml --ref dev -f ref=dev" in printed
    assert "aligned" not in summary.read_text()


def test_check_drift_command_exits_zero_when_aligned(monkeypatch: Any, capsys: Any, tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_REPOSITORY", "dmeiser/kernelworx")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    gate = _gate()
    gate._http_get = FakeTransport(_drift_routes([_run(DEV_SHA)]))

    assert gate.main(["check-drift"]) == 0
    printed = capsys.readouterr().out
    assert f"dev head: {DEV_SHA}" in printed
    assert "::error::" not in printed
    assert "aligned" in summary.read_text()


def test_resolve_ref_command_publishes_the_sha_as_a_step_output(monkeypatch: Any, capsys: Any, tmp_path: Path) -> None:
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_REPOSITORY", "dmeiser/kernelworx")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    gate = _gate()
    transport = FakeTransport(_compare_routes("ahead", OLDER_SHA))
    gate._http_get = transport

    assert gate.main(["resolve-ref", "--ref", "dev"]) == 0
    assert output.read_text().strip() == f"sha={OLDER_SHA}"
    assert OLDER_SHA in capsys.readouterr().out


def test_a_guard_error_is_a_distinct_exit_code(monkeypatch: Any, capsys: Any) -> None:
    """Exit 2 means the check could not be answered, not that dev drifted."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "dmeiser/kernelworx")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    gate = _gate()
    gate._http_get = FakeTransport({"/commits/dev": (403, {"message": "Resource not accessible by integration"})})

    assert gate.main(["check-drift"]) == 2
    assert "Resource not accessible" in capsys.readouterr().out


# --- workflow contracts ----------------------------------------------------


def _workflow(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text())
    assert isinstance(document, dict)
    # YAML 1.1 reads the `on` key as the boolean True.
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), f"{path.name} has no readable trigger block"
    return {"document": document, "triggers": triggers}


def test_deploy_dev_still_deploys_on_push_and_can_be_dispatched() -> None:
    workflow = _workflow(DEPLOY_DEV)
    triggers = workflow["triggers"]
    assert triggers.get("push", {}).get("branches") == ["dev"], "the push trigger must stay exactly as it was"

    dispatch = triggers.get("workflow_dispatch")
    assert isinstance(dispatch, dict), "deploy-dev.yml must accept a manual run, or a lost push event is unrecoverable"
    ref_input = dispatch.get("inputs", {}).get("ref")
    assert ref_input, "the dispatch must take a ref input so the deploy can name the tree it serves"
    assert ref_input.get("default") == "dev"
    assert ref_input.get("required") is False


def test_deploy_dev_passes_the_resolved_commit_to_the_deploy_job() -> None:
    document = _workflow(DEPLOY_DEV)["document"]
    jobs = document["jobs"]
    assert "resolve-deploy-ref" in jobs
    deploy = jobs["deploy"]
    assert "resolve-deploy-ref" in deploy["needs"]
    assert deploy["with"]["checkout-ref"] == "${{ needs.resolve-deploy-ref.outputs.sha }}"
    assert "resolve-vars" in deploy["needs"], "the smoke-test variable job must keep running"


def test_deploy_shared_ignores_an_empty_checkout_ref() -> None:
    """The shared deploy gains a ref input, and every existing caller keeps its default."""
    document = _workflow(DEPLOY_SHARED)["document"]
    inputs = document["on"]["workflow_call"] if "on" in document else document[True]["workflow_call"]
    assert inputs["inputs"]["checkout-ref"]["default"] == "", "prod must deploy the run head, unchanged"

    for job_name in ("deploy", "smoke-tests"):
        steps = document["jobs"][job_name]["steps"]
        checkouts = [step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")]
        assert checkouts, f"{job_name} lost its checkout step"
        for step in checkouts:
            assert step.get("with", {}).get("ref") == "${{ inputs.checkout-ref }}"


def test_drift_check_can_never_deploy_anything() -> None:
    """The drift signal reports; it must not be able to deploy."""
    workflow = _workflow(DRIFT_WORKFLOW)
    triggers, document = workflow["triggers"], workflow["document"]

    assert "schedule" in triggers and "workflow_dispatch" in triggers
    permissions = document.get("permissions", {})
    assert permissions.get("contents") == "read", "the check reads the commit, nothing else"
    assert permissions.get("actions") == "read", "the check reads workflow runs, nothing else"
    assert "id-token" not in permissions, "no OIDC token means no AWS role can be assumed"

    text = DRIFT_WORKFLOW.read_text()
    for forbidden in ("deploy-shared.yml", "configure-aws-credentials", "AWS_ROLE", "id-token: write", "tofu "):
        assert forbidden not in text, f"the drift check must not reference {forbidden!r}: it never deploys"
    for job in document["jobs"].values():
        assert "environment" not in job, "no deployment environment, so nothing can gate or run a deploy here"


def test_drift_check_names_the_script_and_the_branch() -> None:
    text = DRIFT_WORKFLOW.read_text()
    assert "dev_deploy_gate.py check-drift" in text
    assert "--branch dev" in text
    assert "deploy-dev.yml" in text


def test_deploy_dev_resolve_step_guards_the_dispatch_ref() -> None:
    text = DEPLOY_DEV.read_text()
    assert "dev_deploy_gate.py resolve-ref" in text, "a dispatch must be checked against dev's history"
    assert "${{ github.event.inputs.ref }}" in text
