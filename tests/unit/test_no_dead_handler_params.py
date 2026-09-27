"""Guard against dead parameters in handler functions (#573).

A parameter that is declared but never read is "just in case" surface area: a
caller can reasonably believe a ``logger`` they passed is being used when it is
silently ignored, and a ``campaign`` parameter makes a signature imply a
campaign-scoped result when the output is derived entirely from ``orders``.

Ruff cannot express this rule, so this test walks every function under
``src/handlers/`` and fails on any parameter that is never loaded in the
function body. ``self``, ``cls``, and the standard Lambda ``context`` are
excluded: the first two are convention, and ``context`` is taken by signature
convention on every Lambda entrypoint even when the handler does not read it.
"""

import ast
from pathlib import Path

HANDLERS_DIR = Path(__file__).resolve().parents[2] / "src" / "handlers"

# Parameters that may be declared but never read without being a defect.
_EXCLUDED_PARAMS = {"self", "cls", "context"}


def _parameter_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return the names of every parameter of a function definition."""
    args = func.args
    names = [arg.arg for group in ("posonlyargs", "args", "kwonlyargs") for arg in getattr(args, group)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _loaded_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the set of names loaded (read) anywhere in the function node."""
    return {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


def _dead_params(path: Path, source: str) -> list[str]:
    """Return descriptions of every dead parameter in a single handler module."""
    tree = ast.parse(source)
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        loaded = _loaded_names(node)
        for name in _parameter_names(node):
            if name not in _EXCLUDED_PARAMS and name not in loaded:
                findings.append(f"{path}:{node.lineno} in {node.name}(): '{name}'")
    return findings


def test_no_dead_params_in_handlers() -> None:
    """Every handler function parameter must be read, except self/cls/context."""
    dead = []
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        dead.extend(_dead_params(path, path.read_text()))
    assert not dead, "Dead parameters found (declared but never read):\n" + "\n".join(dead)
