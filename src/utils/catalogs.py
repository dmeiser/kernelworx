"""Shared helpers for raw DynamoDB catalog items returned to GraphQL.

User-created catalogs written before the create/update request-template fix
persisted ``isPublic`` as the DynamoDB Strings ``"true"``/``"false"`` (only
the separate ``isPublicStr`` key is legitimately a String, for the GSI). The
GraphQL schema declares ``isPublic: Boolean!``, so any raw item reaching a
``Catalog`` field must have a legacy String coerced back to a native BOOL
before AppSync serializes it. Items already carrying a BOOL pass through
untouched; no row backfill is performed.
"""

from __future__ import annotations

from typing import Any, Dict

__all__ = ["normalize_catalog_is_public"]


def normalize_catalog_is_public(catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a legacy String ``isPublic`` on a raw catalog item, in place."""
    is_public = catalog.get("isPublic")
    if is_public == "true":
        catalog["isPublic"] = True
    elif is_public == "false":
        catalog["isPublic"] = False
    return catalog
