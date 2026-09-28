"""Regression tests for #567: the deploy smoke test must never guess the app client.

The "Ensure owner test user has TOTP MFA" step used to resolve the Cognito app
client in three tiers, the last one being `list-user-pool-clients
--max-results 1`. That returns the first client in pool order, which is a
separately created, non-tofu-managed client that lacks
`ALLOW_USER_PASSWORD_AUTH`, so provisioning fails with
`InvalidParameterException: USER_PASSWORD_AUTH flow not enabled for this client`
(deploy run 34775015216) - an error that points at Cognito configuration rather
than at the bad fallback in the workflow.

The step must instead use the deploy output
(`module.cognito.client_id` = the `KernelWorx-Web` client), fall back only to a
name lookup of that same client, and then fail loudly with a `::error::`
annotation naming the pool.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"
STEP_NAME = "Ensure owner test user has TOTP MFA"

POOL_ID = "us-east-1_ExamplePool"
WEB_CLIENT_ID = "1webclient2345678"
# The pool's first client in list order: separately created, not tofu-managed,
# and the id the removed --max-results 1 fallback would have picked.
FIRST_CLIENT_ID = "1firstclient23456"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"

# The step's only GitHub expression; the test substitutes it per scenario.
CLIENT_ID_EXPRESSION = "${{ needs.deploy.outputs.client_id }}"


def _step_run_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    matches = [s for s in steps if s.get("name") == STEP_NAME]
    assert len(matches) == 1, f"expected exactly one '{STEP_NAME}' step, found {len(matches)}"
    return str(matches[0]["run"])


# The mock records the exact query each call sent so a test can assert which
# client id resolution path the step took.
MOCK_AWS = """\
#!/bin/bash
printf '%s\\0' "$@" >> "$MOCK_AWS_LOG"
printf '\\0' >> "$MOCK_AWS_LOG"
case "$*" in
  *'ClientName==`KernelWorx-Web`'*)
    [ "${WEB_CLIENT_PRESENT:-1}" = "1" ] || exit 0
    echo "__WEB_CLIENT_ID__"
    ;;
  *"UserPoolClients[0].ClientId"*)
    echo "__FIRST_CLIENT_ID__"
    ;;
esac
""".replace("__WEB_CLIENT_ID__", WEB_CLIENT_ID).replace("__FIRST_CLIENT_ID__", FIRST_CLIENT_ID)

# The step calls the real provisioning script; stub it so the test observes
# only the client-resolution decision.
STUB_PROVISION = """\
#!/bin/bash
printf '%s\\0' "$@" >> "$MOCK_PROVISION_LOG"
printf '\\0' >> "$MOCK_PROVISION_LOG"
echo "$STUB_TOTP_SECRET"
"""


@dataclass(frozen=True)
class Step:
    """The workflow step, materialized as a runnable script in a temp dir."""

    script: str
    bin_dir: Path
    logs: dict[str, Path]


@pytest.fixture
def step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Step:
    """Materialize the workflow step as a runnable script in a temp dir."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    provision = scripts_dir / "provision-user-totp.sh"
    provision.write_text(STUB_PROVISION)
    provision.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(MOCK_AWS)
    aws.chmod(0o755)

    logs = {name: tmp_path / f"{name}.log" for name in ("aws", "provision")}
    for path in logs.values():
        path.touch()

    monkeypatch.setenv("MOCK_AWS_LOG", str(logs["aws"]))
    monkeypatch.setenv("MOCK_PROVISION_LOG", str(logs["provision"]))
    monkeypatch.setenv("STUB_TOTP_SECRET", TOTP_SECRET)
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github_env"))
    return Step(script=_step_run_script(), bin_dir=bin_dir, logs=logs)


def run_step(step: Step, tmp_path: Path, client_id: str, **env: str) -> subprocess.CompletedProcess[str]:
    script = step.script.replace(CLIENT_ID_EXPRESSION, client_id)
    assert CLIENT_ID_EXPRESSION not in script
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{step.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "TEST_OWNER_EMAIL": "owner@example.com",
            "TEST_OWNER_PASSWORD": "Sup3rSecret-Pa55word",
            "TEST_USER_POOL_ID": POOL_ID,
            "AWS_REGION": "us-east-1",
            **env,
        },
    )


def invocations(step: Step, which: str = "aws") -> list[list[str]]:
    raw = step.logs[which].read_bytes()
    if not raw:
        return []
    return [chunk.decode().split("\0")[:-1] for chunk in raw.split(b"\0\0") if chunk]


def provisioned_client_id(step: Step) -> str:
    """The client id the step handed to provision-user-totp.sh ($2)."""
    calls = invocations(step, "provision")
    assert len(calls) == 1, f"expected one provisioning call, got {calls}"
    return calls[0][1]


class TestClientResolution:
    def test_deploy_output_is_used_without_any_lookup(self, step: Step, tmp_path: Path) -> None:
        result = run_step(step, tmp_path, WEB_CLIENT_ID)

        assert result.returncode == 0, result.stderr
        assert provisioned_client_id(step) == WEB_CLIENT_ID
        assert invocations(step) == [], "the deploy output was available; no lookup was needed"

    def test_name_lookup_resolves_the_web_client(self, step: Step, tmp_path: Path) -> None:
        result = run_step(step, tmp_path, "")

        assert result.returncode == 0, result.stderr
        assert provisioned_client_id(step) == WEB_CLIENT_ID
        assert len(invocations(step)) == 1

    def test_empty_string_deploy_output_falls_back_to_the_name_lookup(self, step: Step, tmp_path: Path) -> None:
        assert run_step(step, tmp_path, "None").returncode == 0

        assert provisioned_client_id(step) == WEB_CLIENT_ID


def test_unresolvable_client_fails_loudly_without_guessing(step: Step, tmp_path: Path) -> None:
    """#567: no web client in the pool stops the step instead of picking one.

    The mock answers the removed `list-user-pool-clients --max-results 1`
    query with a usable-looking first-client id, so the step can only fail
    here by declining to ask for it.
    """
    result = run_step(step, tmp_path, "", WEB_CLIENT_PRESENT="0")

    assert result.returncode != 0, result.stderr
    assert "::error::" in result.stderr
    assert POOL_ID in result.stderr
    assert "KernelWorx-Web" in result.stderr
    assert not invocations(step, "provision"), "the step provisioned against an arbitrary client"
    for invocation in invocations(step):
        assert "--max-results" not in invocation, f"the removed guess is back: {invocation}"
        assert "UserPoolClients[0].ClientId" not in " ".join(invocation)
