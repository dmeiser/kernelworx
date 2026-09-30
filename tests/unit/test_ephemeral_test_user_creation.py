"""Error reporting in the ephemeral test-user creation path.

`scripts/create-ephemeral-test-users.sh` (called by `scripts/ephemeral-env.sh`)
sent the output of `cognito-idp admin-create-user` to /dev/null and logged
"(User may already exist)" for *any* failure. A signup that failed for any other
reason - a quota, a bad attribute, a network error - was therefore reported as
"may already exist", the script continued, and `admin-set-user-password` then
retried five times against a user that had never been created. That is what an
ephemeral run on PR 628 printed: the real signup error was invisible and the
only visible failure was five identical `UserNotFoundException` password
attempts.

The contract these tests pin down:

- a user-creation failure other than `UsernameExistsException` aborts the run
  and prints the error Cognito actually returned;
- `UsernameExistsException` is the only "already exists" case, and it proceeds
  to the password step;
- a password step that fails because the user does not exist reports that
  directly instead of repeating the same impossible call;
- the same reporting applies to the owner user.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

RUN_ID = "pr-628"
POOL_ID = "us-east-1_ExamplePool"
CLIENT_ID = "1example23client45id6789"
OWNER_EMAIL = f"{RUN_ID}-owner@kernelworx.test"
CONTRIBUTOR_EMAIL = f"{RUN_ID}-contributor@kernelworx.test"
READONLY_EMAIL = f"{RUN_ID}-readonly@kernelworx.test"
# The TOTP secret the stubbed provisioning helper prints.
TOTP_SECRET = "JBSWY3DPEHPK3PXP"

# The aws CLI reports a Cognito exception as
#   aws: [ERROR]: An error occurred (<Code>) when calling the <Op> operation: <message>
# and exits non-zero, which is exactly what the mock reproduces.
MOCK_AWS = """\
#!/bin/bash
op="$1 $2"
printf '%s\\n' "$op" >> "$MOCK_AWS_LOG"

# The email the operation targets, so a failure can be aimed at one user.
username=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--username" ]; then username="$arg"; fi
  prev="$arg"
done

fail() {
  if [ "$username" = "$1" ] && [ -n "$2" ]; then
    echo "aws: [ERROR]: An error occurred ($2) when calling the $3 operation: $4" >&2
    exit 254
  fi
}

case "$op" in
  "cognito-idp admin-create-user")
    fail "${MOCK_AWS_CREATE_ERROR_USERNAME:-}" "${MOCK_AWS_CREATE_ERROR_CODE:-}" \\
      "AdminCreateUser" "${MOCK_AWS_CREATE_ERROR_MESSAGE:-simulated failure}"
    ;;
  "cognito-idp admin-set-user-password")
    fail "${MOCK_AWS_PASSWORD_ERROR_USERNAME:-}" "${MOCK_AWS_PASSWORD_ERROR_CODE:-}" \\
      "AdminSetUserPassword" "${MOCK_AWS_PASSWORD_ERROR_MESSAGE:-User does not exist.}"
    ;;
esac
exit 0
"""

# The user creation path calls the TOTP helper at the end; these tests are about
# the creation calls, so the helper is stubbed to print a fixed secret.
TOTP_STUB = """\
#!/bin/bash
echo "provisioning TOTP for $3" >&2
echo "__TOTP_SECRET__"
"""


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def harness(tmp_path: Path, repo_root: Path) -> dict[str, object]:
    """A copy of scripts/ whose aws CLI and TOTP helper are mocked."""
    scripts_dir = tmp_path / "scripts"
    shutil.copytree(repo_root / "scripts", scripts_dir, ignore=shutil.ignore_patterns("__pycache__"))

    totp_stub = scripts_dir / "provision-user-totp.sh"
    totp_stub.write_text(TOTP_STUB.replace("__TOTP_SECRET__", TOTP_SECRET))
    totp_stub.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_aws = bin_dir / "aws"
    mock_aws.write_text(MOCK_AWS)
    mock_aws.chmod(0o755)
    # Keep the password-set backoff from sleeping for real.
    no_sleep = bin_dir / "sleep"
    no_sleep.write_text("#!/bin/bash\nexit 0\n")
    no_sleep.chmod(0o755)

    return {"scripts_dir": scripts_dir, "bin_dir": bin_dir, "log": tmp_path / "aws.log"}


def run_script(harness: dict[str, object], **env: str) -> subprocess.CompletedProcess[str]:
    """Run the script the way scripts/ephemeral-env.sh does."""
    log = harness["log"]  # type: ignore[index]
    log.write_text("")
    return subprocess.run(
        [
            "bash",
            str(harness["scripts_dir"] / "create-ephemeral-test-users.sh"),  # type: ignore[index]
            RUN_ID,
            POOL_ID,
            CLIENT_ID,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{harness['bin_dir']}{os.pathsep}{os.environ['PATH']}",  # type: ignore[index]
            "AWS_REGION": "us-east-1",
            "MOCK_AWS_LOG": str(log),
            **env,
        },
    )


def operations(harness: dict[str, object]) -> list[str]:
    log: Path = harness["log"]  # type: ignore[assignment]
    return [line for line in log.read_text().splitlines() if line]


def count(harness: dict[str, object], operation: str) -> int:
    return operations(harness).count(operation)


def exported_credentials(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith("export ")]


class TestCreateUserFailureIsReported:
    """A signup failure other than UsernameExistsException must abort loudly."""

    def test_owner_creation_failure_aborts_and_prints_the_real_error(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_CREATE_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_CREATE_ERROR_CODE="LimitExceededException",
            MOCK_AWS_CREATE_ERROR_MESSAGE="Daily message quota for this user pool has been exceeded.",
        )

        assert result.returncode != 0, result.stderr
        assert "LimitExceededException" in result.stderr
        assert "Daily message quota for this user pool has been exceeded." in result.stderr
        assert "may already exist" not in result.stderr

    def test_contributor_creation_failure_is_not_reported_as_already_existing(self, harness: dict[str, object]) -> None:
        """The PR 628 case: the owner succeeded, the contributor signup failed."""
        result = run_script(
            harness,
            MOCK_AWS_CREATE_ERROR_USERNAME=CONTRIBUTOR_EMAIL,
            MOCK_AWS_CREATE_ERROR_CODE="InvalidParameterException",
            MOCK_AWS_CREATE_ERROR_MESSAGE="Email address is not verified.",
        )

        assert result.returncode != 0, result.stderr
        assert "Setting up Owner user" in result.stderr
        assert "InvalidParameterException" in result.stderr
        assert CONTRIBUTOR_EMAIL in result.stderr
        assert "may already exist" not in result.stderr
        # Aborted at the failure: the remaining users were never attempted.
        assert "Setting up Read-only user" not in result.stderr

    def test_no_password_attempt_after_a_creation_failure(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_CREATE_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_CREATE_ERROR_CODE="LimitExceededException",
            MOCK_AWS_CREATE_ERROR_MESSAGE="Daily message quota for this user pool has been exceeded.",
        )

        assert result.returncode != 0, result.stderr
        assert count(harness, "cognito-idp admin-set-user-password") == 0
        assert not exported_credentials(result)


class TestUsernameExistsContinues:
    """UsernameExistsException is the only legitimate 'already exists' case."""

    def test_existing_user_continues_to_the_password_step(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_CREATE_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_CREATE_ERROR_CODE="UsernameExistsException",
            MOCK_AWS_CREATE_ERROR_MESSAGE="User account already exists",
        )

        assert result.returncode == 0, result.stderr
        assert "already exists" in result.stderr
        assert "ERROR:" not in result.stderr
        assert count(harness, "cognito-idp admin-set-user-password") == 4
        exports = exported_credentials(result)
        assert len(exports) == 9, exports
        assert f"export TEST_OWNER_EMAIL={OWNER_EMAIL}" in exports
        assert f"export TEST_OWNER_TOTP_SECRET={TOTP_SECRET}" in exports


class TestPasswordStepFailure:
    def test_missing_user_fails_immediately_instead_of_retrying(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_PASSWORD_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_PASSWORD_ERROR_CODE="UserNotFoundException",
            MOCK_AWS_PASSWORD_ERROR_MESSAGE="User does not exist.",
        )

        assert result.returncode != 0, result.stderr
        assert "UserNotFoundException" in result.stderr
        assert "no user" in result.stderr
        # One doomed call, not five identical ones.
        assert count(harness, "cognito-idp admin-set-user-password") == 1
        assert "Attempt 1/5" not in result.stderr
        assert not exported_credentials(result)

    def test_transient_password_failure_still_retries(self, harness: dict[str, object]) -> None:
        """A retryable error keeps the existing backoff behavior."""
        result = run_script(
            harness,
            MOCK_AWS_PASSWORD_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_PASSWORD_ERROR_CODE="TooManyRequestsException",
            MOCK_AWS_PASSWORD_ERROR_MESSAGE="Rate exceeded",
        )

        assert result.returncode != 0, result.stderr
        assert count(harness, "cognito-idp admin-set-user-password") == 5
        assert "Attempt 5/5" in result.stderr
        assert "Refusing to export test credentials" in result.stderr
        assert not exported_credentials(result)


class TestErrorCodesMatchWholeCliCodes:
    """The branch codes must match the whole CLI error code, not a substring.

    The aws CLI frames every failure as
      An error occurred (<Code>) when calling the <Operation> operation: <message>
    so an unrelated error whose message merely *mentions*
    UsernameExistsException or UserNotFoundException must not be classified as
    that code: a create failure would be misread as "already exists" and a
    retryable password failure as "no such user".
    """

    def test_create_failure_message_mentioning_username_exists_still_aborts(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_CREATE_ERROR_USERNAME=CONTRIBUTOR_EMAIL,
            MOCK_AWS_CREATE_ERROR_CODE="InvalidParameterException",
            MOCK_AWS_CREATE_ERROR_MESSAGE="Malformed attribute (UsernameExistsException) hint in request.",
        )

        assert result.returncode != 0, result.stderr
        assert "InvalidParameterException" in result.stderr
        assert "User already exists" not in result.stderr
        assert "may already exist" not in result.stderr

    def test_password_failure_message_mentioning_user_not_found_still_retries(self, harness: dict[str, object]) -> None:
        result = run_script(
            harness,
            MOCK_AWS_PASSWORD_ERROR_USERNAME=OWNER_EMAIL,
            MOCK_AWS_PASSWORD_ERROR_CODE="TooManyRequestsException",
            MOCK_AWS_PASSWORD_ERROR_MESSAGE="Rate exceeded; cached (UserNotFoundException) verdict replayed.",
        )

        assert result.returncode != 0, result.stderr
        assert "no user" not in result.stderr
        assert count(harness, "cognito-idp admin-set-user-password") == 5
        assert "Attempt 5/5" in result.stderr


def test_script_is_shellcheck_clean(repo_root: Path) -> None:
    """The new error branching must not introduce shell lint findings."""
    result = subprocess.run(
        ["shellcheck", str(repo_root / "scripts" / "create-ephemeral-test-users.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 127:  # pragma: no cover - shellcheck is optional locally
        pytest.skip("shellcheck is not installed")

    assert result.returncode == 0, textwrap.indent(result.stdout + result.stderr, "  ")
