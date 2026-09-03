"""Tests for the resolver-order guard's targeted-apply retry behavior.

The guard in scripts/appsync-ensure-resolver-order.sh runs a targeted
`tofu apply` for pipeline resolvers before the full apply destroys unreferenced
AppSync functions. OpenTofu refuses a targeted apply when the state still has
unmoved `moved`-block lineage ("Moved resource instances excluded by
targeting") and suggests additional -target options. These tests drive the
script with a stubbed `tofu` on PATH and a recorded stderr fixture from the
real dev deploy failure to verify that the apply is retried with the union of
the original and suggested targets.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

RESOLVER_TARGET = "module.appsync.aws_appsync_resolver.create_order"

# Recorded stderr from the real dev deploy failure (run 33689651385): a
# targeted apply refused because the environment's state still has unmoved
# `moved`-block lineage from mainline PR #182's lambda trigger split.
MOVED_INSTANCES_ERROR = textwrap.dedent(
    """\
    ╷
    │ Error: Moved resource instances excluded by targeting
    │
    │ Resource instances in your current state have moved to new addresses in the
    │ latest configuration. OpenTofu must include those resource instances while
    │ planning in order to ensure a correct result, but your -target=... options
    │ do not fully cover all of those resource instances.
    │
    │ To create a valid plan, either remove your -target=... options altogether
    │ or add the following additional target options:
    │   -target="module.appsync.aws_appsync_domain_name.api"
    │   -target="module.appsync.aws_appsync_domain_name_api_association.api"
    │   -target="module.cognito.aws_cognito_user_pool_domain.custom"
    │   -target="module.iam.data.aws_iam_policy_document.lambda_cloudfront"
    │   -target="module.iam.aws_iam_role_policy.lambda_cloudfront"
    │
    │ Note that adding these options may include further additional resource
    │ instances in your plan, in order to respect object dependencies.
    ╵
    """
)

SUGGESTED_TARGETS = [
    "module.appsync.aws_appsync_domain_name.api",
    "module.appsync.aws_appsync_domain_name_api_association.api",
    "module.cognito.aws_cognito_user_pool_domain.custom",
    "module.iam.data.aws_iam_policy_document.lambda_cloudfront",
    "module.iam.aws_iam_role_policy.lambda_cloudfront",
]

PLAN_WITH_FUNCTION_DELETE = (
    '{"resource_changes":[{"address":"module.appsync.aws_appsync_function.old",'
    '"type":"aws_appsync_function","change":{"actions":["delete"]}}]}'
)

PLAN_WITHOUT_DELETIONS = '{"resource_changes":[]}'

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
            printf 'ARG %s\n' "$arg"
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
    (state_dir / "plan.json").write_text(PLAN_WITH_FUNCTION_DELETE)
    return state_dir


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


def targets_of(call: list[str]) -> list[str]:
    return [arg.removeprefix("-target=") for arg in call if arg.startswith("-target=")]


class TestMovedInstancesRetry:
    def test_retry_carries_union_of_original_and_suggested_targets(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        (mock_tofu / "apply_fail_1.stderr").write_text(MOVED_INSTANCES_ERROR)

        result = run_guard(
            repo_root,
            tmp_path,
            ["-t", RESOLVER_TARGET, "--", '-var="environment=pr-123"'],
        )

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 2, f"expected initial apply plus one retry, got: {calls}"
        retried_targets = targets_of(calls[1])
        assert len(retried_targets) == len(set(retried_targets)), "duplicate targets in retry"
        assert set(retried_targets) == {RESOLVER_TARGET, *SUGGESTED_TARGETS}
        assert any(arg.startswith("-var=") for arg in calls[1]), "extra tofu args lost on retry"

    def test_each_retry_can_add_further_targets(self, repo_root: Path, mock_tofu: Path, tmp_path: Path) -> None:
        (mock_tofu / "apply_fail_1.stderr").write_text(MOVED_INSTANCES_ERROR)
        (mock_tofu / "apply_fail_2.stderr").write_text(
            textwrap.dedent(
                """\
                ╷
                │ Error: Moved resource instances excluded by targeting
                │
                │ The following -target options would address all of these moved instance
                │ addresses:
                │
                │   -target="module.lambda.aws_lambda_function.trigger_functions[\\"pre-signup\\"]"
                │
                │ Note that adding these options may include further additional resource
                │ instances.
                ╵
                """
            )
        )

        result = run_guard(repo_root, tmp_path, ["-t", RESOLVER_TARGET])

        assert result.returncode == 0, result.stderr
        calls = apply_calls(mock_tofu)
        assert len(calls) == 3
        final_targets = targets_of(calls[2])
        assert 'module.lambda.aws_lambda_function.trigger_functions["pre-signup"]' in final_targets
        assert set(SUGGESTED_TARGETS) <= set(final_targets)
        assert RESOLVER_TARGET in final_targets

    def test_unrelated_apply_failure_fails_without_retry(
        self, repo_root: Path, mock_tofu: Path, tmp_path: Path
    ) -> None:
        (mock_tofu / "apply_fail_1.stderr").write_text("Error: AccessDenied\n")

        result = run_guard(repo_root, tmp_path, ["-t", RESOLVER_TARGET])

        assert result.returncode != 0
        assert "AccessDenied" in result.stderr
        assert len(apply_calls(mock_tofu)) == 1

    def test_retry_exhaustion_fails_loudly(self, repo_root: Path, mock_tofu: Path, tmp_path: Path) -> None:
        for n in (1, 2, 3, 4):
            (mock_tofu / f"apply_fail_{n}.stderr").write_text(MOVED_INSTANCES_ERROR)

        result = run_guard(repo_root, tmp_path, ["-t", RESOLVER_TARGET])

        assert result.returncode != 0
        assert "Moved resource instances excluded by targeting" in result.stderr
        assert len(apply_calls(mock_tofu)) == 4, "initial apply plus max 3 retries"


class TestNoopFastPath:
    def test_no_function_deletions_skips_guard(self, repo_root: Path, mock_tofu: Path, tmp_path: Path) -> None:
        (mock_tofu / "plan.json").write_text(PLAN_WITHOUT_DELETIONS)

        result = run_guard(repo_root, tmp_path, ["-t", RESOLVER_TARGET])

        assert result.returncode == 0, result.stderr
        assert "resolver ordering guard not needed" in result.stderr
        assert apply_calls(mock_tofu) == []
