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
    path.parent.mkdir(parents=True, exist_ok=True)
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
    """recover_state_if_missing is exercised through ephemeral-env.sh down,
    recover-deploy.sh, and recover-destroy.sh."""

    @pytest.fixture
    def build_dir(self, tmp_path: Path) -> Path:
        """Provide an isolated Lambda layer build directory."""
        return tmp_path / "lambda-layer"

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
        script = f"""
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            export KERNELWORX_TEST_LAYER_DIR="{build_dir}"
            scripts/ephemeral-env.sh down pr-999
        """
        return run_bash(repo_root, script)

    def test_existing_state_is_not_recovered(self, repo_root: Path, tmp_env: Path, build_dir: Path) -> None:
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

    def test_missing_state_restores_latest_version(self, repo_root: Path, tmp_env: Path, build_dir: Path) -> None:
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

    def test_missing_state_no_version_continues(self, repo_root: Path, tmp_env: Path, build_dir: Path) -> None:
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


class TestRecoverDeploy:
    """recover-deploy.sh restores S3 state before importing resources."""

    def test_recover_deploy_restores_missing_state_before_import(
        self,
        repo_root: Path,
        tmp_env: Path,
    ) -> None:
        recorded = tmp_env / "tofu_calls.txt"
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
                echo 'v789'
                ;;
              "s3api copy-object")
                exit 0
                ;;
              "s3api head-bucket" | "dynamodb describe-table")
                exit 1
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
            echo "$@" >> "{recorded}"
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            scripts/recover-deploy.sh pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        assert "Restoring state from version v789" in result.stderr
        tofu_calls = recorded.read_text().splitlines()
        assert tofu_calls and tofu_calls[0].startswith("init"), f"tofu init should be first, got: {tofu_calls}"


class TestRecoverDestroy:
    """recover-destroy.sh restores S3 state before importing and destroying."""

    def test_recover_destroy_restores_missing_state(
        self,
        repo_root: Path,
        tmp_env: Path,
    ) -> None:
        recorded = tmp_env / "tofu_calls.txt"
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
                echo 'v456'
                ;;
              "s3api copy-object")
                exit 0
                ;;
              "s3 rm")
                exit 0
                ;;
              "s3api head-bucket" | "dynamodb describe-table")
                exit 1
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
            echo "$@" >> "{recorded}"
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            scripts/recover-destroy.sh pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        assert "Restoring state from version v456" in result.stderr
        tofu_calls = recorded.read_text().splitlines()
        assert tofu_calls and tofu_calls[0].startswith("init"), f"tofu init should be first, got: {tofu_calls}"
        assert any(c.startswith("destroy") for c in tofu_calls), f"tofu destroy should run, got: {tofu_calls}"


class TestImportEphemeralResources:
    """import_ephemeral_resources issues imports for state-tracked sub-resources."""

    def test_static_iam_and_s3_imports_are_issued(
        self,
        repo_root: Path,
        tmp_env: Path,
    ) -> None:
        recorded = tmp_env / "tofu_calls.txt"
        write_mock(
            tmp_env,
            "aws",
            """
            #!/bin/bash
            case "$1 $2" in
              "s3api head-bucket")
                exit 0
                ;;
              "dynamodb describe-table")
                exit 0
                ;;
              "cognito-idp list-user-pools")
                echo '{"UserPools": [{"Name": "kernelworx-users-ue1-pr-999", "Id": "us-east-1_POOL"}]}'
                ;;
              "cognito-idp list-user-pool-clients")
                echo '{"UserPoolClients": [{"ClientName": "KernelWorx-Web", "ClientId": "client123"}]}'
                ;;
              "appsync list-graphql-apis")
                echo '{"graphqlApis": [{"name": "kernelworx-api-ue1-pr-999", "apiId": "api123"}]}'
                ;;
              "appsync list-data-sources" | "appsync list-functions")
                echo '{"dataSources": [], "functions": []}'
                ;;
              "appsync list-resolvers")
                echo '{"resolvers": []}'
                ;;
              "lambda list-layer-versions")
                echo '{"LayerVersions": []}'
                ;;
              "lambda list-functions")
                echo '{"Functions": []}'
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
            echo "$@" >> "{recorded}"
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            source scripts/ephemeral-recover-common.sh
            import_ephemeral_resources pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        calls = recorded.read_text()
        assert "module.iam.aws_iam_role_policy_attachment.lambda_basic" in calls
        assert "module.iam.aws_iam_role_policy.lambda_dynamodb" in calls
        assert "module.cognito.aws_iam_role_policy.lambda_cognito_admin" in calls
        assert "module.appsync.aws_iam_role_policy.appsync_logging" in calls
        assert "module.s3.aws_s3_bucket_versioning.static" in calls
        assert "module.s3.aws_s3_bucket_cors_configuration.exports" in calls


class TestEphemeralEnvDown:
    def test_down_skips_layer_build_and_uses_placeholder(self, repo_root: Path, tmp_env: Path, tmp_path: Path) -> None:
        recorded = tmp_env / "tofu_calls.txt"
        build_dir = tmp_path / "lambda-layer"

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
            export KERNELWORX_TEST_LAYER_DIR="{build_dir}"
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
    def _load_workflow(self, repo_root: Path, filename: str = "ephemeral-test.yml") -> dict:
        """Load workflow YAML preserving the ``on`` key as a string."""
        workflow_path = repo_root / ".github" / "workflows" / filename
        # PyYAML resolves ``on`` as the boolean True by default.
        workflow = yaml.safe_load(workflow_path.read_text())
        on_value = workflow.pop(True, None)
        if on_value is None:
            on_value = workflow.get("on")
        workflow["on"] = on_value
        return workflow

    @staticmethod
    def _if_gates_on_mode(expression: str, expected_mode: str) -> bool:
        """Check that a GitHub Actions `if` expression gates on the expected mode."""
        normalized = expression.replace("${{", "").replace("}}", "").replace(" ", "")
        return (
            f"github.event.inputs.mode=='{expected_mode}'" in normalized
            or f"inputs.mode=='{expected_mode}'" in normalized
        )

    def test_ephemeral_test_has_no_manual_jobs(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        jobs = workflow.get("jobs", {})
        assert set(jobs) == {"ephemeral-test", "sweep"}
        assert "workflow_dispatch" not in (workflow.get("on") or {})

    def test_manual_teardown_workflow(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root, "manual-teardown.yml")
        inputs = workflow.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
        assert "pr_number" in inputs
        assert inputs["pr_number"]["required"] is True

        concurrency = workflow.get("concurrency", {})
        assert "manual-teardown-" in concurrency.get("group", "")
        assert "inputs.pr_number" in concurrency.get("group", "")

        jobs = workflow.get("jobs", {})
        assert set(jobs) == {"manual-teardown"}
        assert "if" not in jobs["manual-teardown"]

    def test_recover_environment_workflow(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root, "recover-environment.yml")
        inputs = workflow.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
        assert "pr_number" in inputs
        assert inputs["pr_number"]["required"] is True
        assert set(inputs["mode"]["options"]) == {"recover-deploy", "recover-destroy"}

        concurrency = workflow.get("concurrency", {})
        assert "recover-environment-" in concurrency.get("group", "")
        assert "inputs.pr_number" in concurrency.get("group", "")

        jobs = workflow.get("jobs", {})
        assert set(jobs) == {"recover-deploy", "recover-destroy"}
        assert self._if_gates_on_mode(jobs["recover-deploy"]["if"], "recover-deploy")
        assert self._if_gates_on_mode(jobs["recover-destroy"]["if"], "recover-destroy")

    def test_sweep_continues_on_error(self, repo_root: Path, tmp_env: Path) -> None:
        workflow = self._load_workflow(repo_root)
        sweep_step = workflow["jobs"]["sweep"]["steps"][-1]
        run_script = sweep_step["run"]

        teardown_calls = tmp_env / "teardown_calls.txt"
        write_mock(
            tmp_env,
            "aws",
            """
            #!/bin/bash
            if [ "$1" = "s3" ] && [ "$2" = "ls" ]; then
                echo "2026-08-23 00:00:00 1234 application/ephemeral/pr-7/terraform.tfstate"
                echo "2026-08-23 00:00:00 1234 application/ephemeral/pr-42/terraform.tfstate"
            fi
            exit 0
            """,
        )
        write_mock(tmp_env, "gh", '#!/bin/bash\necho "CLOSED"')
        write_mock(
            tmp_env,
            "scripts/ephemeral-env.sh",
            f"""
            #!/bin/bash
            echo "$@" >> "{teardown_calls}"
            exit 1
            """,
        )

        result = subprocess.run(
            ["bash", "-c", run_script],
            cwd=tmp_env,
            capture_output=True,
            text=True,
            env={**os.environ, "GH_TOKEN": "test-token"},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        calls = set(teardown_calls.read_text().splitlines())
        assert calls == {"down pr-7", "down pr-42"}


class TestLambdaLogGroupStaticForEach:
    def test_lambda_module_validates(self, repo_root: Path, tmp_path: Path) -> None:
        tofu_bin = shutil.which("tofu")
        if tofu_bin is None:
            pytest.skip("OpenTofu (tofu) is not installed in this environment")

        module_dir = repo_root / "tofu" / "application" / "modules" / "lambda"
        # Run init/validate in a temp copy so the worktree is not polluted.
        work_dir = tmp_path / "lambda-module"
        shutil.copytree(module_dir, work_dir)
        result = subprocess.run(
            [tofu_bin, "init", "-backend=false", "-input=false"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"tofu init failed: {result.stderr}"
        result = subprocess.run(
            [tofu_bin, "validate"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"tofu validate failed: {result.stderr}"
