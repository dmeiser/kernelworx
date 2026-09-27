"""Unit tests for the shared report order-graph budget (#577).

Both report paths enforce a ceiling measured in the bytes an order graph
serialises to, so the charge has to stay an upper bound on what the report
actually returns: if it ever undercharged, a unit that passed the budget could
still come back as a truncated AppSync response. These tests execute the real
estimator against real order items and the real order-detail projection, so a
change to the stored order shape, to the projected detail, or to the estimator
fails here rather than letting the ceiling quietly become fiction.
"""

import json
from decimal import Decimal
from typing import Any

import pytest

from src.handlers.campaign_reporting import _build_order_detail
from src.utils.errors import AppError, ErrorCode
from src.utils.report_limits import (
    APPSYNC_RESPONSE_LIMIT_BYTES,
    MAX_REPORT_GRAPH_BYTES,
    OrderGraphBudget,
    order_graph_bytes,
)

_LONG_PRODUCT_NAME = "White Chocolate Caramel Popcorn (16oz Bucket)"


def _line_item(index: int = 0) -> dict[str, Any]:
    """Build a realistically wide line item."""
    return {
        "productId": f"PRODUCT#7d9a1c2e-4b3a-4c8d-9e0f-1a2b3c4d5e6f-{index}",
        "productName": _LONG_PRODUCT_NAME,
        "quantity": 12,
        "pricePerUnit": Decimal("12.50"),
        "subtotal": Decimal("150.00"),
    }


def _stored_order(line_items: int = 5) -> dict[str, Any]:
    """Build a stored order item as DynamoDB returns it."""
    return {
        "orderId": "ORDER#2f1c9d4a-8b3e-4a21-9c77-1f0d5e6a7b8c",
        "profileId": "PROFILE#0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
        "campaignId": "CAMPAIGN#9a8b7c6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
        "customerName": "Alexandra Montgomery-Whitfield",
        "customerPhone": "+1 (217) 555-0142",
        "customerAddress": {
            "street": "1234 Old Country Road Apt 12B",
            "city": "Springfield",
            "state": "IL",
            "zipCode": "62704",
        },
        "orderDate": "2024-10-01T12:00:00.000Z",
        "paymentMethod": "VENMO",
        "lineItems": [_line_item(i) for i in range(line_items)],
        "totalAmount": Decimal("1500.00"),
        "notes": "Please deliver after 4pm; ring the doorbell twice.",
        "createdAt": "2024-10-01T12:00:00.000Z",
        "updatedAt": "2024-10-01T12:00:00.000Z",
    }


def _widest_stored_order(line_items: int = 5) -> dict[str, Any]:
    """Build the widest order the schema can store: every variable value at its maximum."""
    return {
        "orderId": "ORDER#" + "a" * 200,
        "profileId": "PROFILE#" + "b" * 200,
        "campaignId": "CAMPAIGN#" + "c" * 200,
        "customerName": "N" * 200,
        "customerPhone": "P" * 50,
        "customerAddress": {"street": "S" * 200, "city": "C" * 200, "state": "T" * 200, "zipCode": "Z" * 200},
        "orderDate": "2024-10-01T12:00:00.000Z",
        "paymentMethod": "M" * 50,
        "lineItems": [
            {
                "productId": "PRODUCT#" + "d" * 200,
                "productName": "Q" * 500,
                "quantity": 999_999,
                "pricePerUnit": Decimal("-99999.99"),
                "subtotal": Decimal("-999999999.99"),
            }
            for _ in range(line_items)
        ],
        "totalAmount": Decimal("-9999999999.99"),
        "notes": "X" * 2000,
        "createdAt": "2024-10-01T12:00:00.000Z",
        "updatedAt": "2024-10-01T12:00:00.000Z",
    }


def _serialised_bytes(value: Any) -> int:
    """Return the length of the JSON the report actually emits for ``value``.

    Numbers are serialised as the floats a GraphQL response carries, which is
    how the handlers convert their monetary values before returning, and text is
    written as UTF-8 rather than ASCII-escaped, which is what a response body
    carries.
    """
    return len(json.dumps(value, default=float, ensure_ascii=False).encode("utf-8"))


class TestOrderGraphBytes:
    """The charge prices real order items, never less than they serialise to."""

    @pytest.mark.parametrize("line_items", [1, 5, 20, 60])
    def test_charge_covers_the_serialised_stored_order(self, line_items: int) -> None:
        """The charge is an upper bound on the serialised stored order at every width."""
        order = _stored_order(line_items)

        assert order_graph_bytes(order) >= _serialised_bytes(order)

    @pytest.mark.parametrize("line_items", [1, 5, 20, 60])
    def test_charge_covers_the_serialised_unit_report_detail(self, line_items: int) -> None:
        """The charge also bounds the order detail the unit report projects and returns."""
        order = _stored_order(line_items)

        assert order_graph_bytes(order) >= _serialised_bytes(_build_order_detail(order))

    def test_charge_covers_the_widest_serialised_unit_report_detail(self) -> None:
        """An order with every variable value maximal is the case that proves a bound, not an average."""
        order = _widest_stored_order()

        assert order_graph_bytes(order) >= _serialised_bytes(_build_order_detail(order))

    def test_charge_follows_the_stored_order_rather_than_a_fixed_price(self) -> None:
        """A field the budget has no knowledge of is still charged, and grows with the data.

        The charge is measured from the order as stored, so a field added to the
        order - or a field that simply gets longer - moves the charge instead of
        disappearing behind a constant the module would have to maintain by hand.
        """
        baseline = order_graph_bytes(_stored_order(5))
        narrow = order_graph_bytes({**_stored_order(5), "aNewlyAddedField": "x" * 500}) - baseline
        wide = order_graph_bytes({**_stored_order(5), "aNewlyAddedField": "x" * 5_000}) - baseline

        assert 0 < narrow < wide

    def test_charge_tracks_line_item_width(self) -> None:
        """Line items, not just orders, drive the charge."""
        narrow = order_graph_bytes(_stored_order(1))
        wide = order_graph_bytes(_stored_order(20))

        assert wide > narrow * 5

    def test_charge_never_under_reads_non_ascii_text(self) -> None:
        """Accented text is charged at least what it costs in the UTF-8 response."""
        order = _stored_order(5)
        order["customerName"] = "Zoë Ångström Škoda-Ñuñez"
        order["lineItems"][0]["productName"] = "Maïs/caramel，北米 — 16oz"

        assert order_graph_bytes(order) >= _serialised_bytes(order)


class TestOrderGraphBudget:
    """The budget refuses the order that would cross it and nothing earlier."""

    def test_the_order_crossing_the_budget_is_refused(self) -> None:
        """A budget sized for N orders admits exactly N and refuses the next."""
        order = _stored_order(5)
        size = order_graph_bytes(order)
        budget = OrderGraphBudget("This unit's", max_bytes=size * 2)

        budget.admit(order)
        budget.admit(order)

        with pytest.raises(AppError) as exc_info:
            budget.admit(order)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert "too large" in exc_info.value.message

    def test_the_error_names_the_budget_that_was_crossed(self) -> None:
        """A caller with a tighter budget reports its own ceiling, not the default."""
        budget = OrderGraphBudget("This campaign's", max_bytes=500_000)
        order = _stored_order(60)

        with pytest.raises(AppError) as exc_info:
            for _ in range(200):
                budget.admit(order)

        assert exc_info.value.message == (
            "This campaign's report is too large to generate: its order details exceed 0.5 MB."
        )


class TestBudgetSize:
    """The default budget leaves AppSync's response limit room for the rest of the payload."""

    def test_budget_is_a_fraction_of_the_app_sync_response_limit(self) -> None:
        """The ceiling is derived from the response limit, not picked out of the air."""
        assert APPSYNC_RESPONSE_LIMIT_BYTES == 5_000_000
        assert 0 < MAX_REPORT_GRAPH_BYTES <= APPSYNC_RESPONSE_LIMIT_BYTES // 2
