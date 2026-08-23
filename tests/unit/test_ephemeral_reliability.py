"""Focused tests for ephemeral teardown/recovery reliability changes.

These tests exercise the shell helpers in scripts/ephemeral-recover-common.sh and
the teardown behavior in scripts/ephemeral-env.sh by driving them with mocked AWS
and OpenTofu executables. They also validate the workflow dispatch surface and the
Lambda module's static for_each keys.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated temp directory prepended to PATH."""
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


def write_mock(tmp_env: Path, name: str, body: str) -> Path:
    path = tmp_env / name
    path.write_text(textwrap.dedent(body).strip() + "\n")
    path.chmod(0o755)
    return path


def run_bash(repo_root: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


class TestBashSyntax:
    def test_all_shell_scripts_parse(self, repo_root: Path) -> None:
        scripts = [
            repo_root / "scripts" / "ephemeral-env.sh",
            repo_root / "scripts" / "ephemeral-recover-common.sh",
            repo_root / "scripts" / "recover-deploy.sh",
            repo_root / "scripts" / "recover-destroy.sh",
            repo_root / "scripts" / "create-ephemeral-test-users.sh",
        ]
        for script in scripts:
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            assert result.returncode == 0, f"{script.name} failed bash syntax check: {result.stderr}"


class TestCleanupStaleLock:
    def _source_and_call(
        self,
        repo_root: Path,
        tmp_env: Path,
        aws_body: str,
        run_id: str = "pr-999",
    ) -> subprocess.CompletedProcess[str]:
        write_mock(tmp_env, "aws", aws_body)
        write_mock(tmp_env, "tofu", '#!/bin/bash\necho "tofu $1"')
        script = f"""
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            source scripts/ephemeral-recover-common.sh
            cleanup_stale_lock "{run_id}"
        """
        return run_bash(repo_root, script)

    def test_no_lock_object_returns_cleanly(self, repo_root: Path, tmp_env: Path) -> None:
        result = self._source_and_call(
            repo_root,
            tmp_env,
            """
            #!/bin/bash
            if [ "$1" = "s3api" ] && [ "$2" = "head-object" ]; then
                exit 1
            fi
            exit 0
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "No lock object found" in result.stderr

    def test_different_host_lock_is_removed(self, repo_root: Path, tmp_env: Path) -> None:
        lock = {"Created": "2026-08-23T00:00:00Z", "Who": "runner@other-host"}
        result = self._source_and_call(
            repo_root,
            tmp_env,
            f"""
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 0
                ;;
              "s3 cp")
                echo '{json.dumps(lock)}'
                ;;
              "s3 rm")
                echo "removed"
                ;;
            esac
            exit 0
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "Lock belongs to a different host" in result.stderr

    def test_same_host_fresh_lock_is_left(self, repo_root: Path, tmp_env: Path) -> None:
        this_host = os.uname().nodename
        lock = {
            "Created": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
            "Who": f"runner@{this_host}",
        }
        result = self._source_and_call(
            repo_root,
            tmp_env,
            f"""
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 0
                ;;
              "s3 cp")
                echo '{json.dumps(lock)}'
                ;;
            esac
            exit 0
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "Lock appears fresh and from this host" in result.stderr

    def test_same_host_stale_lock_is_removed(self, repo_root: Path, tmp_env: Path) -> None:
        this_host = os.uname().nodename
        lock = {
            "Created": (datetime.now(timezone.utc) - timedelta(seconds=900)).isoformat(),
            "Who": f"runner@{this_host}",
        }
        result = self._source_and_call(
            repo_root,
            tmp_env,
            f"""
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 0
                ;;
              "s3 cp")
                echo '{json.dumps(lock)}'
                ;;
              "s3 rm")
                echo "removed"
                ;;
            esac
            exit 0
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "Lock is older than threshold" in result.stderr


class TestRecoverStateIfMissing:
    """recover_state_if_missing is exercised through ephemeral-env.sh down."""

    def _run_down(
        self,
        repo_root: Path,
        tmp_env: Path,
        aws_body: str,
        tofu_body: str,
        build_dir: Path,
    ) -> subprocess.CompletedProcess[str]:
        write_mock(tmp_env, "aws", aws_body)
        write_mock(tmp_env, "tofu", tofu_body)
        if build_dir.exists():
            shutil.rmtree(build_dir)
        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            scripts/ephemeral-env.sh down pr-999
        """
        return run_bash(repo_root, script)

    def test_existing_state_is_not_recovered(self, repo_root: Path, tmp_env: Path) -> None:
        build_dir = repo_root / ".build" / "lambda-layer"
        result = self._run_down(
            repo_root,
            tmp_env,
            """
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                echo "exists"
                exit 0
                ;;
              "s3 rm")
                exit 0
                ;;
            esac
            exit 0
            """,
            """
            #!/bin/bash
            if [ "$1" = "destroy" ]; then
                exit 0
            fi
            exit 0
            """,
            build_dir,
        )
        assert result.returncode == 0, result.stderr
        assert "State object exists" in result.stderr
        assert "No previous state version found" not in result.stderr

    def test_missing_state_restores_latest_version(self, repo_root: Path, tmp_env: Path) -> None:
        build_dir = repo_root / ".build" / "lambda-layer"
        result = self._run_down(
            repo_root,
            tmp_env,
            """
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 1
                ;;
              "s3api list-object-versions")
                echo 'v123'
                ;;
              "s3api copy-object")
                echo 'copied'
                ;;
              "s3 rm")
                exit 0
                ;;
            esac
            exit 0
            """,
            """
            #!/bin/bash
            if [ "$1" = "destroy" ]; then
                exit 0
            fi
            exit 0
            """,
            build_dir,
        )
        assert result.returncode == 0, result.stderr
        assert "Restoring state from version v123" in result.stderr

    def test_missing_state_no_version_continues(self, repo_root: Path, tmp_env: Path) -> None:
        build_dir = repo_root / ".build" / "lambda-layer"
        result = self._run_down(
            repo_root,
            tmp_env,
            """
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 1
                ;;
              "s3api list-object-versions")
                echo 'None'
                ;;
              "s3 rm")
                exit 0
                ;;
            esac
            exit 0
            """,
            """
            #!/bin/bash
            if [ "$1" = "destroy" ]; then
                exit 0
            fi
            exit 0
            """,
            build_dir,
        )
        assert result.returncode == 0, result.stderr
        assert "No previous state version found" in result.stderr


class TestEphemeralEnvDown:
    def test_down_skips_layer_build_and_uses_placeholder(self, repo_root: Path, tmp_env: Path) -> None:
        recorded = tmp_env / "tofu_calls.txt"
        build_dir = repo_root / ".build" / "lambda-layer"
        if build_dir.exists():
            shutil.rmtree(build_dir)

        write_mock(
            tmp_env,
            "aws",
            """
            #!/bin/bash
            case "$1 $2" in
              "s3api head-object")
                exit 1
                ;;
              "s3api list-object-versions")
                echo 'None'
                ;;
              "s3 rm")
                exit 0
                ;;
            esac
            exit 0
            """,
        )
        write_mock(
            tmp_env,
            "tofu",
            f"""
            #!/bin/bash
            echo "tofu $1" >> "{recorded}"
            if [ "$1" = "destroy" ]; then
                exit 0
            fi
            exit 0
            """,
        )

        script = f"""
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            rm -f "{recorded}"
            scripts/ephemeral-env.sh down pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        assert (build_dir / "python" / ".placeholder").exists()
        assert "placeholder" in (build_dir / "python" / ".placeholder").read_text()
        tofu_calls = recorded.read_text()
        assert "tofu init" in tofu_calls
        assert "tofu destroy" in tofu_calls
        assert "Building Lambda layer" not in result.stderr


class TestWorkflowDispatchSurface:
    def _load_workflow(self, repo_root: Path) -> dict:
        """Load workflow YAML preserving the ``on`` key as a string."""
        workflow_path = repo_root / ".github" / "workflows" / "ephemeral-test.yml"
        # PyYAML resolves ``on`` as the boolean True by default.
        workflow = yaml.safe_load(workflow_path.read_text())
        on_value = workflow.pop(True, None)
        if on_value is None:
            on_value = workflow.get("on")
        workflow["on"] = on_value
        return workflow

    def test_workflow_has_manual_modes(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        inputs = workflow.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
        assert "mode" in inputs
        assert set(inputs["mode"]["options"]) == {"down", "recover-deploy", "recover-destroy"}
        assert "pr_number" in inputs

        jobs = workflow.get("jobs", {})
        assert "manual-teardown" in jobs
        assert "recover-deploy" in jobs
        assert "recover-destroy" in jobs
        assert "mode == 'down'" in jobs["manual-teardown"]["if"]
        assert "mode == 'recover-deploy'" in jobs["recover-deploy"]["if"]
        assert "mode == 'recover-destroy'" in jobs["recover-destroy"]["if"]

    def test_sweep_continues_on_error(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        sweep_step = workflow["jobs"]["sweep"]["steps"][-1]
        run_script = sweep_step["run"]
        assert "scripts/ephemeral-env.sh down" in run_script
        assert "Teardown failed" in run_script
        assert "continuing sweep" in run_script


class TestLambdaLogGroupStaticForEach:
    def test_log_groups_use_local_maps_not_function_attributes(self, repo_root: Path) -> None:
        module_path = repo_root / "tofu" / "application" / "modules" / "lambda" / "main.tf"
        content = module_path.read_text()
        # Static for_each means the keys come from local.functions / local.trigger_functions,
        # not from computed aws_lambda_function.* attributes.
        assert "for_each = local.functions" in content
        assert "for_each = local.trigger_functions" in content
        assert "for_each = aws_lambda_function." not in content

    def test_lambda_module_validates(self, repo_root: Path, tmp_path: Path) -> None:
        module_dir = repo_root / "tofu" / "application" / "modules" / "lambda"
        # Run init/validate in a temp copy so the worktree is not polluted.
        work_dir = tmp_path / "lambda-module"
        shutil.copytree(module_dir, work_dir)
        result = subprocess.run(
            ["tofu", "init", "-backend=false", "-input=false"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"tofu init failed: {result.stderr}"
        result = subprocess.run(
            ["tofu", "validate"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"tofu validate failed: {result.stderr}"
