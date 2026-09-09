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


class TestPlanIsFresh:
    """Unit tests for deploy.sh's plan_is_fresh freshness check.

    deploy.sh's main block only runs when executed directly, so the script can be
    sourced and plan_is_fresh driven against an isolated fixture ROOT_DIR.
    """

    PLAN_MTIME = 1_000

    def _build_fixture(self, tmp_path: Path, *, dist_mtime: int, source_mtime: int) -> Path:
        fixture = tmp_path / "fixture"
        (fixture / "src").mkdir(parents=True)
        (fixture / "tofu/application/appsync/dist").mkdir(parents=True)
        (fixture / "tofu/application/appsync/js-resolvers").mkdir(parents=True)

        plan = fixture / "tfplan"
        plan.write_text("saved plan")
        dist = fixture / "tofu/application/appsync/dist/query.js"
        dist.write_text("// esbuild bundle output")
        source = fixture / "tofu/application/appsync/js-resolvers/query.js"
        source.write_text("// resolver source")

        os.utime(plan, (self.PLAN_MTIME, self.PLAN_MTIME))
        os.utime(dist, (dist_mtime, dist_mtime))
        os.utime(source, (source_mtime, source_mtime))
        return fixture

    def _run_plan_is_fresh(self, repo_root: Path, fixture: Path, plan_name: str = "tfplan") -> str:
        script = textwrap.dedent(
            f"""
            export TF_VAR_encryption_passphrase="test-passphrase"
            # Sourcing prints env-loading warnings; silence them so only the
            # FRESH/STALE verdict lands on stdout.
            source "{repo_root}/tofu/application/scripts/deploy.sh" > /dev/null
            ROOT_DIR="{fixture}"
            if plan_is_fresh "{fixture}/{plan_name}"; then
                echo FRESH
            else
                echo STALE
            fi
            """
        )
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"plan_is_fresh driver failed: {result.stderr}"
        return result.stdout.strip()

    def test_rebuilt_dist_does_not_invalidate_plan(self, repo_root: Path, tmp_path: Path) -> None:
        """A dist/ bundle rebuilt after the plan must not count as a source change."""
        fixture = self._build_fixture(tmp_path, dist_mtime=self.PLAN_MTIME + 500, source_mtime=self.PLAN_MTIME - 500)
        assert self._run_plan_is_fresh(repo_root, fixture) == "FRESH"

    def test_resolver_source_change_invalidates_plan(self, repo_root: Path, tmp_path: Path) -> None:
        """A real resolver source edit newer than the plan must force a re-plan."""
        fixture = self._build_fixture(tmp_path, dist_mtime=self.PLAN_MTIME - 500, source_mtime=self.PLAN_MTIME + 500)
        assert self._run_plan_is_fresh(repo_root, fixture) == "STALE"

    def test_python_source_change_invalidates_plan(self, repo_root: Path, tmp_path: Path) -> None:
        """A Lambda handler edit newer than the plan must force a re-plan."""
        fixture = self._build_fixture(tmp_path, dist_mtime=self.PLAN_MTIME - 500, source_mtime=self.PLAN_MTIME - 500)
        handler = fixture / "src/handlers/example.py"
        handler.parent.mkdir(parents=True, exist_ok=True)
        handler.write_text("# handler")
        os.utime(handler, (self.PLAN_MTIME + 500, self.PLAN_MTIME + 500))
        assert self._run_plan_is_fresh(repo_root, fixture) == "STALE"

    def test_missing_plan_is_stale(self, repo_root: Path, tmp_path: Path) -> None:
        fixture = self._build_fixture(tmp_path, dist_mtime=self.PLAN_MTIME - 500, source_mtime=self.PLAN_MTIME - 500)
        assert self._run_plan_is_fresh(repo_root, fixture, plan_name="no-such-plan") == "STALE"

    def test_newer_env_invalidates_plan(self, repo_root: Path, tmp_path: Path) -> None:
        """A root .env newer than the plan must force a re-plan."""
        fixture = self._build_fixture(tmp_path, dist_mtime=self.PLAN_MTIME - 500, source_mtime=self.PLAN_MTIME - 500)
        dot_env = fixture / ".env"
        dot_env.write_text("TF_VAR_encryption_passphrase=x")
        os.utime(dot_env, (self.PLAN_MTIME + 500, self.PLAN_MTIME + 500))
        assert self._run_plan_is_fresh(repo_root, fixture) == "STALE"
