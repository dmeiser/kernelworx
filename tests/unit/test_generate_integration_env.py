"""Tests for scripts/generate_integration_env.py (tofu-outputs -> env file generator)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

SCRIPT_REL = Path("scripts") / "generate_integration_env.py"

# A plausible `tofu output -json` document for the dev stack (same shape as
# `tofu output -json`; values never touch real infrastructure).
DEFAULT_OUTPUTS: dict[str, dict[str, str]] = {
    "appsync_api_url": {
        "value": "https://test-api.appsync-api.us-east-1.amazonaws.com/graphql",
        "type": "string",
    },
    "cognito_user_pool_id": {"value": "us-east-1_TestPool", "type": "string"},
    "cognito_client_id": {"value": "0123456789abcdef0123456789ab", "type": "string"},
    "cognito_domain": {"value": "login.test.kernelworx.app", "type": "string"},
    "site_url": {"value": "https://test.kernelworx.app", "type": "string"},
}


def outputs_json(*, with_site_url: bool = True, drop: tuple[str, ...] = ()) -> str:
    outputs = {name: entry for name, entry in DEFAULT_OUTPUTS.items() if name not in drop}
    if not with_site_url:
        outputs.pop("site_url", None)
    return json.dumps(outputs)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def script_path(repo_root: Path) -> Path:
    return repo_root / SCRIPT_REL


def run_script(
    script_path: Path,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TF_VAR_encryption_passphrase": "test-passphrase", **(extra_env or {})}
    return subprocess.run(
        ["python3", str(script_path), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match:
            values.setdefault(match.group(1), line.split("=", 1)[1])
    return values


class TestGeneration:
    def test_creates_file_from_committed_template_when_file_missing(
        self, script_path: Path, repo_root: Path, tmp_path: Path
    ) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / "fresh.env"
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        values = parse_env_file(target)
        assert values["TEST_APPSYNC_ENDPOINT"] == DEFAULT_OUTPUTS["appsync_api_url"]["value"]
        assert values["TEST_USER_POOL_ID"] == "us-east-1_TestPool"
        assert values["TEST_USER_POOL_CLIENT_ID"] == "0123456789abcdef0123456789ab"
        assert values["TEST_REGION"] == "us-east-1"
        assert values["E2E_BASE_URL"] == "https://test.kernelworx.app"
        # Unmanaged template content (secrets placeholder, user credentials) survives.
        content = target.read_text()
        assert "TF_VAR_encryption_passphrase=your-encryption-passphrase-here" in content
        assert "TEST_OWNER_EMAIL=owner@example.com" in content
        assert (repo_root / ".env.example").exists()

    def test_updates_existing_file_in_place_preserving_unmanaged_lines(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        target.write_text(
            "# keep me\n"
            "TEST_USER_POOL_ID=us-east-1_OldPool\n"
            "TEST_APPSYNC_ENDPOINT=https://old.appsync-api.us-east-1.amazonaws.com/graphql\n"
            "CUSTOM_VAR=keep\n"
        )
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        lines = target.read_text().splitlines()
        assert lines[0] == "# keep me"
        values = parse_env_file(target)
        assert values["TEST_USER_POOL_ID"] == "us-east-1_TestPool"
        assert values["TEST_APPSYNC_ENDPOINT"] == DEFAULT_OUTPUTS["appsync_api_url"]["value"]
        assert values["CUSTOM_VAR"] == "keep"
        # No duplicated managed keys: each managed key appears exactly once.
        assert sum(1 for line in lines if line.startswith("TEST_USER_POOL_ID=")) == 1
        assert sum(1 for line in lines if line.startswith("TEST_APPSYNC_ENDPOINT=")) == 1

    def test_appends_missing_keys_with_marker_comment(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        target.write_text("FOO=bar\n")
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        content = target.read_text()
        assert "managed by scripts/generate_integration_env.py" in content
        values = parse_env_file(target)
        assert values["TEST_USER_POOL_ID"] == "us-east-1_TestPool"
        assert values["FOO"] == "bar"

    def test_omits_e2e_base_url_when_site_url_output_absent(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json(with_site_url=False))
        target = tmp_path / ".env"
        target.write_text("E2E_BASE_URL=http://localhost:4173\n")
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert parse_env_file(target)["E2E_BASE_URL"] == "http://localhost:4173"

    def test_missing_required_output_fails_loudly(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json(drop=("cognito_client_id",)))
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(tmp_path / ".env"), cwd=tmp_path)
        assert result.returncode == 1
        assert "cognito_client_id" in result.stderr

    def test_invalid_outputs_json_fails_loudly(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text("not json")
        result = run_script(script_path, "--outputs-json", str(fixture), "--out", str(tmp_path / ".env"), cwd=tmp_path)
        assert result.returncode == 1
        assert "not valid JSON" in result.stderr

    def test_generates_frontend_file(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / "frontend.env"
        result = run_script(
            script_path,
            "--outputs-json",
            str(fixture),
            "--out",
            str(tmp_path / ".env"),
            "--frontend-out",
            str(target),
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        values = parse_env_file(target)
        assert values["VITE_APPSYNC_ENDPOINT"] == DEFAULT_OUTPUTS["appsync_api_url"]["value"]
        assert values["VITE_APPSYNC_REGION"] == "us-east-1"
        assert values["VITE_COGNITO_USER_POOL_ID"] == "us-east-1_TestPool"
        assert values["VITE_COGNITO_USER_POOL_CLIENT_ID"] == "0123456789abcdef0123456789ab"
        assert values["VITE_COGNITO_DOMAIN"] == "login.test.kernelworx.app"
        assert values["VITE_OAUTH_REDIRECT_SIGNIN"] == "http://localhost:5173/"
        assert values["VITE_OAUTH_REDIRECT_SIGNOUT"] == "http://localhost:5173/"

    def test_frontend_requires_cognito_domain_output(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json(drop=("cognito_domain",)))
        result = run_script(
            script_path,
            "--outputs-json",
            str(fixture),
            "--out",
            str(tmp_path / ".env"),
            "--frontend-out",
            str(tmp_path / "frontend.env"),
            cwd=tmp_path,
        )
        assert result.returncode == 1
        assert "cognito_domain" in result.stderr


class TestCheckMode:
    def test_check_passes_on_generated_file(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        generated = run_script(script_path, "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert generated.returncode == 0, generated.stderr
        result = run_script(script_path, "--check", "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stderr

    def test_check_detects_stale_value(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        target.write_text("TEST_USER_POOL_ID=us-east-1_StalePool\n")
        result = run_script(script_path, "--check", "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 1
        assert "stale" in result.stderr
        assert "TEST_USER_POOL_ID" in result.stderr

    def test_check_detects_missing_key(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        target.write_text("TEST_USER_POOL_ID=us-east-1_TestPool\n")
        result = run_script(script_path, "--check", "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert result.returncode == 1
        assert "TEST_APPSYNC_ENDPOINT" in result.stderr
        assert "missing" in result.stderr

    def test_check_missing_file_fails(self, script_path: Path, tmp_path: Path) -> None:
        result = run_script(script_path, "--check", "--out", str(tmp_path / "nope.env"), cwd=tmp_path)
        assert result.returncode == 1
        assert "does not exist" in result.stderr

    def test_check_never_writes(self, script_path: Path, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        target = tmp_path / ".env"
        target.write_text("TEST_USER_POOL_ID=us-east-1_StalePool\n")
        before = target.read_text()
        run_script(script_path, "--check", "--outputs-json", str(fixture), "--out", str(target), cwd=tmp_path)
        assert target.read_text() == before

    def test_structural_check_passes_on_committed_root_sample(self, script_path: Path, repo_root: Path) -> None:
        """The committed .env.example must cover every structurally-checked key."""
        result = run_script(script_path, "--check", "--out", ".env.example", cwd=repo_root)
        assert result.returncode == 0, result.stderr

    def test_structural_check_passes_on_committed_frontend_sample(self, script_path: Path, repo_root: Path) -> None:
        """The committed frontend/.env.example must cover every frontend key."""
        result = run_script(script_path, "--check", "--frontend-out", "frontend/.env.example", cwd=repo_root)
        assert result.returncode == 0, result.stderr


class TestLiveTofuPath:
    """Drive the script's `tofu output -json` path with a mock tofu binary."""

    def _install_mock_tofu(self, tmp_path: Path, env: dict[str, str]) -> Path:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log_file = tmp_path / "tofu.log"
        marker = tmp_path / "inited"
        fixture = tmp_path / "outputs.json"
        fixture.write_text(outputs_json())
        tofu = bin_dir / "tofu"
        tofu.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                echo "tofu $*" >> "{log_file}"
                sub="$3"
                if [ "$sub" = "init" ]; then
                  touch "{marker}"
                  exit 0
                fi
                if [ "$sub" = "output" ]; then
                  if [ "{env["FAIL_OUTPUT_UNTIL_INIT"]}" = "1" ] && [ ! -f "{marker}" ]; then
                    exit 1
                  fi
                  cat "{fixture}"
                  exit 0
                fi
                exit 1
                """
            )
        )
        tofu.chmod(0o755)
        env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
        return log_file

    def test_dev_live_output_succeeds_without_init(self, script_path: Path, repo_root: Path, tmp_path: Path) -> None:
        env: dict[str, str] = {"FAIL_OUTPUT_UNTIL_INIT": "0"}
        log_file = self._install_mock_tofu(tmp_path, env)
        target = tmp_path / ".env"
        result = run_script(script_path, "--env", "dev", "--out", str(target), cwd=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr
        calls = log_file.read_text().strip().splitlines()
        assert len(calls) == 1
        assert calls[0] == f"tofu -chdir {repo_root / 'tofu/application/environments/dev'} output -input=false -json"
        assert parse_env_file(target)["TEST_USER_POOL_ID"] == "us-east-1_TestPool"

    def test_dev_live_output_inits_and_retries(self, script_path: Path, repo_root: Path, tmp_path: Path) -> None:
        env: dict[str, str] = {"FAIL_OUTPUT_UNTIL_INIT": "1"}
        log_file = self._install_mock_tofu(tmp_path, env)
        target = tmp_path / ".env"
        result = run_script(script_path, "--env", "dev", "--out", str(target), cwd=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr
        calls = log_file.read_text().strip().splitlines()
        dev = f"tofu -chdir {repo_root / 'tofu/application/environments/dev'}"
        assert calls == [
            f"{dev} output -input=false -json",
            f"{dev} init -input=false",
            f"{dev} output -input=false -json",
        ]

    def test_ephemeral_live_inits_with_run_id_backend_key(
        self, script_path: Path, repo_root: Path, tmp_path: Path
    ) -> None:
        env: dict[str, str] = {"FAIL_OUTPUT_UNTIL_INIT": "0"}
        log_file = self._install_mock_tofu(tmp_path, env)
        target = tmp_path / ".env"
        result = run_script(script_path, "--env", "ephemeral/pr-999", "--out", str(target), cwd=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr
        calls = log_file.read_text().strip().splitlines()
        ephemeral_dir = f"-chdir {repo_root / 'tofu/application/environments/ephemeral'}"
        assert calls[0] == (
            "tofu "
            f"{ephemeral_dir} init -input=false "
            "-backend-config=key=application/ephemeral/pr-999/terraform.tfstate "
            "-backend-config=bucket=kernelworx-tofu-state-us-east-1-dev -backend-config=region=us-east-1"
        )
        assert calls[1] == f"tofu {ephemeral_dir} output -input=false -json"
        assert parse_env_file(target)["TEST_USER_POOL_ID"] == "us-east-1_TestPool"

    def test_ephemeral_invalid_run_id_fails_without_tofu(self, script_path: Path, tmp_path: Path) -> None:
        env: dict[str, str] = {"FAIL_OUTPUT_UNTIL_INIT": "0"}
        log_file = self._install_mock_tofu(tmp_path, env)
        result = run_script(
            script_path, "--env", "ephemeral/../etc", "--out", str(tmp_path / ".env"), cwd=tmp_path, extra_env=env
        )
        assert result.returncode == 1
        assert "invalid run id" in result.stderr
        assert not log_file.exists()

    def test_live_path_requires_passphrase(self, script_path: Path, tmp_path: Path) -> None:
        env: dict[str, str] = {"FAIL_OUTPUT_UNTIL_INIT": "0", "TF_VAR_encryption_passphrase": ""}
        self._install_mock_tofu(tmp_path, env)
        result = run_script(script_path, "--env", "dev", "--out", str(tmp_path / ".env"), cwd=tmp_path, extra_env=env)
        assert result.returncode == 1
        assert "TF_VAR_encryption_passphrase" in result.stderr


class TestWiring:
    """The generator must cover every infra key the integration test setup requires."""

    @staticmethod
    def _load_module(script_path: Path) -> Any:
        spec = importlib.util.spec_from_file_location("generate_integration_env", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_managed_keys_cover_integration_setup_requirements(self, script_path: Path, repo_root: Path) -> None:
        module = self._load_module(script_path)
        setup_ts = (repo_root / "tests" / "integration" / "setup.ts").read_text()
        match = re.search(r"requiredEnvVars\s*=\s*\[([^\]]*)\]", setup_ts, re.DOTALL)
        assert match, "requiredEnvVars list not found in tests/integration/setup.ts"
        required = re.findall(r"'([A-Z_]+)'", match.group(1))
        # User credentials are created by scripts/create-test-users.sh, not by tofu.
        user_provided = {
            "TEST_OWNER_EMAIL",
            "TEST_OWNER_PASSWORD",
            "TEST_OWNER_TOTP_SECRET",
            "TEST_CONTRIBUTOR_EMAIL",
            "TEST_CONTRIBUTOR_PASSWORD",
            "TEST_READONLY_EMAIL",
            "TEST_READONLY_PASSWORD",
        }
        infra_required = {key for key in required if key not in user_provided}
        managed = set(
            module.expected_integration_values(
                {
                    "appsync_api_url": "x",
                    "cognito_user_pool_id": "y",
                    "cognito_client_id": "z",
                    "site_url": "w",
                },
                "us-east-1",
            )
        )
        assert infra_required <= managed, (
            f"integration setup requires {sorted(infra_required)} but the generator only manages {sorted(managed)}"
        )

    def test_replaced_script_is_gone(self, repo_root: Path) -> None:
        """scripts/update-integration-env.sh was superseded by the generator."""
        assert not (repo_root / "scripts" / "update-integration-env.sh").exists()
