"""Unit tests for inventory operations (Stage 2 wave 2, partial)."""

import pytest

from src.handlers.inventory_operations import (
    adjust_council_on_order,
    adjust_inventory,
    record_inventory_receipt,
)


def test_record_inventory_receipt_invalid_quantity():
    with pytest.raises(Exception):
        record_inventory_receipt({"arguments": {"quantity": 0}}, None)


def test_adjust_inventory_missing_reason():
    with pytest.raises(Exception):
        adjust_inventory({"arguments": {"delta": 1}}, None)


def test_adjust_council_on_order_negative_result():
    with pytest.raises(Exception):
        adjust_council_on_order({"arguments": {"delta": -5, "current": 2}}, None)
