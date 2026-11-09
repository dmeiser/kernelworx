"""
Tests for src/utils/unit_auth.py (Show & Sell unit-grant authorization).

Covers the tombstone contract (spec SEC-02/SEC-03, AUTH-U-02/U-05):
removed access answers FORBIDDEN, cross-tenant absence answers
indistinguishable NOT_FOUND, and every read is a strongly consistent
base-table read.
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.utils.errors import AppError, ErrorCode
from src.utils.unit_auth import (
    METADATA_ITEM_KEY,
    get_grant,
    get_unit,
    grant_item_key,
    grant_tombstone_item_key,
    require_unit_admin,
)

UNIT_ID = "unit-123"
ACCOUNT_ID = "acct-456"


def _table_with_items(items: Dict[Any, Dict[str, Any]]) -> MagicMock:
    """Build a mock Table whose get_item serves items by Key tuple."""
    table = MagicMock()

    def _get_item(Key: Dict[str, Any], ConsistentRead: bool = False) -> Dict[str, Any]:  # noqa: N803
        assert ConsistentRead is True, "grant authorization must read consistently"
        key = (Key.get("unitId"), Key.get("itemKey"))
        item = items.get(key)
        return {"Item": item} if item else {}

    table.get_item.side_effect = _get_item
    return table


def _unit_row() -> Dict[str, Any]:
    return {"unitId": UNIT_ID, "itemKey": METADATA_ITEM_KEY, "name": "Pack 9999"}


class TestItemKeys:
    def test_grant_item_key(self) -> None:
        assert grant_item_key(ACCOUNT_ID) == "GRANT#acct-456"

    def test_grant_tombstone_item_key(self) -> None:
        assert grant_tombstone_item_key(ACCOUNT_ID) == "GRANT_TOMBSTONE#acct-456"


class TestGetUnit:
    def test_returns_metadata_row(self) -> None:
        table = _table_with_items({(UNIT_ID, METADATA_ITEM_KEY): _unit_row()})
        assert get_unit(table, UNIT_ID) == _unit_row()

    def test_returns_none_when_absent(self) -> None:
        table = _table_with_items({})
        assert get_unit(table, UNIT_ID) is None


class TestGetGrant:
    def test_returns_grant_row(self) -> None:
        grant = {"unitId": UNIT_ID, "itemKey": grant_item_key(ACCOUNT_ID)}
        table = _table_with_items({(UNIT_ID, grant_item_key(ACCOUNT_ID)): grant})
        assert get_grant(table, UNIT_ID, ACCOUNT_ID) == grant

    def test_returns_none_when_absent(self) -> None:
        table = _table_with_items({})
        assert get_grant(table, UNIT_ID, ACCOUNT_ID) is None


class TestRequireUnitAdmin:
    def test_unit_absent_raises_not_found(self) -> None:
        table = _table_with_items({})
        with pytest.raises(AppError) as exc_info:
            require_unit_admin(table, UNIT_ID, ACCOUNT_ID)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_grant_present_returns_unit(self) -> None:
        table = _table_with_items(
            {
                (UNIT_ID, METADATA_ITEM_KEY): _unit_row(),
                (UNIT_ID, grant_item_key(ACCOUNT_ID)): {"role": "UNIT_ADMIN"},
            }
        )
        assert require_unit_admin(table, UNIT_ID, ACCOUNT_ID) == _unit_row()

    def test_tombstone_raises_forbidden(self) -> None:
        table = _table_with_items(
            {
                (UNIT_ID, METADATA_ITEM_KEY): _unit_row(),
                (UNIT_ID, grant_tombstone_item_key(ACCOUNT_ID)): {"removedAt": "t"},
            }
        )
        with pytest.raises(AppError) as exc_info:
            require_unit_admin(table, UNIT_ID, ACCOUNT_ID)
        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_neither_grant_nor_tombstone_raises_not_found(self) -> None:
        table = _table_with_items({(UNIT_ID, METADATA_ITEM_KEY): _unit_row()})
        with pytest.raises(AppError) as exc_info:
            require_unit_admin(table, UNIT_ID, "acct-other")
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_expired_grant_shape_without_tombstone_is_not_found(self) -> None:
        # A grant row must be present-and-valid to authorize; the absence of
        # a tombstone does not upgrade an unknown caller past NOT_FOUND.
        table = _table_with_items(
            {
                (UNIT_ID, METADATA_ITEM_KEY): _unit_row(),
                (UNIT_ID, grant_tombstone_item_key("acct-other")): {"removedAt": "t"},
            }
        )
        with pytest.raises(AppError) as exc_info:
            require_unit_admin(table, UNIT_ID, ACCOUNT_ID)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
