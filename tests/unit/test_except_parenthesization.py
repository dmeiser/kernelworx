"""Portability guard for issue #572: every module under ``src/`` must parse
under the pre-3.14 grammar.

The project targets Python 3.14 (``requires-python = ">=3.14"``), where an
unparenthesized multi-type ``except A, B:`` is legal PEP 758 syntax. It reads as
Python 2's catch-and-bind form, and it is a ``SyntaxError`` on Python 3.13 and
earlier, so any consumer of the source on an older interpreter cannot load the
module at all.

The property is checked semantically rather than by matching the spelling: each
module is parsed with the 3.13 grammar, which accepts the canonical
``except (A, B):`` and rejects the PEP 758 unparenthesized form outright.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
PRE_PEP758_GRAMMAR = (3, 13)


def test_src_modules_parse_under_pre_3_14_grammar() -> None:
    """No module under ``src/`` uses syntax newer than the 3.13 grammar."""
    assert SRC_ROOT.is_dir(), f"expected source tree at {SRC_ROOT}"

    failures: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        try:
            ast.parse(path.read_text(), feature_version=PRE_PEP758_GRAMMAR)
        except SyntaxError as exc:
            rel = path.relative_to(SRC_ROOT)
            failures.append(f"  {rel}:{exc.lineno}: {exc.msg}")

    assert not failures, "modules must parse on Python 3.13:\n" + "\n".join(failures)
