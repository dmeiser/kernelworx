"""Contract: user-facing catalog mutations persist ``isPublic`` as a DynamoDB BOOL.

Issue #428: ``create_catalog_request.vtl`` and ``update_catalog_request.vtl``
previously coerced ``isPublic`` to the strings ``"true"`` / ``"false"`` and
persisted it as a DynamoDB String. The GraphQL schema declares
``isPublic: Boolean!`` and the admin Python handlers
(``src/handlers/admin_operations.py``) write a native BOOL, so user-created
catalogs diverged from admin-created ones (String vs. BOOL in one table) and
boolean filters broke.

These tests render the actual VTL templates with a minimal Velocity engine
and assert on the emitted DynamoDB operation documents: the PutItem /
UpdateItem ``attributeValues`` must carry ``isPublic`` as a DynamoDB BOOL and
``isPublicStr`` as the separate String keying the ``isPublic-createdAt-index``
GSI. The read-side tests render ``get_catalog_response.vtl`` and assert the
catalog item serializes unchanged for GraphQL.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "tofu" / "application" / "appsync" / "mapping-templates"
CREATE_VTL = TEMPLATES / "create_catalog_request.vtl"
UPDATE_VTL = TEMPLATES / "update_catalog_request.vtl"
GET_CATALOG_RESPONSE_VTL = TEMPLATES / "get_catalog_response.vtl"

_IDENT = re.compile(r"[A-Za-z_]\w*")
_FIRST = object()  # sentinel: the branch condition of the opening #if


class VtlAppError(Exception):
    """Mirrors ``$util.error(message, type)`` aborting template evaluation."""

    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(f"{error_type}: {message}")
        self.message = message
        self.error_type = error_type


def _to_dynamodb_json(value: Any) -> Any:
    """Mirror ``$util.dynamodb.toDynamoDBJson`` for the value types used here."""
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float)):
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list):
        return {"L": [_to_dynamodb_json(item) for item in value]}
    if isinstance(value, dict):
        return {"M": {key: _to_dynamodb_json(item) for key, item in value.items()}}
    raise AssertionError(f"unsupported DynamoDB value type: {type(value)!r}")


class _UtilDynamoDb:
    def toDynamoDBJson(self, value: Any) -> Any:
        return _to_dynamodb_json(value)


class _UtilTime:
    def nowISO8601(self) -> str:
        return "2024-01-02T03:04:05.000Z"


class _Util:
    def __init__(self) -> None:
        self.dynamodb = _UtilDynamoDb()
        self.time = _UtilTime()

    def autoId(self) -> str:
        return "00000000-0000-4000-8000-000000000000"

    def toJson(self, value: Any) -> Any:
        return value  # identity; emission json.dumps non-strings

    def qr(self, _value: Any) -> str:
        return ""

    def error(self, message: str, error_type: str) -> None:
        raise VtlAppError(message, error_type)


def _split_top_level(text: str, sep: str) -> List[str]:
    """Split on ``sep`` occurrences outside quotes and nested brackets/parens."""
    parts: List[str] = []
    depth = 0
    start = 0
    in_string = False
    for idx, ch in enumerate(text):
        if ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _find_top_level(text: str, needle: str) -> int:
    depth = 0
    in_string = False
    idx = 0
    while idx <= len(text) - len(needle):
        ch = text[idx]
        if ch == '"':
            in_string = not in_string
        elif in_string:
            idx += 1
            continue
        elif ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif depth == 0 and text.startswith(needle, idx):
            return idx
        idx += 1
    return -1


def _get_attr(node: Any, member: str) -> Any:
    if node is None:
        return None
    if isinstance(node, dict):
        return node.get(member)
    return getattr(node, member)


def _call_method(node: Any, member: str, args: List[Any]) -> Any:
    if isinstance(node, dict):
        if member == "put":
            node[args[0]] = args[1]
            return None
        if member == "isEmpty":
            return len(node) == 0
    if isinstance(node, list):
        if member == "add":
            node.append(args[0])
            return None
        if member == "size":
            return len(node)
        if member == "isEmpty":
            return len(node) == 0
    return getattr(node, member)(*args)


def _parse_call_args(text: str, pos: int, ctx: Dict[str, Any]) -> Tuple[List[Any], int]:
    """Parse a balanced ``(...)`` argument list starting at text[pos] == '('."""
    depth = 0
    in_string = False
    start: Optional[int] = None
    raw_args: List[str] = []
    i = pos
    while i < len(text):
        ch = text[i]
        if ch == '"':
            in_string = not in_string
        elif in_string:
            i += 1
            continue
        elif ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                assert start is not None
                raw_args.append(text[start:i])
                return [_eval_value(arg, ctx) for arg in raw_args if arg.strip()], i + 1
        elif ch == "," and depth == 1:
            assert start is not None
            raw_args.append(text[start:i])
            start = i + 1
        i += 1
    raise AssertionError(f"unbalanced parentheses in {text[pos:]!r}")


def _eval_ref(text: str, pos: int, ctx: Dict[str, Any]) -> Tuple[Any, int]:
    """Evaluate a ``$ref[.member[(args)]]`` chain starting at text[pos] == '$'."""
    match = _IDENT.match(text, pos + 1)
    assert match, f"malformed reference in {text[pos:]!r}"
    node = ctx.get(match.group(0))
    i = match.end()
    while True:
        while i < len(text) and text[i] in " \t":
            i += 1
        if i >= len(text) or text[i] != ".":
            break
        member_match = _IDENT.match(text, i + 1)
        assert member_match, f"malformed member access in {text[pos:]!r}"
        member = member_match.group(0)
        i = member_match.end()
        while i < len(text) and text[i] in " \t":
            i += 1
        if i < len(text) and text[i] == "(":
            args, i = _parse_call_args(text, i, ctx)
            node = _call_method(node, member, args)
        else:
            node = _get_attr(node, member)
    return node, i


def _interpolate(text: str, ctx: Dict[str, Any]) -> str:
    """Velocity string-literal interpolation of ``$ref`` sequences."""
    out: List[str] = []
    i = 0
    while i < len(text):
        if text[i] == "$":
            value, i = _eval_ref(text, i, ctx)
            out.append(value if isinstance(value, str) else json.dumps(value))
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _eval_map_literal(expr: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    inner = expr.strip()[1:-1]
    result: Dict[str, Any] = {}
    for entry in _split_top_level(inner, ","):
        match = re.fullmatch(r'"([^"]+)"\s*:\s*(.+)', entry, re.DOTALL)
        assert match, f"malformed map entry: {entry!r}"
        result[match.group(1)] = _eval_value(match.group(2), ctx)
    return result


def _eval_value(expr: str, ctx: Dict[str, Any]) -> Any:
    expr = expr.strip()
    if expr.startswith('"') and expr.endswith('"'):
        return _interpolate(expr[1:-1], ctx)
    if expr.startswith("{"):
        return _eval_map_literal(expr, ctx)
    if expr.startswith("["):
        return [_eval_value(item, ctx) for item in _split_top_level(expr.strip()[1:-1], ",")]
    if expr.startswith("$"):
        value, _end = _eval_ref(expr, 0, ctx)
        return value
    if expr == "true":
        return True
    if expr == "false":
        return False
    if expr == "null":
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", expr):
        return float(expr) if "." in expr else int(expr)
    raise AssertionError(f"unsupported VTL expression: {expr!r}")


def _eval_atom(atom: str, ctx: Dict[str, Any]) -> bool:
    atom = atom.strip()
    negate = atom.startswith("!")
    if negate:
        atom = atom[1:].strip()
    for operator in ("!=", "=="):
        idx = _find_top_level(atom, operator)
        if idx != -1:
            left = _eval_value(atom[:idx], ctx)
            right = _eval_value(atom[idx + len(operator) :], ctx)
            result = left == right
            return not result if negate else result
    result = bool(_eval_value(atom, ctx))
    return not result if negate else result


def _eval_condition(condition: str, ctx: Dict[str, Any]) -> bool:
    return any(_eval_atom(atom, ctx) for atom in _split_top_level(condition, "|"))


def _strip_parens(text: str) -> str:
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


def _collect_block(lines: List[str], i: int) -> Tuple[List[str], int]:
    """Collect a #foreach body until its matching #end."""
    depth = 0
    body: List[str] = []
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line.startswith("#if") or line.startswith("#foreach"):
            depth += 1
            body.append(raw)
        elif line.startswith("#end"):
            if depth == 0:
                return body, i + 1
            depth -= 1
            body.append(raw)
        else:
            body.append(raw)
        i += 1
    raise AssertionError("unbalanced #foreach block")


def _collect_if(lines: List[str], i: int) -> Tuple[List[Tuple[Any, List[str]]], int]:
    """Collect #if branches: [(condition_or_FIRST, body), ...]; None marks #else."""
    depth = 0
    branches: List[Tuple[Any, List[str]]] = []
    condition: Any = _FIRST
    body: List[str] = []
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line.startswith("#if") or line.startswith("#foreach"):
            depth += 1
            body.append(raw)
        elif line.startswith("#end"):
            if depth == 0:
                branches.append((condition, body))
                return branches, i + 1
            depth -= 1
            body.append(raw)
        elif depth == 0 and line.startswith("#elseif"):
            branches.append((condition, body))
            condition = _strip_parens(line[len("#elseif") :])
            body = []
        elif depth == 0 and line.startswith("#else"):
            branches.append((condition, body))
            condition = None
            body = []
        else:
            body.append(raw)
        i += 1
    raise AssertionError("unbalanced #if block")


def _paren_balance(text: str) -> int:
    depth = 0
    in_string = False
    for ch in text:
        if ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth


def _render_lines(lines: List[str], ctx: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("##"):
            continue
        if line.startswith("#set"):
            statement = line
            while _paren_balance(statement) > 0:
                statement += "\n" + lines[i]
                i += 1
            match = re.fullmatch(r"#set\(\$(\w+)\s*=\s*(.+)\)", statement, re.DOTALL)
            assert match, f"malformed #set: {statement!r}"
            ctx[match.group(1)] = _eval_value(match.group(2), ctx)
        elif line.startswith("#if"):
            branches, i = _collect_if(lines, i)
            opening_condition = _strip_parens(line[len("#if") :])
            for branch_condition, body in branches:
                if branch_condition is _FIRST:
                    taken = _eval_condition(opening_condition, ctx)
                elif branch_condition is None:
                    taken = True
                else:
                    taken = _eval_condition(branch_condition, ctx)
                if taken:
                    out.extend(_render_lines(body, ctx))
                    break
        elif line.startswith("#foreach"):
            match = re.fullmatch(r"#foreach\(\$(\w+) in (.+)\)", line)
            assert match, f"malformed #foreach: {line!r}"
            body, i = _collect_block(lines, i)
            items = _eval_value(match.group(2), ctx) or []
            for item in items:
                sub_context = dict(ctx)
                sub_context[match.group(1)] = item
                out.extend(_render_lines(body, sub_context))
        elif line.startswith("#end") or line.startswith("#else"):
            raise AssertionError(f"stray directive: {line!r}")
        else:
            out.append(_render_text(line, ctx))
    return out


def _render_text(line: str, ctx: Dict[str, Any]) -> str:
    out: List[str] = []
    i = 0
    in_string = False
    while i < len(line):
        ch = line[i]
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            i += 1
        elif ch == "$" and not in_string:
            value, i = _eval_ref(line, i, ctx)
            out.append(value if isinstance(value, str) else json.dumps(value))
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def render_vtl(source: str, context: Dict[str, Any]) -> str:
    """Render a VTL template, returning the emitted text (a JSON document)."""
    ctx = dict(context)
    ctx["util"] = _Util()
    return "\n".join(_render_lines(source.splitlines(), ctx))


def _render_json(source_path: Path, context: Dict[str, Any]) -> Any:
    return json.loads(render_vtl(source_path.read_text(), context))


def _catalog_input(is_public: bool) -> Dict[str, Any]:
    return {
        "catalogName": "Spring Sale",
        "isPublic": is_public,
        "products": [
            {"productName": "Cookie", "price": 5, "sortOrder": 1, "description": "Chocolate"},
            {"productName": "Popcorn", "price": 3, "sortOrder": 2},
        ],
    }


def _create_context(is_public: bool) -> Dict[str, Any]:
    return {
        "ctx": {
            "args": {"input": _catalog_input(is_public)},
            "identity": {"sub": "user-1"},
        }
    }


def _update_context(is_public: bool) -> Dict[str, Any]:
    return {
        "ctx": {
            "args": {"catalogId": "CATALOG#existing", "input": _catalog_input(is_public)},
            "identity": {"sub": "user-1"},
        }
    }


class TestCreateCatalogRequestVtl:
    """The emitted PutItem document must persist isPublic as a DynamoDB BOOL."""

    def test_emitted_put_item_for_public_catalog(self):
        document = _render_json(CREATE_VTL, _create_context(is_public=True))
        assert document["operation"] == "PutItem"
        values = document["attributeValues"]
        assert values["isPublic"] == {"BOOL": True}
        assert values["isPublicStr"] == {"S": "true"}

    def test_emitted_put_item_for_private_catalog(self):
        document = _render_json(CREATE_VTL, _create_context(is_public=False))
        values = document["attributeValues"]
        assert values["isPublic"] == {"BOOL": False}
        assert values["isPublicStr"] == {"S": "false"}

    def test_ispublic_follows_native_boolean_not_string(self):
        # Regression: rendering with a native False must not produce the
        # truthy String "false" in the BOOL attribute.
        document = _render_json(CREATE_VTL, _create_context(is_public=False))
        values = document["attributeValues"]
        assert values["isPublic"] != {"S": "false"}
        assert values["isPublicStr"] != {"BOOL": False}

    def test_empty_products_rejected(self):
        context = _create_context(is_public=True)
        context["ctx"]["args"]["input"]["products"] = []
        try:
            render_vtl(CREATE_VTL.read_text(), context)
        except VtlAppError as error:
            assert error.error_type == "INVALID_INPUT"
        else:  # pragma: no cover
            raise AssertionError("expected $util.error for empty products")


class TestUpdateCatalogRequestVtl:
    """The emitted UpdateItem document must set isPublic from the native boolean."""

    def test_emitted_update_item_for_public_catalog(self):
        document = _render_json(UPDATE_VTL, _update_context(is_public=True))
        assert document["operation"] == "UpdateItem"
        values = document["update"]["expressionValues"]
        assert values[":isPublic"] == {"BOOL": True}
        assert values[":isPublicStr"] == {"S": "true"}

    def test_emitted_update_item_for_private_catalog(self):
        document = _render_json(UPDATE_VTL, _update_context(is_public=False))
        values = document["update"]["expressionValues"]
        assert values[":isPublic"] == {"BOOL": False}
        assert values[":isPublicStr"] == {"S": "false"}

    def test_update_sets_both_attributes(self):
        document = _render_json(UPDATE_VTL, _update_context(is_public=True))
        expression = document["update"]["expression"]
        assert "isPublic = :isPublic" in expression
        assert "isPublicStr = :isPublicStr" in expression


class TestGetCatalogResponseVtl:
    """The response template serializes the raw catalog item unchanged."""

    @staticmethod
    def _context_with_result(result: Any) -> Dict[str, Any]:
        return {"ctx": {"result": result}}

    def test_native_bool_passthrough(self):
        result = {"catalogId": "CATALOG#new", "isPublic": False, "catalogName": "New"}
        output = _render_json(GET_CATALOG_RESPONSE_VTL, self._context_with_result(result))
        assert output["isPublic"] is False

    def test_missing_result_serializes_null(self):
        output = _render_json(GET_CATALOG_RESPONSE_VTL, self._context_with_result(None))
        assert output is None

    def test_empty_result_serializes_null(self):
        output = _render_json(GET_CATALOG_RESPONSE_VTL, self._context_with_result({}))
        assert output is None

    def test_error_propagates(self):
        context = {"ctx": {"error": {"type": "DynamoDB:ConditionalCheckFailedException", "message": "denied"}}}
        try:
            render_vtl(GET_CATALOG_RESPONSE_VTL.read_text(), context)
        except VtlAppError as error:
            assert error.error_type == "DynamoDB:ConditionalCheckFailedException"
        else:  # pragma: no cover
            raise AssertionError("expected $util.error to propagate ctx.error")
