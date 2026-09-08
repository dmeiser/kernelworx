"""Tests for tofu/application/scripts/deploy.sh."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def mock_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Provide isolated PATH with mock binaries and an execution log file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log_file = tmp_path / "calls.log"

    write_mock_bin(
        bin_dir,
        "npm",
        f"""\
        #!/bin/bash
        echo "npm $@" >> "{log_file}"
        if [ "${{FAIL_NPM:-0}}" = "1" ]; then
            exit 1
        fi
        exit 0
        """,
    )

    write_mock_bin(
        bin_dir,
        "tofu",
        f"""\
        #!/bin/bash
        echo "tofu $@" >> "{log_file}"
        exit 0
        """,
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TF_VAR_encryption_passphrase", "test-passphrase")
    return {"bin_dir": bin_dir, "log_file": log_file}


def write_mock_bin(bin_dir: Path, name: str, script: str) -> Path:
    path = bin_dir / name
    path.write_text(textwrap.dedent(script).strip() + "\n")
    path.chmod(0o755)
    return path


def run_deploy(
    repo_root: Path,
    action: str,
    *extra_args: str,
    env_name: str = "dev",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    deploy_script = repo_root / "tofu" / "application" / "scripts" / "deploy.sh"
    cmd = [str(deploy_script), env_name, action, *extra_args]
    return subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**os.environ, **(extra_env or {})},
        check=False,
    )


class TestDeployInit:
    def test_init_builds_resolvers_before_tofu_init(self, repo_root: Path, mock_env: dict[str, Path]) -> None:
        result = run_deploy(repo_root, "init")
        assert result.returncode == 0, f"deploy.sh init failed: {result.stderr}\n{result.stdout}"

        calls = mock_env["log_file"].read_text().strip().splitlines()
        assert calls == [
            "npm run build:resolvers",
            "tofu init -upgrade",
        ]

    def test_init_passes_extra_flags_to_tofu_init(self, repo_root: Path, mock_env: dict[str, Path]) -> None:
        result = run_deploy(repo_root, "init", "-reconfigure", "-backend-config=key=val")
        assert result.returncode == 0, f"deploy.sh init failed: {result.stderr}\n{result.stdout}"

        calls = mock_env["log_file"].read_text().strip().splitlines()
        assert calls == [
            "npm run build:resolvers",
            "tofu init -upgrade -reconfigure -backend-config=key=val",
        ]

    def test_init_aborts_if_build_resolvers_fails(self, repo_root: Path, mock_env: dict[str, Path]) -> None:
        result = run_deploy(repo_root, "init", extra_env={"FAIL_NPM": "1"})
        assert result.returncode != 0

        calls = mock_env["log_file"].read_text().strip().splitlines()
        assert calls == ["npm run build:resolvers"]
