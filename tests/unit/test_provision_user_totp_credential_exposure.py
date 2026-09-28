"""Regression tests for #569 and #597: no credential may appear on argv.

`scripts/provision-user-totp.sh` used to pass the password inline in
`--auth-parameters`, which puts it in the argv of the `aws` CLI process, and it
still passed the Cognito access token inline in `--access-token` (#597). argv of
a running process is world-readable on Linux (`/proc/<pid>/cmdline`) and visible
in `ps` for the duration of the call, so any co-tenant process on the runner
could read the credential. The script now writes every credential parameter -
the auth parameters and the access token - to a private `mktemp` file and passes
them with `--cli-input-json file://...`.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

PASSWORD = "Sup3rSecret-Pa55word,with#delimiters"
USERNAME = "owner@example.com"
POOL_ID = "us-east-1_ExamplePool"
CLIENT_ID = "1example23client45id6789"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"
# The tokens the mock `aws` CLI hands back for the two initiate-auth flows; both
# are live user-pool bearer credentials and neither may reach argv.
ACCESS_TOKEN = "user.password.access.token"
ADMIN_ACCESS_TOKEN = "admin.no.srp.access.token"
# The mock's credential scan reads /proc/<pid>/cmdline and /proc/<pid>/stat;
# where /proc is absent the scan records nothing and would pass vacuously.
requires_proc = pytest.mark.skipif(
    not Path("/proc/self/cmdline").exists(),
    reason="the argv/environ credential scan requires /proc (Linux only)",
)
# The credentials are baked into the fake aws CLI below so the mock can scan
# /proc for them without inheriting them through the environment.
for credential in (PASSWORD, ACCESS_TOKEN, ADMIN_ACCESS_TOKEN):
    assert "'" not in credential, f"the mock embeds {credential!r} in a single-quoted shell string"
    assert credential not in (POOL_ID, CLIENT_ID, USERNAME), f"{credential!r} must be distinguishable from argv args"

MOCK_AWS_TEMPLATE = """\
#!/bin/bash
# Record every argument exactly as the process received it, and snapshot the
# contents/mode of any file:// parameter file while it still exists.
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

# #569/#597: no command line in this process's ancestry may carry a credential -
# in particular this script's own argv, which is still alive as our parent.
# (The secrets stay in this shell's memory: they are never exported and never
# passed on a command line, so the scan below cannot itself leak them.)
scan_credential() {
  credential="$1"
  scan_pid=$$
  while [ "$scan_pid" -gt 1 ]; do
    if tr '\\0' '\\n' < "/proc/$scan_pid/cmdline" 2>/dev/null | grep -qF "$credential"; then
      printf '%s\\n' "$scan_pid" >> "$2"
    fi
    # Field 4 of /proc/<pid>/stat is ppid; strip past the comm field first.
    scan_pid=$(sed -e 's/^.*) //' -e 's/ .*//' "/proc/$scan_pid/stat" 2>/dev/null) || break
    [ -n "$scan_pid" ] || break
  done
  # The script unsets the password variable, so no credential may be inherited
  # into this process's environment either.
  if tr '\\0' '\\n' < /proc/self/environ 2>/dev/null | grep -qF "$credential"; then
    printf 'environ\\n' >> "$3"
  fi
}
scan_credential '__CREDENTIAL__' "$MOCK_AWS_CMDLINE_LEAKS" "$MOCK_AWS_ENV_LEAKS"
scan_credential '__ACCESS_TOKEN__' "$MOCK_AWS_TOKEN_CMDLINE_LEAKS" "$MOCK_AWS_TOKEN_ENV_LEAKS"
scan_credential '__ADMIN_ACCESS_TOKEN__' "$MOCK_AWS_TOKEN_CMDLINE_LEAKS" "$MOCK_AWS_TOKEN_ENV_LEAKS"

sub="$1 $2"
case "$sub" in
  "cognito-idp admin-get-user")
    # No TOTP device from an earlier provisioning.
    echo "None"
    ;;
  "cognito-idp initiate-auth")
    if [ "${FAIL_USER_PASSWORD_AUTH:-0}" = "1" ]; then
      echo "simulated USER_PASSWORD_AUTH failure" >&2
      exit 254
    fi
    echo "__ACCESS_TOKEN__"
    ;;
  "cognito-idp admin-initiate-auth")
    echo "__ADMIN_ACCESS_TOKEN__"
    ;;
  "cognito-idp associate-software-token")
    echo "$MOCK_TOTP_SECRET"
    ;;
  *)
    # verify-software-token / admin-set-user-mfa-preference: nothing to do.
    ;;
esac
"""

MOCK_AWS = (
    MOCK_AWS_TEMPLATE.replace("__CREDENTIAL__", PASSWORD)
    .replace("__ACCESS_TOKEN__", ACCESS_TOKEN)
    .replace("__ADMIN_ACCESS_TOKEN__", ADMIN_ACCESS_TOKEN)
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Run provision-user-totp.sh against a recording fake `aws` CLI."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    logs = {
        name: tmp_path / f"{name}.log"
        for name in (
            "aws_argv",
            "aws_modes",
            "aws_param_files",
            "aws_param_contents",
            "aws_cmdline_leaks",
            "aws_env_leaks",
            "aws_token_cmdline_leaks",
            "aws_token_env_leaks",
        )
    }
    for path in logs.values():
        path.touch()

    def write_mock_bin(name: str, script: str) -> None:
        path = bin_dir / name
        path.write_text(textwrap.dedent(script).strip() + "\n")
        path.chmod(0o755)

    write_mock_bin("aws", MOCK_AWS)
    # The script waits for the TOTP window to roll over; skip that wait.
    write_mock_bin("sleep", "#!/bin/bash\nexit 0\n")
    write_mock_bin("date", "#!/bin/bash\necho 0\n")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("MOCK_AWS_LOG", str(logs["aws_argv"]))
    monkeypatch.setenv("MOCK_AWS_MODES", str(logs["aws_modes"]))
    monkeypatch.setenv("MOCK_AWS_PARAM_FILES", str(logs["aws_param_files"]))
    monkeypatch.setenv("MOCK_AWS_PARAM_CONTENTS", str(logs["aws_param_contents"]))
    monkeypatch.setenv("MOCK_AWS_CMDLINE_LEAKS", str(logs["aws_cmdline_leaks"]))
    monkeypatch.setenv("MOCK_AWS_ENV_LEAKS", str(logs["aws_env_leaks"]))
    monkeypatch.setenv("MOCK_AWS_TOKEN_CMDLINE_LEAKS", str(logs["aws_token_cmdline_leaks"]))
    monkeypatch.setenv("MOCK_AWS_TOKEN_ENV_LEAKS", str(logs["aws_token_env_leaks"]))
    monkeypatch.setenv("MOCK_TOTP_SECRET", TOTP_SECRET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    return {"bin_dir": bin_dir, "logs": logs}


def run_script(
    harness: dict[str, object], repo_root: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the script the way its callers do: three arguments, secret by env."""
    return subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "provision-user-totp.sh"),
            POOL_ID,
            CLIENT_ID,
            USERNAME,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{harness['bin_dir']}{os.pathsep}{os.environ['PATH']}",
            "PROVISION_USER_TOTP_PASSWORD": PASSWORD,
            **(env or {}),
        },
    )


def logs(harness: dict[str, object]) -> dict[str, Path]:
    return harness["logs"]  # type: ignore[return-value]


def aws_invocations(harness: dict[str, object]) -> list[list[str]]:
    raw = logs(harness)["aws_argv"].read_bytes()
    if not raw:
        return []
    return [chunk.decode().split("\0")[:-1] for chunk in raw.split(b"\0\0") if chunk]


def param_files(harness: dict[str, object]) -> list[Path]:
    """Every `file://` path the fake `aws` was pointed at."""
    text = logs(harness)["aws_param_files"].read_text()
    return [Path(line[len("file://") :]) for line in text.splitlines() if line.startswith("file://")]


def param_file_contents(harness: dict[str, object]) -> list[dict]:
    raw = logs(harness)["aws_param_contents"].read_text()
    return [json.loads(chunk) for chunk in raw.split("\x1e") if chunk.strip()]


def token_param_files(harness: dict[str, object]) -> list[dict]:
    """Contents of the parameter files that carry the pool access token."""
    return [chunk for chunk in param_file_contents(harness) if "AccessToken" in chunk]


class TestCredentialNeverOnArgv:
    """#569: the password must not reach any process's command line."""

    def test_password_absent_from_every_aws_argv(self, harness: dict[str, object], repo_root: Path) -> None:
        result = run_script(harness, repo_root)

        assert result.returncode == 0, result.stderr
        invocations = aws_invocations(harness)
        assert invocations, "the fake aws CLI was never invoked"
        for invocation in invocations:
            for arg in invocation:
                assert PASSWORD not in arg, f"credential leaked on argv: {invocation}"

    def test_no_inline_auth_parameters_argument(self, harness: dict[str, object], repo_root: Path) -> None:
        """The old inline `--auth-parameters USERNAME=..,PASSWORD=..` shape is gone."""
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        for invocation in aws_invocations(harness):
            assert "--auth-parameters" not in invocation
            assert not any("PASSWORD=" in arg for arg in invocation)

    def test_password_absent_from_admin_fallback_argv(
        self, harness: dict[str, object], repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ADMIN_NO_SRP_AUTH fallback is the second exposure window (#569)."""
        monkeypatch.setenv("FAIL_USER_PASSWORD_AUTH", "1")
        result = run_script(harness, repo_root)

        assert result.returncode == 0, result.stderr
        flows = " ".join(" ".join(i) for i in aws_invocations(harness))
        assert "ADMIN_NO_SRP_AUTH" in flows
        for invocation in aws_invocations(harness):
            for arg in invocation:
                assert PASSWORD not in arg, f"credential leaked on argv: {invocation}"


class TestAccessTokenNeverOnArgv:
    """#597: the pool access token must not reach any process's command line."""

    def test_access_token_absent_from_every_aws_argv(self, harness: dict[str, object], repo_root: Path) -> None:
        result = run_script(harness, repo_root)

        assert result.returncode == 0, result.stderr
        invocations = aws_invocations(harness)
        assert invocations, "the fake aws CLI was never invoked"
        for invocation in invocations:
            for arg in invocation:
                assert ACCESS_TOKEN not in arg, f"access token leaked on argv: {invocation}"

    def test_no_inline_access_token_flag(self, harness: dict[str, object], repo_root: Path) -> None:
        """The `--access-token <token>` shape must be gone from both calls."""
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        invocations = aws_invocations(harness)
        software_token_calls = [i for i in invocations if i[:2] == ["cognito-idp", "associate-software-token"]]
        software_token_calls += [i for i in invocations if i[:2] == ["cognito-idp", "verify-software-token"]]
        assert len(software_token_calls) == 2, f"expected both software-token calls: {invocations}"
        for invocation in software_token_calls:
            assert "--access-token" not in invocation, f"access token passed by flag: {invocation}"

    def test_access_token_passed_through_a_private_file(
        self, harness: dict[str, object], repo_root: Path
    ) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        chunks = token_param_files(harness)
        assert len(chunks) == 2, f"expected a parameter file per software-token call: {chunks}"
        for contents in chunks:
            assert contents["AccessToken"] == ACCESS_TOKEN

    def test_verify_call_still_sends_the_user_code_in_the_file(
        self, harness: dict[str, object], repo_root: Path
    ) -> None:
        """verify-software-token needs the code; it must ride in the file, not on argv."""
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        chunks = token_param_files(harness)
        with_code = [c for c in chunks if "UserCode" in c]
        assert len(with_code) == 1, f"expected exactly one call to carry the user code: {chunks}"
        user_code = with_code[0]["UserCode"]
        assert len(user_code) == 6 and user_code.isdigit(), f"unexpected user code: {user_code!r}"

        for invocation in aws_invocations(harness):
            if invocation[:2] == ["cognito-idp", "verify-software-token"]:
                assert "--user-code" not in invocation, f"user code passed by flag: {invocation}"

    def test_no_token_carries_on_a_command_line_while_running(
        self, harness: dict[str, object], repo_root: Path
    ) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        assert aws_invocations(harness), "the fake aws CLI was never invoked, so nothing was scanned"
        leaks = logs(harness)["aws_token_cmdline_leaks"].read_text().split()
        assert not leaks, f"the access token appeared in the command line of pid(s): {leaks}"
        assert not logs(harness)["aws_token_env_leaks"].read_text().split()

    def test_token_file_removed_when_a_later_step_fails(
        self, harness: dict[str, object], repo_root: Path
    ) -> None:
        """A failure after the token file exists must not leave the token on disk."""
        broken = harness["bin_dir"] / "aws"  # type: ignore[index]
        broken.write_text(
            textwrap.dedent(
                """\
                #!/bin/bash
                printf '%s\\0' "$@" >> "$MOCK_AWS_LOG"
                printf '\\0' >> "$MOCK_AWS_LOG"
                for arg in "$@"; do case "$arg" in file://*)
                  printf '%s\\n' "$arg" >> "$MOCK_AWS_PARAM_FILES";; esac; done
                case "$1 $2" in
                  "cognito-idp initiate-auth") echo "user.password.access.token";;
                  "cognito-idp associate-software-token") exit 1;;
                  *) ;;
                esac
                """
            ).strip()
            + "\n"
        )
        broken.chmod(0o755)

        result = run_script(harness, repo_root)

        assert result.returncode != 0
        files = param_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file survived a failed run: {path}"


class TestAuthParametersFile:
    def test_parameters_passed_through_a_file(self, harness: dict[str, object], repo_root: Path) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        assert param_files(harness), "no --cli-input-json file:// parameter file was used"
        auth_chunks = [c for c in param_file_contents(harness) if "AuthParameters" in c]
        assert auth_chunks, "the auth parameters were not passed through a file"
        for contents in auth_chunks:
            assert contents["AuthParameters"] == {"USERNAME": USERNAME, "PASSWORD": PASSWORD}

    def test_parameter_file_is_owner_only_readable(self, harness: dict[str, object], repo_root: Path) -> None:
        """mktemp already creates 0600; the script must not widen it."""
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        modes = logs(harness)["aws_modes"].read_text().split()
        assert modes, "the parameter file mode was not recorded"
        assert set(modes) == {oct(stat.S_IRUSR | stat.S_IWUSR)[2:]}

    def test_parameter_file_removed_on_success(self, harness: dict[str, object], repo_root: Path) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        files = param_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file outlived the script: {path}"

    def test_parameter_file_removed_on_failure(self, harness: dict[str, object], repo_root: Path) -> None:
        """A failed run must not leave the credential on disk (trap on EXIT)."""
        broken = harness["bin_dir"] / "aws"  # type: ignore[index]
        broken.write_text(
            "#!/bin/bash\n"
            'printf \'%s\\0\' "$@" >> "$MOCK_AWS_LOG"\n'
            "printf '\\0' >> \"$MOCK_AWS_LOG\"\n"
            'for arg in "$@"; do case "$arg" in file://*) '
            'printf \'%s\\n\' "$arg" >> "$MOCK_AWS_PARAM_FILES";; esac; done\n'
            "exit 1\n"
        )
        broken.chmod(0o755)

        result = run_script(harness, repo_root)

        assert result.returncode != 0
        files = param_files(harness)
        assert files
        for path in files:
            assert not path.exists(), f"parameter file survived a failed run: {path}"


class TestScriptOwnArgv:
    """#569: the credential must not be a positional argument either."""

    @requires_proc
    def test_no_process_command_line_carries_the_credential_while_running(
        self, harness: dict[str, object], repo_root: Path
    ) -> None:
        """Scans the process ancestry from inside the run, covering the script's own argv."""
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        assert aws_invocations(harness), "the fake aws CLI was never invoked, so nothing was scanned"
        leaks = logs(harness)["aws_cmdline_leaks"].read_text().split()
        assert not leaks, f"the credential appeared in the command line of pid(s): {leaks}"

    @requires_proc
    def test_credential_is_not_inherited_by_child_processes(self, harness: dict[str, object], repo_root: Path) -> None:
        result = run_script(harness, repo_root)
        assert result.returncode == 0, result.stderr

        assert aws_invocations(harness)
        assert not logs(harness)["aws_env_leaks"].read_text().split()

    def test_missing_environment_variable_fails_fast(self, harness: dict[str, object], repo_root: Path) -> None:
        """No silent positional fallback: without the variable, nothing runs."""
        result = run_script(harness, repo_root, env={"PROVISION_USER_TOTP_PASSWORD": ""})

        assert result.returncode != 0
        assert "PROVISION_USER_TOTP_PASSWORD" in result.stderr
        assert PASSWORD not in result.stderr
        assert not aws_invocations(harness), "the script called aws despite having no credential"


def test_still_prints_the_totp_secret(harness: dict[str, object], repo_root: Path) -> None:
    """The behavior the callers depend on is unchanged by #569."""
    result = run_script(harness, repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == TOTP_SECRET
