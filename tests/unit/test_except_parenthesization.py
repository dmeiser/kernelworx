"""Regression guard for issue #572: parenthesize multi-type ``except`` clauses.

The project targets Python 3.14 (``requires-python = ">=3.14"``), where an
unparenthesized multi-type ``except A, B:`` is legal PEP 758 syntax that builds a
tuple. It is, however, the form of Python 2's ``except Exception, name:``
catch-and-bind, so a reader mistakes it for a name binding, and any tool running
on Python 3.13 or earlier fails to parse the file at all
(``SyntaxError: multiple exception types must be parenthesized``).

The canonical form in this project is the parenthesized one --
``except (A, B):`` -- which is valid on every Python 3 version and, on 3.14,
produces an AST identical to the PEP 758 form (a ``Tuple`` of the exception
types). The parenthesized form is therefore the correct, unambiguous spelling.

This test walks the whole ``src/`` tree and asserts that every multi-type
``except`` clause is parenthesized. It uses ``ast`` (not a text grep) so it does
not trip on comments or string contents: a clause is flagged only when the
exception-type node is a ``Tuple`` whose source line does not begin with ``(``
at the type node's offset. A single-type ``except`` (no tuple) is fine.
"""

import ast
from pathlib import Path

# All .py modules under src/ -- the invariant is project-wide.
SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def _unparenthesized_multi_type_excepts(source: str) -> list[tuple[int, str]]:
    """Return (line, text) for every unparenthesized multi-type ``except`` clause.

    A multi-type clause parses to an ``ast.ExceptHandler`` whose ``type`` is an
    ``ast.Tuple``. Both ``except (A, B):`` and ``except A, B:`` (PEP 758) parse
    to that same ``Tuple``, so the AST alone cannot distinguish them; the source
    can: the parenthesized form's type node starts at the ``(`` on its line,
    while the PEP 758 form's type node starts at the first exception name.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    bad: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        type_node = node.type
        if not isinstance(type_node, ast.Tuple):
            continue
        line_text = lines[type_node.lineno - 1]
        col = type_node.col_offset
        starts_char = line_text[col] if col < len(line_text) else ""
        if starts_char != "(":
            bad.append((type_node.lineno, line_text.strip()))
    return bad


def test_no_unparenthesized_multi_type_except_in_src() -> None:
    """No ``except A, B:`` (PEP 758) clauses anywhere in src/ -- all parenthesized."""
    assert SRC_ROOT.is_dir(), f"expected source tree at {SRC_ROOT}"

    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        findings = _unparenthesized_multi_type_excepts(path.read_text())
        if findings:
            offenders[str(path.relative_to(SRC_ROOT))] = findings

    message_lines = ["unparenthesized multi-type 'except' clauses found (use 'except (A, B):'):",]
    for rel, findings in offenders.items():
        for line_no, text in findings:
            message_lines.append(f"  {rel}:{line_no}: {text}")
    assert not offenders, "\n".join(message_lines)


def test_named_issue_files_parse_with_parenthesized_multi_type() -> None:
    """The three files named in #572 parse and use only parenthesized multi-type."""
    named = [
        "src/utils/validation.py",
        "src/utils/responses.py",
        "src/handlers/admin_operations.py",
    ]
    for rel in named:
        path = Path(__file__).resolve().parents[2] / rel
        assert path.is_file(), f"missing named file {rel}"
        source = path.read_text()
        # Parses on the project's interpreter; the PEP 758 form would also parse
        # here on 3.14, so this guards against syntax breakage, not style.
        ast.parse(source)
        assert _unparenthesized_multi_type_excepts(source) == [], (
            f"{rel} has unparenthesized multi-type 'except' clauses"
        )


def test_parenthesized_form_is_ast_identical_to_pep758_form() -> None:
    """Parenthesizing a multi-type clause is a pure spelling change on 3.14.

    Confirms the premise of the fix: ``except (A, B):`` and ``except A, B:``
    (PEP 758, legal on 3.14) compile to the same handler AST, so changing the
    spelling changes no runtime behavior.
    """
    import sys

    if sys.version_info < (3, 14):
        # The PEP 758 unparenthesized form is a SyntaxError below 3.14, which is
        # exactly the portability defect this issue records; there is nothing to
        # compare on this interpreter.
        import pytest
        pytest.skip("PEP 758 unparenthesized multi-type except requires Python 3.14")

    paren = ast.parse(
        "def f():\n    try:\n        x()\n    except (ValueError, TypeError):\n        pass\n"
    )
    unparen = ast.parse(
        "def f():\n    try:\n        x()\n    except ValueError, TypeError:\n        pass\n"
    )

    def handler(node: ast.Module) -> ast.ExceptHandler:
        found = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
        assert len(found) == 1
        return found[0]

    hp = handler(paren)
    hu = handler(unparen)
    # Both are a Tuple of the same two names -> identical handler AST.
    assert ast.dump(hp) == ast.dump(hu)
    # And the parenthesized form is the one that parses on every Python 3.
    assert isinstance(hp.type, ast.Tuple)
