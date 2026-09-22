"""Contract: user-facing catalog mutations persist ``isPublic`` as a DynamoDB BOOL.

Issue #428: ``create_catalog_request.vtl`` and ``update_catalog_request.vtl``
previously coerced ``isPublic`` to the strings ``"true"`` / ``"false"`` and
persisted it as a DynamoDB String. The GraphQL schema declares
``isPublic: Boolean!`` and the admin Python handlers
(``src/handlers/admin_operations.py``) write a native BOOL, so user-created
catalogs diverged from admin-created ones (String vs. BOOL in one table) and
boolean filters broke.

These templates must persist ``isPublic`` from the native GraphQL boolean
(``$ctx.args.input.isPublic``) and keep ``isPublicStr`` as the separate String
used to key the ``isPublic-createdAt-index`` GSI — mirroring the admin item
layout exactly. These tests parse the VTL source and assert that contract.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VTLS = REPO_ROOT / "tofu" / "application" / "appsync" / "mapping-templates"
CREATE_VTL = VTLS / "create_catalog_request.vtl"
UPDATE_VTL = VTLS / "update_catalog_request.vtl"

NATIVE_BOOL = "$ctx.args.input.isPublic"
STRING_FOR_GSI = "$isPublicStr"


def _read(path: Path) -> str:
    return path.read_text()


def _line_containing(source: str, needle: str) -> str | None:
    """Return the first source line containing ``needle``."""
    for line in source.splitlines():
        if needle in line:
            return line
    return None


class TestCreateCatalogRequestVtl:
    def test_ispublic_persisted_as_native_bool(self):
        line = _line_containing(_read(CREATE_VTL), '"isPublic"')
        assert line is not None
        assert NATIVE_BOOL in line
        assert "toDynamoDBJson" in line

    def test_ispublic_not_coerced_to_string(self):
        line = _line_containing(_read(CREATE_VTL), '"isPublic"')
        assert line is not None
        # Regression: the String variant must not be written for the BOOL attr.
        assert STRING_FOR_GSI not in line

    def test_ispublicstr_still_written_for_gsi(self):
        line = _line_containing(_read(CREATE_VTL), '"isPublicStr"')
        assert line is not None
        assert STRING_FOR_GSI in line


class TestUpdateCatalogRequestVtl:
    def test_ispublic_expression_value_is_native_bool(self):
        line = _line_containing(_read(UPDATE_VTL), '":isPublic"')
        assert line is not None
        assert NATIVE_BOOL in line
        assert "toDynamoDBJson" in line

    def test_ispublic_not_coerced_to_string(self):
        line = _line_containing(_read(UPDATE_VTL), '":isPublic"')
        assert line is not None
        assert STRING_FOR_GSI not in line

    def test_ispublicstr_still_written_for_gsi(self):
        line = _line_containing(_read(UPDATE_VTL), '":isPublicStr"')
        assert line is not None
        assert STRING_FOR_GSI in line

    def test_update_expression_sets_both_attributes(self):
        expr = _line_containing(_read(UPDATE_VTL), "SET catalogName")
        assert expr is not None
        assert "isPublic = :isPublic" in expr
        assert "isPublicStr = :isPublicStr" in expr
