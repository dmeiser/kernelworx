"""Character-class invariant of the ephemeral test-user password generator.

`scripts/create-ephemeral-test-users.sh` generates each test user's password
once, before its retry loop, so a generator that can emit a Cognito-policy
rejection (e.g. a base64 prefix whose surviving characters happen to contain
no lowercase letter, with suffix `A1!`) fails deterministically: all five
`admin-set-user-password` attempts repeat the same invalid password and the
run dies on a misleading auth error. The generator therefore guarantees every
required character class by construction; these tests generate many passwords
through the real `generate_password()` function and assert the invariant on
each one, so a future edit to the generator cannot silently reintroduce the
bug.

The contract these tests pin down, per password:

- length is at least Cognito's minimum of 15;
- it contains at least one lowercase letter;
- it contains at least one uppercase letter;
- it contains at least one digit;
- it contains at least one symbol.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

GENERATED_PASSWORD_COUNT = 2000

LOWERCASE = re.compile(r"[a-z]")
UPPERCASE = re.compile(r"[A-Z]")
DIGIT = re.compile(r"[0-9]")
SYMBOL = re.compile(r"[^A-Za-z0-9]")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create-ephemeral-test-users.sh"


def generate_passwords(count: int) -> list[str]:
    """Run the real generate_password() from the script `count` times.

    The function definition is extracted from the script source (it sits
    between `generate_password() {` and the closing `}`) and sourced, so the
    code under test is exactly what ships; the rest of the script (which would
    make Cognito calls at source time) is never executed.
    """
    bash_program = (
        f"extracted=$(mktemp); "
        f"sed -n '/^generate_password()/,/^}}/p' '{SCRIPT}' > \"$extracted\" && "
        f'source "$extracted" && rm -f "$extracted" && '
        f"for _ in $(seq 1 {count}); do generate_password; done"
    )
    result = subprocess.run(
        ["bash", "-c", bash_program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


class TestGeneratePasswordInvariant:
    def test_every_password_satisfies_the_cognito_policy_classes(self) -> None:
        passwords = generate_passwords(GENERATED_PASSWORD_COUNT)
        assert len(passwords) == GENERATED_PASSWORD_COUNT

        for password in passwords:
            assert len(password) >= 15, f"too short: {password!r}"
            assert LOWERCASE.search(password), f"no lowercase letter: {password!r}"
            assert UPPERCASE.search(password), f"no uppercase letter: {password!r}"
            assert DIGIT.search(password), f"no digit: {password!r}"
            assert SYMBOL.search(password), f"no symbol: {password!r}"
