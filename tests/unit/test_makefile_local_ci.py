"""Behavioral tests for the Makefile's local CI mirror (#536).

The `ci` target advertises itself as the local CI pipeline, so it must plan
every suite the CI workflow runs (including the AppSync JS resolver suite),
and its `.PHONY` list must be consistent with the targets it actually
declares.
"""

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

TARGET_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*):")


def _run_make(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _phony_names(text: str) -> set[str]:
    """Names declared on the `.PHONY` line(s), continuation-aware."""
    lines = text.splitlines()
    names: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(".PHONY:"):
            logical = line.split(":", 1)[1]
            while logical.endswith("\\"):
                logical = logical[:-1] + " " + lines[i + 1]
                i += 1
            names = logical.split()
        i += 1
    return set(names)


def _defined_target_names(text: str) -> set[str]:
    """Top-level target names (recipe lines start with a tab and never match)."""
    return {m.group(1) for line in text.splitlines() if (m := TARGET_RE.match(line))}


def test_ci_plans_the_appsync_js_resolver_suite():
    """`make ci` must plan the exact command the CI js-resolvers job runs."""
    proc = _run_make(REPO_ROOT, "-n", "ci")
    assert proc.returncode == 0, proc.stderr
    assert "npm run test:js-resolvers" in proc.stdout, (
        f"`make ci` does not plan the AppSync JS resolver suite that CI runs (planned commands:\n{proc.stdout})"
    )


def test_stray_files_cannot_shadow_test_targets(tmp_path: Path):
    """A stray file named after a recipe target must not make make skip it."""
    for target in ("test-guards", "ci-full", "ci", "js-resolvers"):
        sandbox = tmp_path / target
        sandbox.mkdir()
        shutil.copy(MAKEFILE, sandbox / "Makefile")
        (sandbox / target).write_text("stray file shadowing the make target\n")
        proc = _run_make(sandbox, "-n", target)
        assert proc.returncode == 0, f"{target}: {proc.stderr}"
        assert "is up to date" not in proc.stdout, (
            f"target `{target}` was shadowed by a stray file of the same name (output:\n{proc.stdout})"
        )


def test_phony_list_declares_only_real_targets():
    """Every name in `.PHONY` must be a target that `make <name>` can run."""
    text = MAKEFILE.read_text()
    declared = _phony_names(text)
    defined = _defined_target_names(text)
    phantoms = declared - defined
    assert not phantoms, f".PHONY declares names with no corresponding target: {sorted(phantoms)}"


def test_ci_and_ci_full_targets_are_protected_from_shadowing():
    """The real `ci`-family and guard-suite targets must be declared .PHONY."""
    declared = _phony_names(MAKEFILE.read_text())
    missing = {"test-guards", "ci-full"} - declared
    assert not missing, f"real targets missing from .PHONY: {sorted(missing)}"
