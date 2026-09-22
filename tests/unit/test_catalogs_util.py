"""Tests for src/utils/catalogs.py — legacy isPublic coercion on raw items."""

from __future__ import annotations

from src.utils.catalogs import normalize_catalog_is_public


class TestNormalizeCatalogIsPublic:
    def test_legacy_string_true_coerced(self):
        catalog = {"catalogId": "CATALOG#1", "isPublic": "true"}
        assert normalize_catalog_is_public(catalog)["isPublic"] is True

    def test_legacy_string_false_coerced(self):
        catalog = {"catalogId": "CATALOG#1", "isPublic": "false"}
        assert normalize_catalog_is_public(catalog)["isPublic"] is False

    def test_native_bool_passthrough(self):
        catalog = {"catalogId": "CATALOG#1", "isPublic": False}
        assert normalize_catalog_is_public(catalog)["isPublic"] is False

    def test_missing_attribute_untouched(self):
        catalog = {"catalogId": "CATALOG#1"}
        assert normalize_catalog_is_public(catalog) == {"catalogId": "CATALOG#1"}

    def test_returns_same_item(self):
        catalog = {"catalogId": "CATALOG#1", "isPublic": "true"}
        assert normalize_catalog_is_public(catalog) is catalog
