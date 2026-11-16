"""A test double that refuses what DynamoDB refuses: a Query filter over a key attribute.

The service rejects a ``Query`` whose ``FilterExpression`` names a key attribute of
the table — or of the index — it is reading:

    ValidationException: Filter Expression can only contain non-primary key
    attributes: Primary key attribute: sk

moto answers the same call, so every read built that way was green in CI and failed
on every deployed request (WORK-158: ``inventoryMovements`` answered
``INTERNAL_ERROR`` on ``dev``, with ``INV-Q-02`` and ``PAGE-01`` passing locally).
This guard installs the service's rule on the client a test drives, which is the
only way a test can pin that class of defect: a moto-based assertion on the RESULT
of such a query can never fail.

Two details decide whether the guard helps or simply blocks, and both are the
service's behaviour rather than a guess:

- The key schema that counts is the one for the index named by ``IndexName``, not
  the base table's. A GSI query that filters a base-table key attribute is accepted
  by the service (aws-emulator#372 reproduces the rejection on the emulator and
  states it was checked against us-east-1 on 2026-11-13, where the same query
  succeeds; DynamoDB Local accepts it too). The Stage 1 reads that list a Unit's
  campaigns and invites depend on that: they query an index and filter ``pk``/``sk``.
- A ``Scan`` keeps its filter free of that rule — the service allows key attributes
  in a Scan filter, because a Scan has no key condition to put them in. Only Query
  is guarded here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterator, List, Mapping

from botocore.exceptions import ClientError

# ``:name`` placeholders are values, not attributes: a filter for ``#sk = :sk`` would
# otherwise report the value token as the offending key attribute.
_PLACEHOLDER = re.compile(r":[A-Za-z0-9_]+")
# Attribute names, including the ``#name`` form and a dotted document path.
_TOKEN = re.compile(r"[#A-Za-z0-9_.]+")

# Expression operators and functions, matched case-insensitively on bare tokens so a
# word that happens to name nothing cannot be mistaken for an attribute reference.
_EXPRESSION_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "and",
        "or",
        "not",
        "between",
        "in",
        "begins_with",
        "contains",
        "attribute_exists",
        "attribute_not_exists",
        "attribute_type",
        "size",
        "if_not_exists",
    }
)


def attribute_tokens(expression: str) -> Iterator[str]:
    """Yield the attributes a condition expression references, in ``#name`` or bare form."""
    for token in _TOKEN.findall(_PLACEHOLDER.sub(" ", expression)):
        if token.startswith("#"):
            yield token
            continue
        # A document path is rooted at its first segment; only that segment can be a key.
        name = token.split(".")[0]
        if not name or name.lower() in _EXPRESSION_KEYWORDS:
            continue
        yield name


def key_attributes_by_index(schema: Mapping[str, Any]) -> Dict[str, FrozenSet[str]]:
    """Map an index name (``""`` is the base table) to the key attributes of that scope."""
    scopes: Dict[str, FrozenSet[str]] = {
        "": frozenset(str(key["AttributeName"]) for key in schema.get("KeySchema", []))
    }
    indexes: List[Mapping[str, Any]] = [
        *schema.get("GlobalSecondaryIndexes", []),
        *schema.get("LocalSecondaryIndexes", []),
    ]
    for index in indexes:
        scopes[str(index["IndexName"])] = frozenset(str(key["AttributeName"]) for key in index.get("KeySchema", []))
    return scopes


def violating_key_attribute(params: Mapping[str, Any], scopes: Mapping[str, FrozenSet[str]]) -> str | None:
    """Return the key attribute a Query filter names, or None when the Query is legal."""
    expression = params.get("FilterExpression")
    if not isinstance(expression, str) or not expression:
        return None
    scope = scopes.get(str(params.get("IndexName") or ""))
    if not scope:
        # An unknown index is not this guard's business; the service reports it.
        return None
    names: Mapping[str, str] = params.get("ExpressionAttributeNames") or {}
    for token in attribute_tokens(expression):
        attribute = names.get(token, token) if token.startswith("#") else token
        if attribute in scope:
            return attribute
    return None


def install_query_filter_guard(client: Any, schema: Mapping[str, Any]) -> None:
    """Teach one DynamoDB client to raise the service's error for one table's bad Query.

    The guard is scoped to the table its schema describes, so installing it for the
    inventory table leaves every other read of the same test untouched.
    """
    table_name = str(schema["TableName"])
    scopes = key_attributes_by_index(schema)

    def _reject_key_attribute_filter(params: Dict[str, Any], **kwargs: Any) -> None:
        if str(params.get("TableName", "")) != table_name:
            return
        attribute = violating_key_attribute(params, scopes)
        if attribute is None:
            return
        raise ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": (
                        "Filter Expression can only contain non-primary key attributes: "
                        f"Primary key attribute: {attribute}"
                    ),
                },
                "ResponseMetadata": {"HTTPStatusCode": 400},
            },
            "Query",
        )

    client.meta.events.register("before-parameter-build.dynamodb.Query", _reject_key_attribute_filter)
