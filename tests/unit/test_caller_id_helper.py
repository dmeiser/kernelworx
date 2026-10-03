"""Caller-ID extraction goes through ``utils.appsync_types.get_caller_id`` (#527).

``get_caller_id`` exists to centralize the caller-ID read, but thirteen handler
sites had inlined it in three dialects. Only one of them was total:
``event["identity"]["sub"]`` raises ``KeyError`` on a malformed or
unauthenticated event, where ``get_caller_id`` returns ``None``.

The AST guard below scans every handler source and fails if any handler reads
``identity``/``sub`` directly instead of going through ``get_caller_id`` — the
centralization only survives if nothing can silently re-inline the read.
"""

import ast
from pathlib import Path

from src.utils.appsync_types import get_caller_id

HANDLERS_DIR = Path(__file__).parent.parent.parent / "src" / "handlers"

# Handlers may legitimately read other keys off the AppSync identity (e.g.
# ``identity.get("claims")`` for group-based admin checks via ``utils.auth``);
# only the ``sub`` read must go through ``get_caller_id``, because every other
# dialect of that read is partial. Add a filename here with a comment saying
# why if a deliberate exception ever becomes necessary.
SUB_READ_EXEMPTIONS: frozenset[str] = frozenset()


def _identity_aliases(tree: ast.AST) -> set[str]:
    """Collect names bound to the AppSync ``identity`` sub-object of the event."""
    aliases = {"identity"}  # a parameter or local literally named identity
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            # event["identity"] or event.get("identity")
            if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name) and value.value.id == "event":
                aliases.add(node.targets[0].id)
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "get"
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "event"
            ):
                aliases.add(node.targets[0].id)
    return aliases


def _sub_read_violations(source: str, path: Path) -> list[str]:
    """Return human-readable lines for every direct identity/sub read in source."""
    tree = ast.parse(source, filename=str(path))
    aliases = _identity_aliases(tree)

    def base_name(expr: ast.expr) -> str | None:
        """Unwrap call/subscript chains (event.get('identity', {}).get) to their root Name."""
        while isinstance(expr, (ast.Call, ast.Subscript)):
            if isinstance(expr, ast.Subscript):
                expr = expr.value
            elif isinstance(expr.func, ast.Attribute):
                expr = expr.func.value
            else:
                return None
        return expr.id if isinstance(expr, ast.Name) else None

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "sub":
            root = base_name(node.value)
            if root is not None and (root in aliases or root == "event"):
                violations.append(f"{path}: {root}['sub'] at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "sub"
        ):
            root = base_name(node.func.value)
            if root is not None and (root in aliases or root == "event"):
                violations.append(f"{path}: {root}.get('sub') at line {node.lineno}")
    return violations


def test_no_handler_reads_identity_sub_directly() -> None:
    """AST guard: every caller-ID read goes through get_caller_id, never re-inlined.

    Without this, the centralization erodes silently — the next handler can
    re-introduce ``event['identity']['sub']`` and nothing flags it.
    """
    violations = []
    for source_path in sorted(HANDLERS_DIR.glob("*.py")):
        if source_path.name in SUB_READ_EXEMPTIONS:
            continue
        violations.extend(_sub_read_violations(source_path.read_text(), source_path))
    assert not violations, "Direct identity/sub reads found; use get_caller_id instead:\n" + "\n".join(violations)


def test_guard_flags_a_direct_sub_read() -> None:
    """The guard must actually go red: a handler inlining the read is flagged."""
    violating = "def handler(event, context):\n    return event['identity']['sub']\n"
    assert _sub_read_violations(violating, Path("synthetic_handler.py"))


def test_guard_flags_aliased_and_dotted_dialects() -> None:
    """The three dialects the helper replaced are all caught, including aliasing."""
    for dialect in (
        "def h(event, context):\n    identity = event.get('identity')\n    return identity.get('sub')\n",
        "def h(event, context):\n    return event.get('identity', {}).get('sub')\n",
        "def h(event, context):\n    caller = event['identity']\n    return caller['sub']\n",
    ):
        assert _sub_read_violations(dialect, Path("synthetic_handler.py")), dialect

    # Non-sub identity reads (claims for admin checks) and unrelated .get("sub")
    # calls (Cognito ListUsers attributes) must NOT be flagged.
    benign = (
        "def h(event, context):\n    identity = event.get('identity')\n"
        "    claims = identity.get('claims')\n    return claims\n"
        "def g(attributes):\n    return attributes.get('sub', 'fallback')\n"
    )
    assert not _sub_read_violations(benign, Path("synthetic_handler.py"))


def test_get_caller_id_is_the_total_dialect() -> None:
    """The helper returns None for every shape the inlined dialects disagreed on."""
    assert get_caller_id({"identity": {"sub": "user-1"}}) == "user-1"
    assert get_caller_id({"identity": None}) is None
    assert get_caller_id({"identity": {}}) is None
    assert get_caller_id({}) is None
    assert get_caller_id({"identity": "not-a-dict"}) is None
