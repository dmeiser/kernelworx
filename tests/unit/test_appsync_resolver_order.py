"""Tests for the resolver-order guard's plan-derived exclusion set.

The guard in scripts/appsync-ensure-resolver-order.sh runs before the deploy's
main apply. It plans, reads every planned `aws_appsync_function` /
`aws_appsync_datasource` deletion address out of the plan JSON, and applies
everything else with `tofu apply -exclude=<addr>` so the reference-releasing
updates land while the destroys remain for the main apply. AWS refuses
`DeleteFunction`/`DeleteDataSource` while something still references the object,
and removing the object from the configuration removes the dependency edge that
ordered its destroy after the referencing updates — the #750 prod outage (13
consecutive failed deploys) and the #298-#301 Lambda-to-JS migrations before it.

These tests drive the script with a stubbed `tofu` on PATH and fixture plan JSON,
asserting the derived `-exclude` set for each plan shape. The `-exclude`
semantics themselves were verified against a real OpenTofu 1.13.1 engine (see
the PR description); the mocks here pin only the script's derivation.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

# Last night's prod plan shape (#750): two NONE data sources deleted while three
# functions are re-pointed to the shared NoneDataSource in the same change.
PLAN_FUNCTION_REPOINT_PLUS_DATASOURCE_DELETE = {
    "resource_changes": [
        {
            "address": "module.appsync.aws_appsync_datasource.payment_methods_none",
            "type": "aws_appsync_datasource",
            "change": {"actions": ["delete"]},
        },
        {
            "address": "module.appsync.aws_appsync_datasource.filter_payment_methods_none",
            "type": "aws_appsync_datasource",
            "change": {"actions": ["delete"]},
        },
        {
            "address": "module.appsync.aws_appsync_function.inject_global_payment_methods",
            "type": "aws_appsync_function",
            "change": {"actions": ["update"]},
        },
        {
            "address": "module.appsync.aws_appsync_function.set_owner_account_id_in_stash",
            "type": "aws_appsync_function",
            "change": {"actions": ["update"]},
        },
        {
            "address": "module.appsync.aws_appsync_function.filter_payment_methods_by_access",
            "type": "aws_appsync_function",
            "change": {"actions": ["update"]},
        },
        {
            "address": "module.lambda.aws_lambda_function.api",
            "type": "aws_lambda_function",
            "change": {"actions": ["update"]},
        },
    ]
}

# A plan with no AppSync changes at all: the guard must stay a silent no-op.
PLAN_WITHOUT_APPSYNC_CHANGES = {
    "resource_changes": [
        {
            "address": "module.lambda.aws_lambda_function.api",
            "type": "aws_lambda_function",
            "change": {"actions": ["update"]},
        },
        {
            "address": "module.cognito.aws_cognito_user_pool.main",
            "type": "aws_cognito_user_pool",
            "change": {"actions": ["no-op"]},
        },
    ]
}

# A datasource nothing references any more: the guard still defers the delete to
# the main apply (its exclude-apply is a no-op there) rather than failing.
PLAN_DATASOURCE_DELETE_WITHOUT_REFERENCES = {
    "resource_changes": [
        {
            "address": "module.appsync.aws_appsync_datasource.retired",
            "type": "aws_appsync_datasource",
            "change": {"actions": ["delete"]},
        },
        {
            "address": "module.appsync.aws_appsync_function.still_used",
            "type": "aws_appsync_function",
            "change": {"actions": ["no-op"]},
        },
    ]
}

# A replaced function carries actions ["delete","create"]; the whole replacement
# is deferred to the main apply, where OpenTofu re-orders create before destroy.
PLAN_FUNCTION_REPLACEMENT = {
    "resource_changes": [
        {
            "address": "module.appsync.aws_appsync_function.tainted",
            "type": "aws_appsync_function",
            "change": {"actions": ["delete", "create"]},
        },
        {
            "address": "module.appsync.aws_appsync_resolver.create_order",
            "type": "aws_appsync_resolver",
            "change": {"actions": ["update"]},
        },
    ]
}

TOFU_MOCK = textwrap.dedent(
    """\
    #!/bin/bash
    case "$1" in
      plan)
        for arg in "$@"; do
          case "$arg" in
            -out=*) touch "${arg#-out=}" ;;
          esac
        done
        ;;
      show)
        cat "$TOFU_MOCK_PLAN_JSON"
        ;;
      apply)
        {
          echo "APPLY"
          for arg in "$@"; do
            printf 'ARG %s\\n' "$arg"
          done
        } >> "$TOFU_MOCK_LOG"
        n=$(( $(cat "$TOFU_MOCK_DIR/apply_count" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$TOFU_MOCK_DIR/apply_count"
        err_file="$TOFU_MOCK_DIR/apply_fail_$n.stderr"
        if [ -f "$err_file" ]; then
          cat "$err_file" >&2
          exit 1
        fi
        ;;
    esac
    """
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def mock_tofu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a stubbed `tofu` on PATH; return the mock's state dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tofu").write_text(TOFU_MOCK)
    (bin_dir / "tofu").chmod(0o755)
    state_dir = tmp_path / "tofu-mock"
    state_dir.mkdir()
    (state_dir / "apply_count").write_text("0\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TOFU_MOCK_DIR", str(state_dir))
    monkeypatch.setenv("TOFU_MOCK_LOG", str(state_dir / "calls.log"))
    monkeypatch.setenv("TOFU_MOCK_PLAN_JSON", str(state_dir / "plan.json"))
    write_plan(state_dir, PLAN_WITHOUT_APPSYNC_CHANGES)
    return state_dir


def write_plan(state_dir: Path, plan: dict) -> None:
    (state_dir / "plan.json").write_text(json.dumps(plan))


def run_guard(repo_root: Path, cwd: Path, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo_root / "scripts" / "appsync-ensure-resolver-order.sh"), *extra_args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def apply_calls(state_dir: Path) -> list[list[str]]:
    """Return each recorded `tofu apply` invocation as a list of arguments."""
    log = state_dir / "calls.log"
    if not log.exists():
        return []
    calls: list[list[str]] = []
    current: list[str] = []
    for line in log.read_text().splitlines():
        if line == "APPLY":
            if current:
                calls.append(current)
            current = []
        elif line.startswith("ARG "):
            current.append(line.removeprefix("ARG "))
    if current:
        calls.append(current)
    return calls


def excludes_of(call: list[str]) -> list[str]:
    return [arg.removeprefix("-exclude=") for arg in call if arg.startswith("-exclude=")]


class TestDerivedExclusions:
    def test_function_repoint_plus_datasource_delete_defers_only_the_deletes(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        """The #750 shape: both datasource deletes excluded, function updates applied."""
        write_plan(mock_tofu, PLAN_FUNCTION_REPOINT_PLUS_DATASOURCE_DELETE)

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 1, f"expected exactly one reference-releasing apply, got: {calls}"
        assert set(excludes_of(calls[0])) == {
            "module.appsync.aws_appsync_datasource.payment_methods_none",
            "module.appsync.aws_appsync_datasource.filter_payment_methods_none",
        }
        # The re-pointed functions must land in the guard pass, never be excluded.
        for addr in excludes_of(calls[0]):
            assert "aws_appsync_function" not in addr
        assert not [arg for arg in calls[0] if arg.startswith("-target=")], (
            "the guard must not target: a hand-maintained target list is the failure mode "
            "this change removes"
        )

    def test_every_planned_deletion_address_is_named_in_the_log(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        write_plan(mock_tofu, PLAN_FUNCTION_REPOINT_PLUS_DATASOURCE_DELETE)

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        for addr in (
            "module.appsync.aws_appsync_datasource.payment_methods_none",
            "module.appsync.aws_appsync_datasource.filter_payment_methods_none",
        ):
            assert addr in result.stderr, f"deferred deletion {addr} not named in the log"
        assert "deferring to the main apply" in result.stderr
        assert "remain for the main apply" in result.stderr

    def test_extra_tofu_args_reach_the_apply(self, repo_root: Path, mock_tofu: Path, tmp_path: Path) -> None:
        write_plan(mock_tofu, PLAN_FUNCTION_REPOINT_PLUS_DATASOURCE_DELETE)

        result = run_guard(repo_root, tmp_path, ["--", '-var="environment=pr-123"'])

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 1
        assert '-var="environment=pr-123"' in calls[0]

    def test_datasource_delete_without_references_still_defers_the_delete(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        """Nothing references the datasource: the guard is harmless, the main apply deletes."""
        write_plan(mock_tofu, PLAN_DATASOURCE_DELETE_WITHOUT_REFERENCES)

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 1, f"expected one reference-releasing apply, got: {calls}"
        assert excludes_of(calls[0]) == ["module.appsync.aws_appsync_datasource.retired"]

    def test_replaced_function_is_deferred_whole(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        """actions ["delete","create"] is excluded so the main apply orders the replacement."""
        write_plan(mock_tofu, PLAN_FUNCTION_REPLACEMENT)

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 1
        assert excludes_of(calls[0]) == ["module.appsync.aws_appsync_function.tainted"]


class TestNoopFastPath:
    def test_plan_without_appsync_deletions_skips_the_guard(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        write_plan(mock_tofu, PLAN_WITHOUT_APPSYNC_CHANGES)

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        assert "No AppSync function/datasource deletions planned; resolver ordering guard not needed." in (
            result.stderr
        )
        assert apply_calls(mock_tofu) == []

    def test_appsync_updates_without_deletions_skip_the_guard(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        write_plan(
            mock_tofu,
            {
                "resource_changes": [
                    {
                        "address": "module.appsync.aws_appsync_function.inject_global_payment_methods",
                        "type": "aws_appsync_function",
                        "change": {"actions": ["update"]},
                    }
                ]
            },
        )

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode == 0, result.stderr
        assert "resolver ordering guard not needed" in result.stderr
        assert apply_calls(mock_tofu) == []


class TestGuardFailureAborts:
    def test_apply_failure_exits_nonzero_without_retrying(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        """A guard failure must stop the deploy before the main apply touches anything."""
        write_plan(mock_tofu, PLAN_FUNCTION_REPOINT_PLUS_DATASOURCE_DELETE)
        (mock_tofu / "apply_fail_1.stderr").write_text(
            "Error: updating AppSync Function: BadRequestException: Data source is still in use by functions\n"
        )

        result = run_guard(repo_root, tmp_path, [])

        assert result.returncode != 0
        assert "Data source is still in use by functions" in result.stderr
        assert "aborting before the main apply" in result.stderr
        assert len(apply_calls(mock_tofu)) == 1, "the guard must not paper over a real apply failure"

    def test_hand_maintained_target_flag_is_rejected(self, repo_root: Path, mock_tofu: Path, tmp_path: Path) -> None:
        """A stale `-t` call site fails loudly instead of silently restoring the old contract."""
        result = run_guard(
            repo_root,
            tmp_path,
            ["-t", "module.appsync.aws_appsync_resolver.create_order"],
        )

        assert result.returncode != 0
        assert "-t is no longer supported" in result.stderr
        assert apply_calls(mock_tofu) == []
