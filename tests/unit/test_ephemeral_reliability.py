"""Focused tests for ephemeral teardown/recovery reliability changes.

These tests exercise the shell helpers in scripts/ephemeral-recover-common.sh and
the teardown behavior in scripts/ephemeral-env.sh by driving them with mocked AWS
and OpenTofu executables. They also validate the workflow dispatch surface and the
Lambda module's static for_each keys.
"""

from __future__ import annotations

import json
import os
import re
import shlex
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
            repo_root / "scripts" / "appsync-ensure-resolver-order.sh",
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

    def test_different_host_fresh_lock_is_left(self, repo_root: Path, tmp_env: Path) -> None:
        recorded = tmp_env / "aws_calls.txt"
        lock = {
            "Created": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
            "Who": "runner@other-host",
        }
        result = self._source_and_call(
            repo_root,
            tmp_env,
            f"""
            #!/bin/bash
            echo "$@" >> "{recorded}"
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
        assert "Lock appears fresh" in result.stderr
        rm_calls = [line for line in recorded.read_text().splitlines() if line.startswith("s3 rm")]
        assert not rm_calls, "Fresh lock from a different host must not be deleted"

    def test_different_host_stale_lock_is_removed(self, repo_root: Path, tmp_env: Path) -> None:
        recorded = tmp_env / "aws_calls.txt"
        lock = {
            "Created": (datetime.now(timezone.utc) - timedelta(seconds=900)).isoformat(),
            "Who": "runner@other-host",
        }
        result = self._source_and_call(
            repo_root,
            tmp_env,
            f"""
            #!/bin/bash
            echo "$@" >> "{recorded}"
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
        rm_calls = [line for line in recorded.read_text().splitlines() if line.startswith("s3 rm")]
        assert rm_calls, "Stale lock from a different host must be deleted"

    def test_same_host_fresh_lock_is_left(self, repo_root: Path, tmp_env: Path) -> None:
        recorded = tmp_env / "aws_calls.txt"
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
            echo "$@" >> "{recorded}"
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
        assert "Lock appears fresh" in result.stderr
        rm_calls = [line for line in recorded.read_text().splitlines() if line.startswith("s3 rm")]
        assert not rm_calls, "Fresh lock from the same host must not be deleted"

    def test_same_host_stale_lock_is_removed(self, repo_root: Path, tmp_env: Path) -> None:
        recorded = tmp_env / "aws_calls.txt"
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
            echo "$@" >> "{recorded}"
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
        rm_calls = [line for line in recorded.read_text().splitlines() if line.startswith("s3 rm")]
        assert rm_calls, "Stale lock from the same host must be deleted"


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
        assert "module.iam.aws_iam_role.lambda_execution" in calls
        assert "module.iam.aws_iam_role.lambda_admin_execution" in calls
        assert "module.iam.aws_iam_role_policy_attachment.lambda_basic" in calls
        assert "module.iam.aws_iam_role_policy_attachment.lambda_admin_basic" in calls
        assert "module.iam.aws_iam_role_policy.lambda_dynamodb" in calls
        assert "module.iam.aws_iam_role_policy.lambda_admin_dynamodb" in calls
        assert "module.iam.aws_iam_role_policy.lambda_admin_s3" in calls
        assert "module.iam.aws_iam_role_policy.lambda_admin_cloudfront" in calls
        assert "module.cognito.aws_iam_role_policy.lambda_cognito_admin" in calls
        assert "kernelworx-lambda-admin-exec-ue1-pr-999:cognito-admin" in calls
        assert "module.appsync.aws_iam_role_policy.appsync_logging" in calls
        assert "module.s3.aws_s3_bucket_versioning.static" in calls
        assert "module.s3.aws_s3_bucket_cors_configuration.exports" in calls

    def test_import_continues_on_error(
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
                exit 1
                ;;
              "appsync list-graphql-apis")
                exit 1
                ;;
              "lambda list-layer-versions" | "lambda list-functions")
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
            # Fail the first import, succeed on others
            if echo "$@" | grep -q "module.dynamodb.aws_dynamodb_table.accounts"; then
                exit 1
            fi
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
        assert "Import of module.dynamodb.aws_dynamodb_table.accounts" in result.stderr
        calls = recorded.read_text()
        # Despite accounts failing, subsequent tables and resources should still have been imported
        assert "module.dynamodb.aws_dynamodb_table.catalogs" in calls
        assert "module.iam.aws_iam_role.lambda_execution" in calls


class TestEmptyEphemeralS3Buckets:
    def test_empty_s3_buckets_deletes_versions_and_markers(
        self,
        repo_root: Path,
        tmp_env: Path,
    ) -> None:
        recorded_aws = tmp_env / "aws_calls.txt"
        write_mock(
            tmp_env,
            "aws",
            f"""
            #!/bin/bash
            echo "$@" >> "{recorded_aws}"
            case "$1 $2" in
              "s3api head-bucket")
                exit 0
                ;;
              "s3api list-object-versions")
                echo '{{"Versions": [{{"Key": "file1.txt", "VersionId": "v1"}}], "DeleteMarkers": [{{"Key": "file2.txt", "VersionId": "v2"}}]}}'
                ;;
              "s3api delete-objects")
                exit 0
                ;;
              "s3 rm")
                exit 0
                ;;
            esac
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            source scripts/ephemeral-recover-common.sh
            empty_ephemeral_s3_buckets pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        assert "Emptying S3 buckets for run: pr-999" in result.stderr
        calls = recorded_aws.read_text()
        assert "s3api delete-objects" in calls
        assert "s3 rm s3://kernelworx-static-ue1-pr-999" in calls
        assert "s3 rm s3://kernelworx-exports-ue1-pr-999" in calls

    def test_empty_s3_buckets_skips_nonexistent_buckets(
        self,
        repo_root: Path,
        tmp_env: Path,
    ) -> None:
        write_mock(
            tmp_env,
            "aws",
            """
            #!/bin/bash
            if [ "$1" = "s3api" ] && [ "$2" = "head-bucket" ]; then
                exit 1
            fi
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            source scripts/ephemeral-recover-common.sh
            empty_ephemeral_s3_buckets pr-999
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr
        assert "Emptying S3 buckets for run: pr-999" in result.stderr


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
              "s3api head-bucket")
                exit 1
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

    @staticmethod
    def _normalize_if_expression(expression: str) -> str:
        """Normalize a GitHub Actions `if` expression for semantic comparison."""
        return re.sub(r"\s+", " ", expression.replace("${{", "").replace("}}", "")).strip()

    @staticmethod
    def _extract_command_args(script: str, basename: str, subcommand: str) -> list[str]:
        """Parse a shell script and return the args of the first matching command."""
        for line in script.splitlines():
            segment = line.split("|", 1)[0].strip()
            if not segment:
                continue
            parts = shlex.split(segment)
            if len(parts) >= 2 and parts[0].endswith(basename) and parts[1] == subcommand:
                return parts
        raise AssertionError(f"Could not find {basename} {subcommand} command in script")

    def test_ephemeral_test_has_no_manual_jobs(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        jobs = workflow.get("jobs", {})
        assert set(jobs) == {"ephemeral-test", "sweep"}
        assert "workflow_dispatch" not in (workflow.get("on") or {})

    def test_ephemeral_test_job_only_runs_on_pull_request(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        job_if = workflow["jobs"]["ephemeral-test"].get("if", "")
        normalized = self._normalize_if_expression(job_if)
        assert normalized == (
            "github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository"
        ), f"ephemeral-test job must be gated to same-repo pull_request events, got: {job_if!r}"

    def test_ephemeral_test_uses_valid_pr_run_id(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        up_step = next(s for s in workflow["jobs"]["ephemeral-test"]["steps"] if s.get("id") == "ephemeral_up")
        run_script = up_step["run"]
        args = self._extract_command_args(run_script, "ephemeral-env.sh", "up")
        assert args[2] == "pr-${{ github.event.pull_request.number }}", (
            "ephemeral-env.sh up must use a PR-numbered run-id"
        )

    def test_sweep_job_has_ephemeral_environment(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        sweep_job = workflow["jobs"]["sweep"]
        assert sweep_job.get("environment") == "ephemeral", (
            "sweep job must use the ephemeral environment so it can assume the AWS role"
        )

    def test_sweep_job_only_runs_on_schedule(self, repo_root: Path) -> None:
        workflow = self._load_workflow(repo_root)
        job_if = workflow["jobs"]["sweep"].get("if", "")
        normalized = self._normalize_if_expression(job_if)
        assert normalized == "github.event_name == 'schedule'", (
            f"sweep job must be gated to schedule events, got: {job_if!r}"
        )

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

    def test_sweep_skips_open_and_unknown_pr_states(self, repo_root: Path, tmp_env: Path) -> None:
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
                echo "2026-08-23 00:00:00 1234 application/ephemeral/pr-99/terraform.tfstate"
            fi
            exit 0
            """,
        )
        write_mock(
            tmp_env,
            "gh",
            """
            #!/bin/bash
            if echo "$*" | grep -q "\\b7\\b"; then
                echo "OPEN"
            else
                echo "UNKNOWN"
            fi
            exit 0
            """,
        )
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
        calls = teardown_calls.read_text().splitlines() if teardown_calls.exists() else []
        assert calls == [], f"Expected no teardown calls for OPEN/UNKNOWN states, got: {calls}"

    def test_sweep_fails_when_teardown_fails(self, repo_root: Path, tmp_env: Path) -> None:
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
        assert result.returncode == 1, result.stderr
        calls = set(teardown_calls.read_text().splitlines())
        assert calls == {"down pr-7", "down pr-42"}

    def test_sweep_continues_after_partial_failure(self, repo_root: Path, tmp_env: Path) -> None:
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
            if echo "$@" | grep -q "pr-7"; then
                exit 1
            fi
            exit 0
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
        assert result.returncode == 1, result.stderr
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


class TestEphemeralResourceImportCoverage:
    """Dynamic test ensuring every resource declared in OpenTofu for ephemeral
    environments is covered by the recovery import logic in scripts/ephemeral-recover-common.sh."""

    @staticmethod
    def _extract_map_keys(content: str, map_name: str) -> list[str]:
        import re

        pattern = re.compile(r"\b" + map_name + r"\s*=\s*\{")
        m = pattern.search(content)
        if not m:
            return []
        start = m.end() - 1
        depth = 0
        i = start
        block = ""
        while i < len(content):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    block = content[start + 1 : i]
                    break
            i += 1
        return re.findall(r'^\s*"([a-z0-9-]+)"\s*=', block, re.MULTILINE)

    @classmethod
    def get_declared_ephemeral_resources(cls, repo_root: Path) -> set[str]:
        import re

        modules_dir = repo_root / "tofu" / "application" / "modules"

        # 1. DynamoDB
        dynamodb_tf = (modules_dir / "dynamodb" / "main.tf").read_text()
        tables = re.findall(r'resource\s+"aws_dynamodb_table"\s+"([^"]+)"', dynamodb_tf)
        dynamodb_res = {f"module.dynamodb.aws_dynamodb_table.{t}" for t in tables}

        # 2. S3
        s3_tf = (modules_dir / "s3" / "main.tf").read_text()
        s3_res = set()
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"', s3_tf):
            s3_res.add(f"module.s3.{m.group(1)}.{m.group(2)}")

        # 3. IAM (ephemeral stack has cloudfront_distribution_arn = null, so cloudfront invalidation policies are omitted)
        iam_tf = (modules_dir / "iam" / "main.tf").read_text()
        iam_res = set()
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"', iam_tf):
            rtype, rname = m.group(1), m.group(2)
            if "cloudfront" in rname:
                continue
            iam_res.add(f"module.iam.{rtype}.{rname}")

        # 4. Cognito (ephemeral uses prefix domain and lambda triggers)
        cognito_tf = (modules_dir / "cognito" / "main.tf").read_text()
        cognito_res = set()
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"', cognito_tf):
            rtype, rname = m.group(1), m.group(2)
            if "custom" in rname or "google" in rname:
                continue
            if rtype == "aws_cognito_user_pool_domain" and rname == "prefix":
                cognito_res.add(f"module.cognito.{rtype}.{rname}[0]")
            elif rtype == "aws_lambda_permission":
                cognito_res.add(f"module.cognito.{rtype}.{rname}[0]")
            else:
                cognito_res.add(f"module.cognito.{rtype}.{rname}")

        # 5. Lambda (shared layer, plus functions and log groups for functions and trigger_functions)
        lambda_tf = (modules_dir / "lambda" / "main.tf").read_text()
        func_keys = cls._extract_map_keys(lambda_tf, "functions")
        trigger_func_keys = cls._extract_map_keys(lambda_tf, "trigger_functions")

        lambda_res = {"module.lambda.aws_lambda_layer_version.shared"}
        for fk in func_keys:
            lambda_res.add(f'module.lambda.aws_lambda_function.functions["{fk}"]')
            lambda_res.add(f'module.lambda.aws_cloudwatch_log_group.functions["{fk}"]')
        for tfk in trigger_func_keys:
            lambda_res.add(f'module.lambda.aws_lambda_function.trigger_functions["{tfk}"]')
            lambda_res.add(f'module.lambda.aws_cloudwatch_log_group.trigger_functions["{tfk}"]')

        # 6. AppSync (static: api, logging role, logging policy, cloudwatch log group; dynamic: datasources, functions, resolvers)
        appsync_res = {
            "module.appsync.aws_appsync_graphql_api.main",
            "module.appsync.aws_iam_role.appsync_logging",
            "module.appsync.aws_iam_role_policy.appsync_logging",
            "module.appsync.aws_cloudwatch_log_group.appsync",
        }
        for tf_file in sorted((modules_dir / "appsync").glob("*.tf")):
            content = tf_file.read_text()
            for m in re.finditer(
                r'resource\s+"(aws_appsync_datasource|aws_appsync_function|aws_appsync_resolver)"\s+"([^"]+)"', content
            ):
                appsync_res.add(f"module.appsync.{m.group(1)}.{m.group(2)}")

        return dynamodb_res | s3_res | iam_res | cognito_res | lambda_res | appsync_res

    def test_dynamic_resource_import_coverage(self, repo_root: Path, tmp_env: Path) -> None:
        import re

        declared_resources = self.get_declared_ephemeral_resources(repo_root)
        assert len(declared_resources) > 0, "Declared ephemeral resources must not be empty"

        recorded = tmp_env / "tofu_calls.txt"

        lambda_tf = (repo_root / "tofu" / "application" / "modules" / "lambda" / "main.tf").read_text()
        func_keys = self._extract_map_keys(lambda_tf, "functions")
        trigger_func_keys = self._extract_map_keys(lambda_tf, "trigger_functions")

        all_func_names = [f"kernelworx-{fk}-ue1-pr-coverage" for fk in func_keys] + [
            f"kernelworx-{tfk}-ue1-pr-coverage" for tfk in trigger_func_keys
        ]
        functions_json = json.dumps({"Functions": [{"FunctionName": fn} for fn in all_func_names]})

        appsync_dir = repo_root / "tofu" / "application" / "modules" / "appsync"
        appsync_tf_content = "".join(f.read_text() + "\n" for f in sorted(appsync_dir.glob("*.tf")))

        ds_names = re.findall(
            r'resource\s+"aws_appsync_datasource"\s+"([^"]+)".*?name\s*=\s*"([^"]+)"',
            appsync_tf_content,
            re.DOTALL,
        )
        ds_json = json.dumps({"dataSources": [{"name": aws_name} for _, aws_name in ds_names]})

        fn_matches = re.findall(
            r'resource\s+"aws_appsync_function"\s+"([^"]+)".*?name\s*=\s*"([^"]+)"',
            appsync_tf_content,
            re.DOTALL,
        )
        fn_list = []
        for i, (_, raw_name) in enumerate(fn_matches):
            fn_name = raw_name.replace("${local.env_suffix}", "_pr_coverage")
            fn_list.append({"name": fn_name, "functionId": f"fn_{i}"})
        fn_json = json.dumps({"functions": fn_list})

        res_matches = re.findall(
            r'resource\s+"aws_appsync_resolver"\s+"([^"]+)".*?type\s*=\s*"([^"]+)".*?field\s*=\s*"([^"]+)"',
            appsync_tf_content,
            re.DOTALL,
        )
        resolvers_by_type: dict[str, list[dict]] = {}
        for _, type_name, field_name in res_matches:
            resolvers_by_type.setdefault(type_name, []).append({"typeName": type_name, "fieldName": field_name})

        resolvers_map_file = tmp_env / "resolvers.json"
        resolvers_map_file.write_text(json.dumps(resolvers_by_type))

        write_mock(
            tmp_env,
            "aws",
            f"""
            #!/bin/bash
            case "$1 $2" in
              "s3api head-bucket")
                exit 0
                ;;
              "dynamodb describe-table")
                exit 0
                ;;
              "cognito-idp list-user-pools")
                echo '{json.dumps({"UserPools": [{"Name": "kernelworx-users-ue1-pr-coverage", "Id": "us-east-1_COVERAGE"}]})}'
                ;;
              "cognito-idp list-user-pool-clients")
                echo '{json.dumps({"UserPoolClients": [{"ClientName": "KernelWorx-Web", "ClientId": "client-coverage"}]})}'
                ;;
              "lambda get-function")
                exit 0
                ;;
              "appsync list-graphql-apis")
                echo '{json.dumps({"graphqlApis": [{"name": "kernelworx-api-ue1-pr-coverage", "apiId": "api-coverage"}]})}'
                ;;
              "appsync list-data-sources")
                echo '{ds_json}'
                ;;
              "appsync list-functions")
                echo '{fn_json}'
                ;;
              "appsync list-resolvers")
                type_name=""
                while [ $# -gt 0 ]; do
                  if [ "$1" = "--type-name" ]; then
                    type_name="$2"
                    shift 2
                  else
                    shift
                  fi
                done
                python3 -c "import sys, json; m=json.load(open('{resolvers_map_file}')); print(json.dumps({{'resolvers': m.get('$type_name', [])}}))"
                ;;
              "lambda list-layer-versions")
                echo '{json.dumps({"LayerVersions": [{"Version": 1}]})}'
                ;;
              "lambda get-layer-version")
                echo "arn:aws:lambda:us-east-1:123456789012:layer:kernelworx-deps-ue1-pr-coverage:1"
                ;;
              "lambda list-functions")
                echo '{functions_json}'
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
            if [ "$1" = "import" ]; then
                echo "$4" >> "{recorded}"
            fi
            exit 0
            """,
        )

        script = """
            set -e
            export STATE_BUCKET="test-bucket"
            export STATE_REGION="us-east-1"
            export TF_VAR_encryption_passphrase="not-used"
            source scripts/ephemeral-recover-common.sh
            import_ephemeral_resources pr-coverage
        """
        result = run_bash(repo_root, script)
        assert result.returncode == 0, result.stderr

        imported_addresses = set(recorded.read_text().splitlines()) if recorded.exists() else set()
        missing = declared_resources - imported_addresses

        assert not missing, (
            f"The following {len(missing)} OpenTofu ephemeral resource(s) are declared in modules "
            f"but lack corresponding recovery import logic in scripts/ephemeral-recover-common.sh:\n"
            + "\n".join(sorted(missing))
        )
