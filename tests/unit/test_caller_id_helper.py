"""Caller-ID extraction goes through ``utils.appsync_types.get_caller_id`` (#527).

``get_caller_id`` exists to centralize the caller-ID read, but thirteen handler
sites had inlined it in three dialects. Only one of them was total:
``event["identity"]["sub"]`` raises ``KeyError`` on a malformed or
unauthenticated event, where ``get_caller_id`` returns ``None``.

The guards below are the regression:

* an AST walk over ``src/`` that fails on any hand-inlined caller-ID read
  outside ``appsync_types`` (so a new handler cannot reintroduce a fourth
  dialect), and
* a behavioral check that the one site which indexed ``event["identity"]["sub"]``
  now reports the typed ``UNAUTHORIZED`` error code instead of the generic
  ``INTERNAL_ERROR`` the ``KeyError`` produced.
"""

import ast
from pathlib import Path
from typing import List, Set

from src.handlers import list_catalogs_in_use
from src.utils.appsync_types import get_caller_id
from src.utils.errors import ErrorCode

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
# The helper itself is the one legitimate place that reads identity.sub.
ALLOWED = SRC_ROOT / "utils" / "appsync_types.py"


def _is_identity_source(node: ast.AST) -> bool:
    """True for an expression that reads the event's ``identity`` mapping."""
    if isinstance(node, ast.Subscript):
        slice_node = node.slice
        return isinstance(slice_node, ast.Constant) and slice_node.value == "identity"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == "identity"
    return False


def _reads_sub_from_identity(tree: ast.Module) -> List[int]:
    """Line numbers of every inline ``<identity>["sub"]`` / ``<identity>.get("sub")``."""
    hits: List[int] = []
    # Names bound to an identity mapping, so the two-statement dialect
    # (`identity = event.get("identity", {})` then `identity.get("sub")`) is caught too.
    identity_names: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_identity_source(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    identity_names.add(target.id)

    def is_identity_expr(node: ast.AST) -> bool:
        return _is_identity_source(node) or (isinstance(node, ast.Name) and node.id in identity_names)

    for node in ast.walk(tree):
        # dialect: event["identity"]["sub"]
        if isinstance(node, ast.Subscript) and is_identity_expr(node.value):
            slice_node = node.slice
            if isinstance(slice_node, ast.Constant) and slice_node.value == "sub":
                hits.append(node.lineno)
        # dialect: <identity>.get("sub") / (event.get("identity") or {}).get("sub")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "sub"
        ):
            receiver = node.func.value
            if is_identity_expr(receiver) or (
                isinstance(receiver, ast.BoolOp) and any(is_identity_expr(value) for value in receiver.values)
            ):
                hits.append(node.lineno)

    return sorted(hits)


def test_no_handler_inlines_the_caller_id_read() -> None:
    """Every ``src/`` module reads the caller through ``get_caller_id``."""
    offenders: List[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path == ALLOWED:
            continue
        tree = ast.parse(path.read_text())
        for lineno in _reads_sub_from_identity(tree):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert offenders == [], "inline caller-ID extraction reintroduced; call get_caller_id() instead: " + ", ".join(
        offenders
    )


def test_list_catalogs_in_use_reports_unauthenticated_instead_of_key_error() -> None:
    """A missing identity is UNAUTHORIZED, not the KeyError's generic INTERNAL_ERROR."""
    result = list_catalogs_in_use.handler({"identity": None}, None)

    assert result["__isError"] is True
    assert result["errorCode"] == ErrorCode.UNAUTHORIZED


def test_get_caller_id_is_the_total_dialect() -> None:
    """The helper returns None for every shape the inlined dialects disagreed on."""
    assert get_caller_id({"identity": {"sub": "user-1"}}) == "user-1"
    assert get_caller_id({"identity": None}) is None
    assert get_caller_id({"identity": {}}) is None
    assert get_caller_id({}) is None


def test_get_caller_id_tolerates_a_non_mapping_identity() -> None:
    """A present-but-non-mapping ``identity`` is None, not an AttributeError.

    Reading ``sub`` off a truthy non-mapping (a string, a number, a list)
    raises ``AttributeError``, which would surface as the decorator's generic
    ``INTERNAL_ERROR`` instead of the typed ``UNAUTHORIZED`` the handlers raise
    for an absent caller.
    """
    for identity in ("not-a-dict", 42, 0, ["sub"], object()):
        assert get_caller_id({"identity": identity}) is None
