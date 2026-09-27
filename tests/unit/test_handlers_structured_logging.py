"""Regression guard: handler modules must use the project structured logger (#565).

The three Cognito triggers (pre_signup, post_authentication, pre_token_generation)
used to configure the ROOT logger at module scope and emit unstructured f-string
messages, so their log lines were invisible to ``grep '"correlationId"'`` in
CloudWatch despite being the most security-relevant events in the system. The
failure is invisible until an incident, so this guard statically parses every
module under ``src/handlers/`` and fails on any ``logging.getLogger()`` call
without a name argument, and on any module that does not obtain its logger from
``utils.logging.get_logger``.
"""

import ast
from pathlib import Path
from typing import List

HANDLERS_DIR = Path(__file__).resolve().parents[2] / "src" / "handlers"


def _handler_modules() -> List[Path]:
    """All handler modules except the package __init__."""
    return sorted(path for path in HANDLERS_DIR.glob("*.py") if path.name != "__init__.py")


def _root_logger_get_call_lines(tree: ast.Module) -> List[int]:
    """Line numbers of ``logging.getLogger()`` calls with no arguments.

    Catches both the ``logging.getLogger()`` attribute form and the
    ``from logging import getLogger`` name form; either returns the root
    logger and reconfigures global logging state for the whole process.
    """
    imported_getters = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "logging":
            for alias in node.names:
                if alias.name == "getLogger":
                    imported_getters.add(alias.asname or alias.name)

    lines: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.args:
            continue
        func = node.func
        is_attribute_form = (
            isinstance(func, ast.Attribute)
            and func.attr == "getLogger"
            and isinstance(func.value, ast.Name)
            and func.value.id == "logging"
        )
        is_name_form = isinstance(func, ast.Name) and func.id in imported_getters
        if is_attribute_form or is_name_form:
            lines.append(node.lineno)
    return lines


def _imports_structured_logger(tree: ast.Module) -> bool:
    """Whether the module imports get_logger from utils.logging."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "utils.logging":
            if any(alias.name == "get_logger" for alias in node.names):
                return True
    return False


def test_no_handler_module_configures_root_logger() -> None:
    """No module under src/handlers/ may call logging.getLogger() unnamed."""
    modules = _handler_modules()
    assert modules, f"no handler modules found under {HANDLERS_DIR}"

    offenders = {
        path.name: _root_logger_get_call_lines(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in modules
    }
    offenders = {name: lines for name, lines in offenders.items() if lines}

    assert offenders == {}, f"modules configuring the root logger: {offenders}"


def test_every_handler_module_uses_structured_logger() -> None:
    """Every handler module obtains its logger via utils.logging.get_logger."""
    modules = _handler_modules()
    assert modules, f"no handler modules found under {HANDLERS_DIR}"

    missing = [
        path.name
        for path in modules
        if not _imports_structured_logger(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    ]

    assert missing == [], f"modules not using the structured logger: {missing}"
