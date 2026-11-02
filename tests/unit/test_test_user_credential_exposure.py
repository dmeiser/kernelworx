"""Regression tests for #710: the test-user provisioning scripts must not put a
password on a command line or print one to stdout.

`scripts/create-test-users.sh`, `scripts/create-screenshot-user.sh`, and
`scripts/create-ephemeral-test-users.sh` passed `--temporary-password` /
`--password` inline on the `aws cognito-idp` command line, and the first two also
echoed the plaintext passwords at the end of the run. A running process's argv is
world-readable on Linux (`/proc/<pid>/cmdline`) and visible in `ps` for the
duration of the call, so any co-tenant on the runner could read the credential,
and the echoed passwords landed in terminal scrollback and CI logs.

The scripts now follow the shape `scripts/provision-user-totp.sh` already used
(#569/#597): the credential rides in a `chmod 600` `mktemp` file passed with
`--cli-input-json file://...` and removed by an `EXIT` trap on every exit path.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

# Deliberately carries a comma and a double quote: the comma is what broke the
# old flat inline parameter lists, and the quote has to survive JSON encoding.
PASSWORD = 'Sup3r,Secret"Pa55'
EMAILS = {
    "TEST_OWNER_EMAIL": "owner@kernelworx.test",
    "TEST_CONTRIBUTOR_EMAIL": "contributor@kernelworx.test",
    "TEST_READONLY_EMAIL": "readonly@kernelworx.test",
    "TEST_SMOKE_EMAIL": "smoke@kernelworx.test",
    "TEST_ALEX_EMAIL": "alex.kernel@kernelworx.test",
}
POOL_ID = "us-east-1_ExamplePool"
CLIENT_ID = "1example23client45id6789"
RUN_ID = "pr-710"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"

MOCK_AWS = """\
#!/bin/bash
# Record every argument exactly as the process received it, and snapshot the
# contents and mode of any file:// parameter file while it still exists.
printf '%s\\0' "$@" >> "$MOCK_AWS_LOG"
printf '\\0' >> "$MOCK_AWS_LOG"
for arg in "$@"; do
  case "$arg" in
    file://*)
      path="${arg#file://}"
      python3 -c 'import os,stat,sys;print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])' \\
        "$path" >> "$MOCK_AWS_MODES"
      printf '%s\\n' "$arg" >> "$MOCK_AWS_PARAM_FILES"
      cat "$path" >> "$MOCK_AWS_PARAM_CONTENTS"
      printf '\\036' >> "$MOCK_AWS_PARAM_CONTENTS"
      ;;
  esac
done
case "$1 $2" in
  "cognito-idp admin-create-user")
    if [ -n "${MOCK_AWS_CREATE_ERROR_CODE:-}" ]; then
      echo "aws: [ERROR]: An error occurred ($MOCK_AWS_CREATE_ERROR_CODE) when calling the AdminCreateUser operation: simulated" >&2
      exit 254
    fi
    ;;
  "cognito-idp admin-get-user") echo "None" ;;
  "cognito-idp initiate-auth") echo "an-access-token" ;;
  "cognito-idp associate-software-token") echo "$MOCK_TOTP_SECRET" ;;
esac
exit 0
"""

# The dev script provisions the owner's TOTP device through the real helper;
# these tests are about the create/password calls, so the helper is stubbed.
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
    """A copy of scripts/ with a mocked aws CLI, a stubbed TOTP helper, and a .env."""
    scripts_dir = tmp_path / "scripts"
    shutil.copytree(repo_root / "scripts", scripts_dir, ignore=shutil.ignore_patterns("__pycache__"))
    totp_stub = scripts_dir / "provision-user-totp.sh"
    totp_stub.write_text(TOTP_STUB.replace("__TOTP_SECRET__", TOTP_SECRET))
    totp_stub.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", MOCK_AWS), ("sleep", "#!/bin/bash\nexit 0\n")):
        path = bin_dir / name
        path.write_text(textwrap.dedent(body).strip() + "\n")
        path.chmod(0o755)

    logs = {
        name: tmp_path / f"{name}.log" for name in ("aws_argv", "aws_modes", "aws_param_files", "aws_param_contents")
    }
    for path in logs.values():
        path.touch()

    # Single-quoted so the comma and double quote survive sourcing.
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                f"TEST_USER_POOL_ID={POOL_ID}",
                f"TEST_USER_POOL_CLIENT_ID={CLIENT_ID}",
                "TEST_REGION=us-east-1",
                *[f"{key}={value}" for key, value in EMAILS.items()],
                *(
                    f"{name}='{PASSWORD}'"
                    for name in (
                        "TEST_OWNER_PASSWORD",
                        "TEST_CONTRIBUTOR_PASSWORD",
                        "TEST_READONLY_PASSWORD",
                        "TEST_SMOKE_PASSWORD",
                        "TEST_ALEX_PASSWORD",
                    )
                ),
                "",
            ]
        )
    )
    return {"scripts_dir": scripts_dir, "bin_dir": bin_dir, "logs": logs, "cwd": tmp_path}


def run_script(
    harness: dict[str, object], script: str, args: list[str] | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run one of the provisioning scripts the way its real caller does."""
    return subprocess.run(
        ["bash", str(Path(harness["scripts_dir"]) / script), *(args or [])],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
        check=False,
        cwd=str(harness["cwd"]),  # type: ignore[arg-type]
        env={
            **os.environ,
            "PATH": f"{harness['bin_dir']}{os.pathsep}{os.environ['PATH']}",  # type: ignore[str-format]
            "AWS_REGION": "us-east-1",
            "MOCK_AWS_LOG": str(harness["logs"]["aws_argv"]),  # type: ignore[index]
            "MOCK_AWS_MODES": str(harness["logs"]["aws_modes"]),  # type: ignore[index]
            "MOCK_AWS_PARAM_FILES": str(harness["logs"]["aws_param_files"]),  # type: ignore[index]
            "MOCK_AWS_PARAM_CONTENTS": str(harness["logs"]["aws_param_contents"]),  # type: ignore[index]
            "MOCK_TOTP_SECRET": TOTP_SECRET,
            **env,
        },
    )


def run_ephemeral(harness: dict[str, object], **env: str) -> subprocess.CompletedProcess[str]:
    return run_script(harness, "create-ephemeral-test-users.sh", [RUN_ID, POOL_ID, CLIENT_ID], **env)


def logs(harness: dict[str, object]) -> dict[str, Path]:
    return harness["logs"]  # type: ignore[return-value]


def all_argv(harness: dict[str, object]) -> list[str]:
    raw = logs(harness)["aws_argv"].read_bytes()
    if not raw:
        return []
    return [arg for chunk in raw.split(b"\0\0") if chunk for arg in chunk.decode().split("\0")[:-1]]


def param_files(harness: dict[str, object]) -> list[Path]:
    text = logs(harness)["aws_param_files"].read_text()
    return [Path(line[len("file://") :]) for line in text.splitlines() if line.startswith("file://")]


def credential_chunks(harness: dict[str, object]) -> list[dict]:
    raw = logs(harness)["aws_param_contents"].read_text()
    return [
        chunk
        for chunk in (json.loads(part) for part in raw.split("\x1e") if part.strip())
        if "Password" in chunk or "TemporaryPassword" in chunk
    ]


def exported(result: subprocess.CompletedProcess[str], name: str) -> str:
    prefix = f"export {name}="
    return next((line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)), "")


class TestPasswordNeverOnArgv:
    @pytest.mark.parametrize("script", ["create-test-users.sh", "create-screenshot-user.sh"])
    def test_env_password_absent_from_every_aws_argv(self, harness: dict[str, object], script: str) -> None:
        result = run_script(harness, script)

        assert result.returncode == 0, result.stderr
        assert all_argv(harness), "the fake aws CLI was never invoked"
        for arg in all_argv(harness):
            assert PASSWORD not in arg, f"credential leaked on argv: {arg!r}"

    def test_generated_ephemeral_passwords_absent_from_every_aws_argv(self, harness: dict[str, object]) -> None:
        """The ephemeral passwords are generated, so read them back from the
        export block and confirm none of them reached a command line."""
        result = run_ephemeral(harness)

        assert result.returncode == 0, result.stderr
        generated = [
            exported(result, name)
            for name in (
                "TEST_OWNER_PASSWORD",
                "TEST_CONTRIBUTOR_PASSWORD",
                "TEST_READONLY_PASSWORD",
                "TEST_SMOKE_PASSWORD",
            )
        ]
        assert all(generated), f"expected all four passwords to be exported: {result.stdout}"
        argv = all_argv(harness)
        assert argv, "the fake aws CLI was never invoked"
        for password in generated:
            for arg in argv:
                assert password not in arg, f"generated credential leaked on argv: {arg!r}"


class TestCredentialRidesInAPrivateFile:
    @pytest.mark.parametrize("script", ["create-test-users.sh", "create-screenshot-user.sh"])
    def test_both_credential_calls_use_a_parameter_file(self, harness: dict[str, object], script: str) -> None:
        result = run_script(harness, script)

        assert result.returncode == 0, result.stderr
        chunks = credential_chunks(harness)
        assert {"TemporaryPassword": PASSWORD} in chunks, chunks
        assert {"Password": PASSWORD} in chunks, chunks

    def test_ephemeral_credential_calls_use_a_parameter_file(self, harness: dict[str, object]) -> None:
        result = run_ephemeral(harness)

        assert result.returncode == 0, result.stderr
        generated = {
            exported(result, name)
            for name in (
                "TEST_OWNER_PASSWORD",
                "TEST_CONTRIBUTOR_PASSWORD",
                "TEST_READONLY_PASSWORD",
                "TEST_SMOKE_PASSWORD",
            )
        }
        chunks = credential_chunks(harness)
        # One TemporaryPassword plus one Password per user, each carrying the
        # password generated for that user.
        assert len(chunks) == 8, chunks
        for chunk in chunks:
            assert chunk.get("Password", chunk.get("TemporaryPassword")) in generated, chunk

    def test_parameter_file_is_owner_only_readable(self, harness: dict[str, object]) -> None:
        """mktemp already creates 0600; the scripts must not widen it."""
        result = run_ephemeral(harness)
        assert result.returncode == 0, result.stderr

        modes = logs(harness)["aws_modes"].read_text().split()
        assert modes, "the parameter file mode was not recorded"
        assert set(modes) == {oct(stat.S_IRUSR | stat.S_IWUSR)[2:]}

    def test_parameter_file_removed_after_success(self, harness: dict[str, object]) -> None:
        result = run_ephemeral(harness)
        assert result.returncode == 0, result.stderr

        files = param_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file outlived the script: {path}"

    def test_parameter_file_removed_after_failure(self, harness: dict[str, object]) -> None:
        """The EXIT trap must fire on the abort paths, not only on success."""
        result = run_ephemeral(harness, MOCK_AWS_CREATE_ERROR_CODE="LimitExceededException")

        assert result.returncode != 0
        files = param_files(harness)
        assert files, "the run never reached a credential-carrying call, so nothing was checked"
        for path in files:
            assert not path.exists(), f"parameter file survived a failed run: {path}"


class TestPlaintextNoLongerPrinted:
    @pytest.mark.parametrize(
        ("script", "email_keys"),
        [
            (
                "create-test-users.sh",
                ["TEST_OWNER_EMAIL", "TEST_CONTRIBUTOR_EMAIL", "TEST_READONLY_EMAIL", "TEST_SMOKE_EMAIL"],
            ),
            ("create-screenshot-user.sh", ["TEST_ALEX_EMAIL"]),
        ],
    )
    def test_password_not_printed_but_users_still_listed(
        self, harness: dict[str, object], script: str, email_keys: list[str]
    ) -> None:
        result = run_script(harness, script)

        assert result.returncode == 0, result.stderr
        assert PASSWORD not in result.stdout
        assert PASSWORD not in result.stderr
        for key in email_keys:
            assert EMAILS[key] in result.stdout, f"{script} stopped identifying the {key} user"

    def test_ephemeral_still_exports_credentials_to_its_caller(self, harness: dict[str, object]) -> None:
        """scripts/ephemeral-env.sh pipes this stdout into the CI environment;
        removing it would break every ephemeral test run."""
        result = run_ephemeral(harness)

        assert result.returncode == 0, result.stderr
        exports = [line for line in result.stdout.splitlines() if line.startswith("export ")]
        assert len(exports) == 9, exports
        for name in (
            "TEST_OWNER_EMAIL",
            "TEST_OWNER_PASSWORD",
            "TEST_OWNER_TOTP_SECRET",
            "TEST_CONTRIBUTOR_EMAIL",
            "TEST_CONTRIBUTOR_PASSWORD",
            "TEST_READONLY_EMAIL",
            "TEST_READONLY_PASSWORD",
            "TEST_SMOKE_EMAIL",
            "TEST_SMOKE_PASSWORD",
        ):
            assert any(line.startswith(f"export {name}=") for line in exports), exports


class TestScriptsCarryNoInlineCredentialFlags:
    """Static backstop: an unexercised branch must not reintroduce the flag."""

    @pytest.mark.parametrize(
        "script",
        ["create-test-users.sh", "create-screenshot-user.sh", "create-ephemeral-test-users.sh"],
    )
    def test_no_inline_credential_flag_in_source(self, repo_root: Path, script: str) -> None:
        source = (repo_root / "scripts" / script).read_text()

        assert "--temporary-password" not in source
        assert "--password " not in source
