"""Round-trip budget tests for the ephemeral stack's output reads.

Each `tofu output` call reads the remote S3 state, so the up/env export blocks
must read the whole output document once (`tofu output -json`) and pull fields
out of it with jq. These tests drive scripts/ephemeral-env.sh with a mocked
OpenTofu executable that counts its own invocations, and pin the error
behavior of the single capture: a failed read or a missing required output
fails the script before any export line reaches stdout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

RUN_ID = "pr-999"

# The full output document a deployed ephemeral stack reports today.
FULL_OUTPUTS = {
    "appsync_api_url": {"value": "https://appsync.example.amazonaws.com/graphql"},
    "appsync_api_key": {"value": "public-read-key"},
    "cognito_user_pool_id": {"value": "us-east-1_pool-1"},
    "cognito_client_id": {"value": "client-abc"},
    "cognito_domain": {"value": "kernelworx-ue1-pr-999.auth.us-east-1.amazoncognito.com"},
}


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def code_only(path: Path) -> str:
    """Script text with whole-line comments dropped, so prose cannot satisfy a
    structural assertion about the commands the script actually runs."""
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))


def write_mock(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).strip() + "\n")
    path.chmod(0o755)
    return path


def write_tofu_mock(tmp_path: Path, calls_file: Path, outputs: dict[str, dict[str, str]] | None) -> None:
    """Mock `tofu` so every call is recorded and `output -json` answers once.

    `outputs` of None makes the read itself fail, standing in for a state or
    backend error.
    """
    payload = "MISSING" if outputs is None else json.dumps(outputs)
    write_mock(
        tmp_path,
        "tofu",
        f"""
        #!/bin/bash
        echo "tofu $*" >> "{calls_file}"
        if [ "$1" = "output" ]; then
            if [ "$2" = "-json" ]; then
                if [ "{payload}" = "MISSING" ]; then
                    echo "Failed to read state: backend initialization error" >&2
                    exit 1
                fi
                cat <<'TOFU_JSON'
        {payload}
        TOFU_JSON
                exit 0
            fi
            echo "Missing output: $3" >&2
            exit 1
        fi
        exit 0
        """,
    )


def run_env_action(repo_root: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "STATE_BUCKET": "test-bucket",
        "STATE_REGION": "us-east-1",
        "TF_VAR_encryption_passphrase": "not-used",
    }
    return subprocess.run(
        ["bash", "-c", f"scripts/ephemeral-env.sh env {RUN_ID}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def output_calls(calls_file: Path) -> list[str]:
    if not calls_file.exists():
        return []
    return [line for line in calls_file.read_text().splitlines() if " output" in line]


class TestRoundTripBudget:
    def test_env_action_reads_outputs_in_one_round_trip(self, repo_root: Path, tmp_path: Path) -> None:
        calls = tmp_path / "tofu_calls.txt"
        write_tofu_mock(tmp_path, calls, FULL_OUTPUTS)

        result = run_env_action(repo_root, tmp_path)

        assert result.returncode == 0, result.stderr
        calls_made = output_calls(calls)
        assert calls_made == ["tofu output -json"], "the env branch must read the stack outputs in a single round trip"

    def test_script_never_asks_for_a_single_output_by_name(self, repo_root: Path) -> None:
        code = code_only(repo_root / "scripts" / "ephemeral-env.sh")
        assert "tofu output -raw" not in code, (
            "each single-name `tofu output` read is a separate remote state round trip"
        )
        assert len(re.findall(r"\$\(\s*tofu output", code)) == 1, (
            "exactly one capture point must exist, shared by the up and env branches"
        )

    def test_export_block_is_shared_by_both_branches(self, repo_root: Path) -> None:
        code = code_only(repo_root / "scripts" / "ephemeral-env.sh")
        assert code.count("print_stack_exports") == 3, "one definition plus one call per branch (up, env)"
        assert code.count("load_stack_outputs") == 3, "one definition plus one call per branch (up, env)"


class TestExportContract:
    def test_exports_match_the_captured_outputs(self, repo_root: Path, tmp_path: Path) -> None:
        calls = tmp_path / "tofu_calls.txt"
        write_tofu_mock(tmp_path, calls, FULL_OUTPUTS)

        result = run_env_action(repo_root, tmp_path)

        assert result.returncode == 0, result.stderr
        exports = dict(
            line.removeprefix("export ").split("=", 1)
            for line in result.stdout.splitlines()
            if line.startswith("export ")
        )
        assert exports["TEST_APPSYNC_ENDPOINT"] == FULL_OUTPUTS["appsync_api_url"]["value"]
        assert exports["VITE_APPSYNC_ENDPOINT"] == FULL_OUTPUTS["appsync_api_url"]["value"]
        assert exports["TEST_USER_POOL_ID"] == FULL_OUTPUTS["cognito_user_pool_id"]["value"]
        assert exports["VITE_COGNITO_USER_POOL_ID"] == FULL_OUTPUTS["cognito_user_pool_id"]["value"]
        assert exports["TEST_USER_POOL_CLIENT_ID"] == FULL_OUTPUTS["cognito_client_id"]["value"]
        assert exports["VITE_COGNITO_USER_POOL_CLIENT_ID"] == FULL_OUTPUTS["cognito_client_id"]["value"]
        assert exports["VITE_COGNITO_DOMAIN"] == FULL_OUTPUTS["cognito_domain"]["value"]
        assert exports["TEST_APPSYNC_API_KEY"] == FULL_OUTPUTS["appsync_api_key"]["value"]
        assert exports["VITE_APPSYNC_API_KEY"] == FULL_OUTPUTS["appsync_api_key"]["value"]
        assert exports["SHARED_CAMPAIGNS_TABLE_NAME"] == f"kernelworx-shared-campaigns-ue1-{RUN_ID}"

    def test_absent_appsync_api_key_omits_the_key_exports(self, repo_root: Path, tmp_path: Path) -> None:
        calls = tmp_path / "tofu_calls.txt"
        outputs = {name: value for name, value in FULL_OUTPUTS.items() if name != "appsync_api_key"}
        write_tofu_mock(tmp_path, calls, outputs)

        result = run_env_action(repo_root, tmp_path)

        assert result.returncode == 0, result.stderr
        assert "TEST_APPSYNC_API_KEY" not in result.stdout
        assert "VITE_APPSYNC_API_KEY" not in result.stdout
        assert "appsync_api_key output is absent" in result.stderr
        assert output_calls(calls) == ["tofu output -json"]


class TestFailureBehavior:
    def test_failed_output_read_fails_before_any_export(self, repo_root: Path, tmp_path: Path) -> None:
        calls = tmp_path / "tofu_calls.txt"
        write_tofu_mock(tmp_path, calls, None)

        result = run_env_action(repo_root, tmp_path)

        assert result.returncode != 0
        assert "tofu output -json failed" in result.stderr
        assert result.stdout == "", "a failed read must not emit a partial export block"

    @pytest.mark.parametrize(
        "missing", ["cognito_user_pool_id", "cognito_client_id", "appsync_api_url", "cognito_domain"]
    )
    def test_missing_required_output_fails_loudly(self, repo_root: Path, tmp_path: Path, missing: str) -> None:
        calls = tmp_path / "tofu_calls.txt"
        outputs = {name: value for name, value in FULL_OUTPUTS.items() if name != missing}
        write_tofu_mock(tmp_path, calls, outputs)

        result = run_env_action(repo_root, tmp_path)

        assert result.returncode != 0
        assert f"required tofu output '{missing}' is missing" in result.stderr
        assert result.stdout == "", "an empty export line would hand the caller a broken environment"


class TestScriptHygiene:
    def test_script_is_shellcheck_clean(self, repo_root: Path) -> None:
        if not shutil.which("shellcheck"):
            pytest.skip("shellcheck is not installed")
        result = subprocess.run(
            ["shellcheck", str(repo_root / "scripts" / "ephemeral-env.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"shellcheck findings:\n{result.stdout}"

    def test_script_parses(self, repo_root: Path) -> None:
        result = subprocess.run(
            ["bash", "-n", str(repo_root / "scripts" / "ephemeral-env.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
