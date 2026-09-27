"""Regression tests for #569: the test user's password must not appear on argv.

`scripts/provision-user-totp.sh` used to pass the password inline in
`--auth-parameters`, which puts it in the argv of the `aws` CLI process. argv of
a running process is world-readable on Linux (`/proc/<pid>/cmdline`) and visible
in `ps` for the duration of the call, so any co-tenant process on the runner
could read the credential. The script now writes the auth parameters to a
private `mktemp` file and passes them with `--cli-input-json file://...`.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

PASSWORD = "Sup3rSecret-Passw0rd,with#delimiters"
USERNAME = "owner@example.com"
POOL_ID = "us-east-1_ExamplePool"
CLIENT_ID = "1example23client45id6789"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"

MOCK_AWS = """\
#!/bin/bash
# Record every argument exactly as the process received it.
printf '%s\\0' "$@" >> "$MOCK_AWS_LOG"
printf '\\0' >> "$MOCK_AWS_LOG"

sub="$1 $2"
case "$sub" in
  "cognito-idp admin-get-user")
    # No existing TOTP device.
    echo "None"
    ;;
  "cognito-idp initiate-auth")
    if [ "${FAIL_USER_PASSWORD_AUTH:-0}" = "1" ]; then
      echo "simulated USER_PASSWORD_AUTH failure" >&2
      exit 254
    fi
    echo "user.password.access.token"
    ;;
  "cognito-idp admin-initiate-auth")
    echo "admin.no.srp.access.token"
    ;;
  "cognito-idp associate-software-token")
    echo "$MOCK_TOTP_SECRET"
    ;;
  *)
    # verify-software-token / admin-set-user-mfa-preference: nothing to do.
    ;;
esac
"""


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Run provision-user-totp.sh against a recording fake `aws` CLI."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "aws-argv.log"
    log_file.touch()

    def write_mock_bin(name: str, script: str) -> None:
        path = bin_dir / name
        path.write_text(textwrap.dedent(script).strip() + "\n")
        path.chmod(0o755)

    write_mock_bin("aws", MOCK_AWS)
    # The script sleeps for the TOTP window to roll over; skip that wait.
    write_mock_bin("sleep", "#!/bin/bash\nexit 0\n")
    write_mock_bin("date", "#!/bin/bash\necho 0\n")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("MOCK_AWS_LOG", str(log_file))
    monkeypatch.setenv("MOCK_TOTP_SECRET", TOTP_SECRET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    return {"bin_dir": bin_dir, "log_file": log_file}


def run_script(harness: dict[str, Path], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "provision-user-totp.sh"),
            POOL_ID,
            CLIENT_ID,
            USERNAME,
            PASSWORD,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{harness['bin_dir']}{os.pathsep}{os.environ['PATH']}"},
    )


def aws_invocations(harness: dict[str, Path]) -> list[list[str]]:
    raw = harness["log_file"].read_bytes()
    if not raw:
        return []
    return [chunk.decode().split("\0")[:-1] for chunk in raw.split(b"\0\0") if chunk]


def params_files(harness: dict[str, Path]) -> list[Path]:
    """Every `file://` path the fake `aws` was pointed at."""
    paths = []
    for invocation in aws_invocations(harness):
        for arg in invocation:
            if arg.startswith("file://"):
                paths.append(Path(arg[len("file://") :]))
    return paths


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class TestPasswordNeverOnArgv:
    """#569: the password must not reach any process's command line."""

    def test_password_absent_from_every_aws_argv(self, harness: dict[str, Path], repo_root: Path) -> None:
        result = run_script(harness, repo_root)

        assert result.returncode == 0, result.stderr
        invocations = aws_invocations(harness)
        assert invocations, "the fake aws CLI was never invoked"
        for invocation in invocations:
            for arg in invocation:
                assert PASSWORD not in arg, f"password leaked on argv: {invocation}"

    def test_no_inline_auth_parameters_argument(self, harness: dict[str, Path], repo_root: Path) -> None:
        """The old `--auth-parameters USERNAME=..,PASSWORD=..` shape is gone."""
        run_script(harness, repo_root)

        for invocation in aws_invocations(harness):
            assert "--auth-parameters" not in invocation
            assert "PASSWORD" not in " ".join(invocation)

    def test_password_absent_from_admin_fallback_argv(
        self, harness: dict[str, Path], repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ADMIN_NO_SRP_AUTH fallback is the second exposure window (#569)."""
        monkeypatch.setenv("FAIL_USER_PASSWORD_AUTH", "1")
        result = run_script(harness, repo_root)

        assert result.returncode == 0, result.stderr
        flows = " ".join(" ".join(i) for i in aws_invocations(harness))
        assert "ADMIN_NO_SRP_AUTH" in flows
        for invocation in aws_invocations(harness):
            for arg in invocation:
                assert PASSWORD not in arg, f"password leaked on argv: {invocation}"


class TestAuthParametersFile:
    def test_parameters_passed_through_a_private_file(
        self, harness: dict[str, Path], repo_root: Path
    ) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        files = params_files(harness)
        assert files, "no --cli-input-json file:// parameter file was used"
        for path in files:
            # Written by the script before the call, so it is inspectable here
            # only because the fake aws CLI does not delete it.
            assert json.loads(path.read_text())["AuthParameters"] == {
                "USERNAME": USERNAME,
                "PASSWORD": PASSWORD,
            }

    def test_parameter_file_is_owner_only_readable(self, harness: dict[str, Path], repo_root: Path) -> None:
        """mktemp already creates 0600; the script must not widen it."""
        recording_aws = harness["bin_dir"] / "aws"
        original = recording_aws.read_text()
        recording_aws.write_text(
            original.replace(
                'printf \'%s\\0\' "$@" >> "$MOCK_AWS_LOG"',
                'printf \'%s\\0\' "$@" >> "$MOCK_AWS_LOG"\n'
                'for a in "$@"; do case "$a" in file://*) '
                'stat -c "%a %n" "${a#file://}" >> "$MOCK_AWS_MODES";; esac; done',
            )
        )
        harness["log_file"].touch()
        modes_file = harness["log_file"].with_name("modes.log")
        modes_file.touch()
        os.environ["MOCK_AWS_MODES"] = str(modes_file)
        try:
            result = run_script(harness, repo_root)
        finally:
            os.environ.pop("MOCK_AWS_MODES", None)

        assert result.returncode == 0, result.stderr
        recorded = modes_file.read_text().strip().splitlines()
        assert recorded, "the parameter file mode was not recorded"
        modes = {line.split()[0] for line in recorded}
        assert modes == {oct(stat.S_IRUSR | stat.S_IWUSR)[2:]}

    def test_parameter_file_removed_on_success(self, harness: dict[str, Path], repo_root: Path) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        files = params_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file outlived the script: {path}"

    def test_parameter_file_removed_on_failure(self, harness: dict[str, Path], repo_root: Path) -> None:
        """A failed run must not leave the password on disk (trap on EXIT)."""
        broken = harness["bin_dir"] / "aws"
        broken.write_text("#!/bin/bash\nexit 1\n")
        broken.chmod(0o755)
        harness["log_file"].unlink()
        harness["log_file"].touch()
        os.environ["MOCK_AWS_LOG"] = str(harness["log_file"])
        # Record the file path even though the call itself "fails".
        broken.write_text(
            "#!/bin/bash\n"
            'printf \'%s\\0\' "$@" >> "$MOCK_AWS_LOG"\n'
            'printf \'\\0\' >> "$MOCK_AWS_LOG"\n'
            "exit 1\n"
        )

        result = run_script(harness, repo_root)

        assert result.returncode != 0
        files = params_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file survived a failed run: {path}"


def test_still_prints_the_totp_secret(harness: dict[str, Path], repo_root: Path) -> None:
    """The behaviour the callers depend on is unchanged by #569."""
    result = run_script(harness, repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == TOTP_SECRET
