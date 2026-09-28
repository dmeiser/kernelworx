"""Convention guard for issue #572: the multi-type ``except`` spelling in ``src/``.

The project pins ``requires-python = ">=3.14"``, where an unparenthesized
multi-type handler (``except ValueError, TypeError:``) is legal PEP 758 syntax.
It reads like Python 2's ``except Exception, name:`` catch-and-bind form, which
it is not: it builds a tuple of exception types and binds no name, so runtime
behavior is identical to the parenthesized spelling.

That unparenthesized spelling is also exactly what ``ruff format`` emits for the
pinned target version, and the formatter STRIPS parentheses around these
clauses. Hand-written parentheses and the repo's own formatter are therefore in
direct conflict, and the project's documented workflow (README, AGENT.md,
docs/GETTING_STARTED.md, docs/DEVELOPER_GUIDE.md) tells every contributor and
agent to run ``uv run ruff format src/ tests/``. The resolved convention is
therefore to keep the formatter's spelling and document it, rather than to
parenthesize and have the next format run silently revert it.

These tests pin that convention. They are semantic, not textual: the
multi-type handlers are located by walking the AST, and the spelling check is
delegated to the formatter itself rather than matched against source text.
"""

import ast
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PYPROJECT = REPO_ROOT / "pyproject.toml"
EXPECTED_PYTHON_FLOOR = (3, 14)


def _multi_type_except_count(path: Path) -> int:
    """Count handlers catching more than one exception type, via the AST."""
    tree = ast.parse(path.read_text())
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple)
    )


def test_src_still_uses_multi_type_except_handlers() -> None:
    """Non-vacuity: the PEP 758 spelling is in use, so the guard below bites.

    Without this, deleting every multi-type handler would make the formatter
    check pass vacuously.
    """
    assert SRC_ROOT.is_dir(), f"expected source tree at {SRC_ROOT}"

    total = sum(_multi_type_except_count(path) for path in sorted(SRC_ROOT.rglob("*.py")))
    assert total >= 1, "no multi-type except handlers under src/; guard would be vacuous"


def test_src_is_in_ruff_formats_canonical_spelling() -> None:
    """``src/`` must already be formatted, which pins the unparenthesized form.

    This is the guard that fails if someone re-adds parentheses: at the pinned
    py314 target, ``ruff format`` rewrites ``except (A, B):`` back to
    ``except A, B:`` and this check reports the file as needing reformatting.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff is not installed in this environment")

    result = subprocess.run(
        [ruff, "format", "--check", "src/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "src/ is not in the spelling `ruff format` produces at the pinned target "
        "version. Multi-type except clauses must be left unparenthesized: the "
        "formatter strips parentheses around them.\n" + result.stdout + result.stderr
    )


def test_ruff_target_version_matches_the_python_floor() -> None:
    """The formatter target must be pinned to the same floor as ``requires-python``.

    ``ruff`` otherwise infers it from ``requires-python``. Making it explicit
    keeps the choice enforced rather than remembered, so a future floor change
    cannot silently flip the formatter's behavior on these clauses.
    """
    config = tomllib.loads(PYPROJECT.read_text())

    requires_python = config["project"]["requires-python"]
    floor = tuple(int(part) for part in requires_python.lstrip(">=").split("."))
    assert floor == EXPECTED_PYTHON_FLOOR, f"unexpected Python floor: {requires_python}"

    target_version = config["tool"]["ruff"]["target-version"]
    assert target_version == f"py{EXPECTED_PYTHON_FLOOR[0]}{EXPECTED_PYTHON_FLOOR[1]}", (
        f"ruff target-version is {target_version!r} but requires-python is {requires_python!r}; "
        "they must agree or the formatter's output for multi-type except clauses changes"
    )
