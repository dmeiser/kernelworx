"""Regression tests for #709: frontend/deploy.sh must not guess the app client
and must not delete prior hashed assets.

``frontend/deploy.sh`` resolves the Cognito App Client ID from OpenTofu outputs,
and when those outputs are unavailable (uninitialized local ``.terraform`` state)
falls back to an AWS CLI lookup. That fallback used to be
``list-user-pool-clients --max-results 1 --query UserPoolClients[0].ClientId``,
which returns the first client in pool order — a separately created,
non-tofu-managed client that lacks the required auth flows — and bakes the wrong
``VITE_COGNITO_USER_POOL_CLIENT_ID`` into the bundle (AGENTS.md, #336/#567). It
must instead look the client up by name (``KernelWorx-Web``), matching
``deploy-shared.yml``, and fail loudly when it cannot resolve it.

The script also ran ``aws s3 sync dist ... --delete``, which deletes prior
hashed JS/CSS chunks that clients holding a cached ``index.html`` may still
request until the CloudFront invalidation completes (the same warning recorded in
``deploy-shared.yml``).

These tests run the real script against a mock ``aws`` so the assertions are
behavioral: they observe which client-lookup query the script issues and whether
the S3 sync carries ``--delete``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "frontend" / "deploy.sh"

POOL_ID = "us-east-1_ExamplePool"
# The tofu-managed KernelWorx-Web app client id (the correct answer).
WEB_CLIENT_ID = "1a2b3c4d5e6f7a8b9c0d1e2f3a4"
# The pool's first client in list order: separately created, not tofu-managed,
# and the id the removed `--max-results 1` fallback would have picked.
FIRST_CLIENT_ID = "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5"

# The mock records every aws invocation (null-separated args) and answers each
# subcommand, so a test can assert which client-id resolution path the script
# took and whether the S3 sync carried --delete.
MOCK_AWS = """\
#!/bin/bash
printf '%s\\0' "$@" >> "$MOCK_AWS_LOG"
printf '\\0' >> "$MOCK_AWS_LOG"
case "$*" in
  *'list-user-pool-clients'*)
    case "$*" in
      *'ClientName==`KernelWorx-Web`'*)
        if [ "${WEB_CLIENT_PRESENT:-1}" = "1" ]; then echo "__WEB_CLIENT_ID__"; fi
        ;;
      *'UserPoolClients[0].ClientId'*)
        echo "__FIRST_CLIENT_ID__"
        ;;
    esac
    ;;
  *'list-user-pools'*)
    echo "__POOL_ID__"
    ;;
  *'describe-user-pool'*)
    echo "login.dev.kernelworx.app"
    ;;
  *'head-bucket'*)
    exit 0
    ;;
  *'list-distributions'*)
    echo "E1234567890ABC"
    ;;
  *'list-graphql-apis'*)
    echo "https://appsync.example.com/graphql"
    ;;
  *'s3 sync'*)
    exit 0
    ;;
  *'create-invalidation'*)
    echo "I0INVALIDATION0"
    ;;
esac
""".replace("__WEB_CLIENT_ID__", WEB_CLIENT_ID).replace(
    "__FIRST_CLIENT_ID__", FIRST_CLIENT_ID
).replace("__POOL_ID__", POOL_ID)

# npm run build is invoked by the script; stub it so the test observes only the
# configuration and upload decisions.
MOCK_NPM = """\
#!/bin/bash
exit 0
"""


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A temp dir holding a copy of deploy.sh plus mock binaries.

    The copy's parent has no ``tofu/application/environments`` tree, so every
    ``tofu output`` lookup fails and the AWS CLI fallbacks engage — exactly the
    uninitialized-state scenario the issue describes.
    """
    scripts = tmp_path / "frontend"
    scripts.mkdir()
    shutil.copy2(DEPLOY_SCRIPT, scripts / "deploy.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", MOCK_AWS), ("npm", MOCK_NPM)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)

    (tmp_path / "calls.log").touch()
    return tmp_path


def run_deploy(run_dir: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(run_dir / "frontend" / "deploy.sh")],
        capture_output=True,
        text=True,
        check=False,
        cwd=run_dir / "frontend",
        env={
            **os.environ,
            "PATH": f"{run_dir / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "ENVIRONMENT": "dev",
            "AWS_REGION": "us-east-1",
            "MOCK_AWS_LOG": str(run_dir / "calls.log"),
            **env,
        },
    )


def invocations(run_dir: Path) -> list[list[str]]:
    raw = (run_dir / "calls.log").read_bytes()
    if not raw:
        return []
    return [chunk.decode().split("\0")[:-1] for chunk in raw.split(b"\0\0") if chunk]


def client_lookup_calls(run_dir: Path) -> list[list[str]]:
    return [inv for inv in invocations(run_dir) if "list-user-pool-clients" in inv]


def s3_sync_calls(run_dir: Path) -> list[list[str]]:
    return [inv for inv in invocations(run_dir) if "s3" in inv and "sync" in inv]


def baked_client_id(run_dir: Path) -> str:
    env_file = run_dir / "frontend" / ".env.production"
    for line in env_file.read_text().splitlines():
        if line.startswith("VITE_COGNITO_USER_POOL_CLIENT_ID="):
            return line.split("=", 1)[1].strip()
    return ""


class TestAppClientResolution:
    def test_fallback_resolves_the_web_client_by_name(self, run_dir: Path) -> None:
        result = run_deploy(run_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert baked_client_id(run_dir) == WEB_CLIENT_ID

        lookups = client_lookup_calls(run_dir)
        assert len(lookups) == 1, f"expected one client lookup, got {lookups}"
        assert any("ClientName==`KernelWorx-Web`" in arg for arg in lookups[0])

    def test_the_positional_guess_is_never_issued(self, run_dir: Path) -> None:
        run_deploy(run_dir)

        for invocation in invocations(run_dir):
            joined = " ".join(invocation)
            assert "UserPoolClients[0].ClientId" not in joined, (
                f"the removed positional guess is back: {invocation}"
            )
            if "list-user-pool-clients" in invocation:
                assert "--max-results" not in invocation, (
                    f"the removed --max-results guess is back: {invocation}"
                )

    def test_unresolvable_web_client_fails_loudly_without_guessing(
        self, run_dir: Path
    ) -> None:
        """No KernelWorx-Web client in the pool stops the deploy instead of
        picking an arbitrary one.

        The mock answers the removed ``UserPoolClients[0].ClientId`` query with a
        usable-looking first-client id, so the script can only fail here by
        declining to ask for it.
        """
        result = run_deploy(run_dir, WEB_CLIENT_PRESENT="0")

        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "KernelWorx-Web" in output
        assert POOL_ID in output
        # Never reached the upload: the deploy stopped at validation.
        assert not s3_sync_calls(run_dir), "the deploy uploaded despite no client"
        for invocation in invocations(run_dir):
            assert "UserPoolClients[0].ClientId" not in " ".join(invocation)


class TestStaticAssetUpload:
    def test_s3_sync_does_not_delete_prior_assets(self, run_dir: Path) -> None:
        result = run_deploy(run_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        syncs = s3_sync_calls(run_dir)
        assert len(syncs) == 1, f"expected one s3 sync, got {syncs}"
        assert "--delete" not in syncs[0], (
            f"the destructive --delete is back: {syncs[0]}"
        )
