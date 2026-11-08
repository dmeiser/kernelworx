"""Unit tests for inventory operations (Stage 2 wave 2)."""

import pytest

from src.handlers.inventory_operations import (
    adjust_council_on_order,
    adjust_inventory,
    record_inventory_receipt,
)


def test_inv_m_01_record_receipt_invalid_quantity():
    with pytest.raises(Exception):
        record_inventory_receipt({"arguments": {"quantity": 0}}, None)


def test_inv_m_01_no_side_effect():
    r = record_inventory_receipt({"arguments": {"quantity": 2}}, None)
    assert r["success"] is True


def test_inv_m_02_adjust_inventory():
    with pytest.raises(Exception):
        adjust_inventory({"arguments": {"delta": 0, "reason": "x"}}, None)


def test_inv_m_02_missing_reason():
    with pytest.raises(Exception):
        adjust_inventory({"arguments": {"delta": 1}}, None)


def test_inv_m_03_adjust_council_on_order():
    with pytest.raises(Exception):
        adjust_council_on_order({"arguments": {"delta": -5, "current": 2}}, None)


def test_inv_m_03_zero_result():
    r = adjust_council_on_order({"arguments": {"delta": -2, "current": 2}}, None)
    assert r["councilOnOrderQty"] == 0


def test_inv_m_02_missing_reason_branch():
    with pytest.raises(Exception):
        adjust_inventory({"arguments": {"delta": 1, "reason": ""}}, None)


def test_inv_m_03_negative_result_branch():
    with pytest.raises(Exception):
        adjust_council_on_order({"arguments": {"delta": -5, "current": 2}}, None)


def test_inv_m_02_success_path():
    r = adjust_inventory({"arguments": {"delta": 1, "reason": "r"}}, None)
    assert r["success"] is True


def test_inv_m_03_non_int_delta():
    with pytest.raises(Exception):
        adjust_council_on_order({"arguments": {"delta": "x"}}, None)
