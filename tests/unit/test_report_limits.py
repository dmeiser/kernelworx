"""Unit tests for the shared report order-graph ceilings (#577).

Both report paths enforce a ceiling measured in the bytes an order graph
serialises to, so the charge has to be an upper bound on what the report
actually returns, and each ceiling has to be the one its own path can afford.
These tests execute the real charge against real order items and the real order
detail the unit report projects, and drive realistic volumes through the real
budget at the real ceilings, so a change to the stored order shape, to the
projected detail, or to either number fails here rather than letting a ceiling
quietly become fiction - or quietly start refusing reports the platform could
have carried.
"""

import json
from decimal import Decimal
from typing import Any

import pytest

from src.handlers.campaign_reporting import _build_order_detail
from src.utils.errors import AppError, ErrorCode
from src.utils.report_limits import (
    MAX_CAMPAIGN_REPORT_GRAPH_BYTES,
    MAX_UNIT_REPORT_GRAPH_BYTES,
    OrderGraphBudget,
    order_graph_bytes,
)

_LONG_PRODUCT_NAME = "White Chocolate Caramel Popcorn (16oz Bucket)"

# The order count #577 approved for a single report: "a few thousand is
# generous" for a scout unit or one campaign.
_APPROVED_REPORT_ORDERS = 5_000


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

    Numbers are serialised the way a response carries them - ``Decimal`` becomes
    the float the handlers convert monetary values to, which is what
    ``json.dumps(..., default=float)`` produces - and text is written as UTF-8
    rather than ASCII-escaped, which is what a response body carries.
    """
    return len(json.dumps(value, default=float, ensure_ascii=False).encode("utf-8"))


class TestChargeBoundsWhatIsReturned:
    """Each path charges the record it materialises, and never less than it costs."""

    @pytest.mark.parametrize("line_items", [1, 5, 20, 60])
    def test_charge_bounds_the_serialised_stored_order(self, line_items: int) -> None:
        """The campaign export's charge bounds the stored order it holds at every width."""
        order = _stored_order(line_items)

        assert order_graph_bytes(order) >= _serialised_bytes(order)

    @pytest.mark.parametrize("line_items", [1, 5, 20, 60])
    def test_charge_bounds_the_serialised_unit_report_detail(self, line_items: int) -> None:
        """The unit report's charge bounds the detail it returns, as the response carries it.

        The detail is charged with the ``Decimal`` money the handler materialises
        and the response returns it as floats, so this is the assertion that the
        unit path never holds - and never returns - more than it charged.
        """
        detail = _build_order_detail(_stored_order(line_items))

        assert order_graph_bytes(detail) >= _serialised_bytes(detail)

    def test_charge_bounds_the_widest_unit_report_detail(self) -> None:
        """An order with every variable value maximal is the case that proves a bound, not an average."""
        detail = _build_order_detail(_widest_stored_order())

        assert order_graph_bytes(detail) >= _serialised_bytes(detail)

    def test_unit_report_is_not_charged_for_fields_it_does_not_return(self) -> None:
        """The charge tracks the projected detail, not the wider stored order behind it.

        ``_build_order_detail`` drops the profile, campaign, address, notes and
        timestamp fields, so charging the stored order would bill the unit report
        for bytes it never returns - at this shape, more than twice what the
        response costs.
        """
        order = _stored_order(1)
        detail = _build_order_detail(order)

        assert order_graph_bytes(detail) < order_graph_bytes(order) / 2

    def test_charge_follows_the_record_rather_than_a_fixed_price(self) -> None:
        """A field the budget has no knowledge of is still charged, and grows with the data.

        The charge is measured from the record itself, so a field added to the
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


class TestBudgetEnforcement:
    """The budget refuses the record that would cross it and nothing earlier."""

    def test_the_record_crossing_the_budget_is_refused(self) -> None:
        """A budget sized for N records admits exactly N and refuses the next."""
        record = _stored_order(5)
        size = order_graph_bytes(record)
        budget = OrderGraphBudget("This unit's", size * 2)

        budget.admit(record)
        budget.admit(record)

        with pytest.raises(AppError) as exc_info:
            budget.admit(record)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert "too large" in exc_info.value.message

    def test_the_error_names_the_budget_that_was_crossed(self) -> None:
        """A caller with a tighter budget reports its own ceiling, not the default."""
        budget = OrderGraphBudget("This campaign's", 500_000)
        order = _stored_order(60)

        with pytest.raises(AppError) as exc_info:
            for _ in range(200):
                budget.admit(order)

        assert exc_info.value.message == (
            "This campaign's report is too large to generate: its order details exceed 0.5 MB."
        )


class TestCeilingsCarryTheApprovedOrderCount:
    """Each ceiling is exercised at the real default, against a realistic volume."""

    def test_unit_ceiling_reports_the_approved_order_count(self) -> None:
        """A whole unit of ``_APPROVED_REPORT_ORDERS`` realistic orders still reports.

        This is the capacity the issue approved ("a few thousand is generous"),
        charged through the real ceiling the unit report enforces. A change to
        the number - or to the order shape, which moves the charge - that made a
        unit this size fail would fail here.
        """
        budget = OrderGraphBudget("This unit's", MAX_UNIT_REPORT_GRAPH_BYTES)
        detail = _build_order_detail(_stored_order(1))

        for _ in range(_APPROVED_REPORT_ORDERS):
            budget.admit(detail)

    def test_unit_ceiling_refuses_the_same_count_when_the_orders_are_wide(self) -> None:
        """The same order count of 20-line-item orders is refused, which is the point of bytes.

        Narrow and wide orders are the same number of orders and very different
        amounts of work, so a ceiling expressed in orders could not tell them
        apart. The refusal lands well before the 5,000th wide order, and a
        response carrying all of them could not have been returned within
        AppSync's response quota in any case.
        """
        budget = OrderGraphBudget("This unit's", MAX_UNIT_REPORT_GRAPH_BYTES)
        detail = _build_order_detail(_stored_order(20))

        with pytest.raises(AppError) as exc_info:
            for _ in range(_APPROVED_REPORT_ORDERS):
                budget.admit(detail)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_campaign_ceiling_exports_the_approved_order_count(self) -> None:
        """A campaign of the approved order count exports even when every order is wide.

        The export is not a resolver response, so its ceiling has to keep the
        approved order count exporting at every realistic width - not only the
        narrow one. This drives 20-line-item orders, which is the widest a
        realistic bulk-popcorn order gets.
        """
        budget = OrderGraphBudget("This campaign's", MAX_CAMPAIGN_REPORT_GRAPH_BYTES)
        order = _stored_order(20)

        for _ in range(_APPROVED_REPORT_ORDERS):
            budget.admit(order)

    def test_campaign_ceiling_refuses_a_graph_larger_than_the_lambda_holds(self) -> None:
        """The campaign export still has a ceiling, at the volume that exhausts the function.

        It bites far past the approved order count, but it bites: at the widest
        orders the schema can store, a campaign three times the approved size is
        refused with the same typed error rather than running the function out of
        memory (#533).
        """
        budget = OrderGraphBudget("This campaign's", MAX_CAMPAIGN_REPORT_GRAPH_BYTES)
        order = _widest_stored_order(20)

        with pytest.raises(AppError) as exc_info:
            for _ in range(_APPROVED_REPORT_ORDERS * 3):
                budget.admit(order)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
