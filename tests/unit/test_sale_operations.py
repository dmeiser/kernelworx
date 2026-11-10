"""Unit tests for src/handlers/sale_operations.py (Show & Sell wave 5):
sale persistence (immediate handoff + We-Owe-consumes-no-allocation),
absolute-target corrections, voids, We-Owe reservation/fulfillment."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict

import boto3
import pytest

from src.handlers.sale_operations import handler
from src.utils.errors import ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"

NOW = datetime.now(timezone.utc)


def _grid(moment: Any) -> Any:
    return moment.replace(minute=(moment.minute // 30) * 30, second=0, microsecond=0) + timedelta(days=1)


SALE_AT = _grid(NOW).isoformat().replace("+00:00", "Z")
CATALOG = {
    "products": [
        {"productId": "PROD#1", "productName": "Popcorn", "price": Decimal("5.0")},
        {"productId": "PROD#2", "productName": "Caramel", "price": Decimal("0.5")},
    ]
}


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "catalogs": dynamodb.Table("kernelworx-catalogs-ue1-dev"),
        "show_and_sells": dynamodb.Table("kernelworx-show-and-sells-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
    }


def _seed(t: Dict[str, Any]) -> None:
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": "METADATA",
            "accountId": ACCOUNT_A,
            "unitType": "Pack",
            "unitNumber": "1",
            "city": "D",
            "state": "CO",
            "displayName": "d",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": "k",
            "adminCount": 1,
            "activeInviteCount": 0,
            "version": 1,
            "createdAt": "t",
            "updatedAt": "t",
            "createdByAccountId": ACCOUNT_A,
        }
    )
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": f"GRANT#{ACCOUNT_A}",
            "accountId": ACCOUNT_A,
            "role": "UNIT_ADMIN",
            "createdByAccountId": ACCOUNT_A,
            "createdAt": "t",
        }
    )
    t["unit_campaigns"].put_item(
        Item={
            "unitCampaignId": "uc-1",
            "itemKey": "METADATA",
            "unitId": "unit-1",
            "campaignName": "S&S",
            "campaignYear": 2026,
            "catalogId": "CATALOG#c",
            "joinCode": "JOINJOINJOINJOIN1",
            "isActive": True,
            "version": 1,
            "createdAt": "t",
            "updatedAt": "t",
            "createdByAccountId": ACCOUNT_A,
            "updatedByAccountId": ACCOUNT_A,
        }
    )
    t["catalogs"].put_item(
        Item={
            "catalogId": "CATALOG#c",
            "catalogName": "Council",
            "products": CATALOG["products"],
            "version": 1,
            "createdAt": "t",
        }
    )
    t["show_and_sells"].put_item(
        Item={
            "unitCampaignId": "uc-1",
            "itemKey": "EVENT#ev-1",
            "showAndSellId": "ev-1",
            "saleId": "ev-1",
            "unitId": "unit-1",
            "locationName": "Store",
            "startAt": _grid(NOW).isoformat().replace("+00:00", "Z"),
            "endAt": (_grid(NOW) + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
            "status": "SCHEDULED",
            "splitMethod": "EQUAL",
            "weOweEnabled": True,
            "version": 1,
            "createdByAccountId": ACCOUNT_A,
            "createdAt": "t",
            "updatedAt": "t",
        }
    )
    for product_id in ("PROD#1", "PROD#2"):
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"BALANCE#{product_id}",
                "productId": product_id,
                "kernelPhysicalQty": 100,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#ev-1#{product_id}",
                "productId": product_id,
                "showAndSellId": "ev-1",
                "eventStartAt": "t",
                "eventEndAt": "t",
                "status": "OPEN",
                "allocatedQty": 10,
                "soldQty": 0,
                "releasedQty": 0,
                "remainingQty": 10,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )


def _ev(field: str, args: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {"arguments": args, "identity": {"sub": sub, "username": sub}, "info": {"fieldName": field}}


def _sale_args(key: str, lines: Any, **extra: Any) -> Dict[str, Any]:
    return {
        "showAndSellId": "ev-1",
        "expectedEventVersion": 1,
        "saleAt": SALE_AT,
        "lineItems": lines,
        "paymentMethod": {"methodCode": "CASH"},
        "idempotencyKey": key,
        **extra,
    }


def _create_sale(t: Dict[str, Any], key: str = "sale-create1", lines: Any = None, **extra: Any) -> Dict[str, Any]:
    _seed(t)
    if lines is None:
        lines = [{"productId": "PROD#1", "immediateQty": 3, "weOweQty": 2}]
    return handler(_ev("createShowAndSellSale", _sale_args(key, lines, **extra)), None)


class TestCreateSale:
    def test_immediate_handoff_and_we_owe_no_allocation(self, t: Dict[str, Any]) -> None:
        result = _create_sale(t)
        sale = result["sale"]
        assert sale["status"] == "ACTIVE" and sale["revision"] == 1
        line = sale["lineItems"][0]
        assert line["immediateQty"] == 3 and line["weOweQty"] == 2
        assert line["unitPriceCentsSnapshot"] == 500  # 5.00 dollars
        assert sale["totalCents"] == 2500
        # Immediate drew the allocation; We-Owe consumed NONE of it.
        alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "ALLOC#ev-1#PROD#1"})["Item"]
        assert alloc["remainingQty"] == 7 and alloc["soldQty"] == 3
        # We-Owe obligation minted.
        obligations = result["weOweObligations"]
        assert len(obligations) == 1
        assert obligations[0]["originalQty"] == 2 and obligations[0]["remainingQty"] == 2
        assert obligations[0]["valueCentsSnapshot"] == 1000

    def test_replay(self, t: Dict[str, Any]) -> None:
        first = _create_sale(t, key="sale-replay1")
        second = _create_sale(t, key="sale-replay1")
        assert second == first

    def test_insufficient_allocation_conflicts(self, t: Dict[str, Any]) -> None:
        result = _create_sale(t, lines=[{"productId": "PROD#1", "immediateQty": 11, "weOweQty": 0}])
        assert result["errorCode"] == ErrorCode.CONFLICT
        # Nothing partial landed.
        assert t["show_and_sells"].scan()["Count"] == 1  # only the EVENT row

    def test_validation(self, t: Dict[str, Any]) -> None:
        _seed(t)
        no_lines = handler(_ev("createShowAndSellSale", _sale_args("sale-vl-01", [])), None)
        assert no_lines["errorCode"] == ErrorCode.INVALID_INPUT
        bad_product = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args("sale-vl-02", [{"productId": "PROD#nope", "immediateQty": 1, "weOweQty": 0}]),
            ),
            None,
        )
        assert bad_product["errorCode"] == ErrorCode.INVALID_INPUT
        missing_payment = handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "expectedEventVersion": 1,
                    "saleAt": SALE_AT,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sale-vl-03",
                },
            ),
            None,
        )
        assert missing_payment["errorCode"] == ErrorCode.INVALID_INPUT


class TestCorrectionAndVoid:
    def test_absolute_target_correction(self, t: Dict[str, Any]) -> None:
        created = _create_sale(t)
        sale = created["sale"]
        line = sale["lineItems"][0]
        corrected = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "saleAt": SALE_AT,
                    "lineItems": [
                        {"lineItemId": line["lineItemId"], "productId": "PROD#1", "immediateQty": 1, "weOweQty": 4}
                    ],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "buyer changed mind",
                    "idempotencyKey": "sale-corr-01",
                },
            ),
            None,
        )
        new_sale = corrected["sale"]
        assert new_sale["revision"] == 2
        assert new_sale["lineItems"][0]["immediateQty"] == 1
        assert new_sale["lineItems"][0]["weOweQty"] == 4
        assert len(new_sale["priorRevisions"]) == 1
        assert new_sale["priorRevisions"][0]["revision"] == 1
        # Allocation net: drew 3, returned 2 -> remaining 9.
        alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "ALLOC#ev-1#PROD#1"})["Item"]
        assert alloc["remainingQty"] == 9 and alloc["soldQty"] == 1
        # Obligation target moved 2 -> 4.
        obligation = corrected["weOweObligations"][0]
        assert obligation["originalQty"] == 4 and obligation["remainingQty"] == 4

    def test_correction_can_drop_a_line(self, t: Dict[str, Any]) -> None:
        created = _create_sale(t)
        sale = created["sale"]
        # Correct to a DIFFERENT product: the old line fully releases.
        corrected = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "saleAt": SALE_AT,
                    "lineItems": [{"productId": "PROD#2", "immediateQty": 2, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "swap",
                    "idempotencyKey": "sale-corr-02",
                },
            ),
            None,
        )
        assert corrected["sale"]["lineItems"][0]["productId"] == "PROD#2"
        old_alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "ALLOC#ev-1#PROD#1"})["Item"]
        assert old_alloc["remainingQty"] == 10 and old_alloc["soldQty"] == 0
        assert corrected["weOweObligations"][0]["cancelledQty"] == 2

    def test_void_returns_stock_and_cancels(self, t: Dict[str, Any]) -> None:
        created = _create_sale(t)
        sale = created["sale"]
        voided = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "reason": "walked away",
                    "idempotencyKey": "sale-void-01",
                },
            ),
            None,
        )
        assert voided["sale"]["status"] == "VOIDED"
        assert voided["sale"]["voidReason"] == "walked away"
        alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "ALLOC#ev-1#PROD#1"})["Item"]
        assert alloc["remainingQty"] == 10 and alloc["soldQty"] == 0
        assert voided["weOweObligations"][0]["cancelledQty"] == 2
        # Double void blocked.
        again = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 2,
                    "expectedEventVersion": 3,
                    "reason": "again",
                    "idempotencyKey": "sale-void-02",
                },
            ),
            None,
        )
        assert again["errorCode"] == ErrorCode.CONFLICT


class TestWeOwe:
    def _with_obligation(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _create_sale(t)
        return created["weOweObligations"][0]

    def test_reservation_target_not_delta(self, t: Dict[str, Any]) -> None:
        obligation = self._with_obligation(t)
        reserved = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": 1,
                    "expectedVersion": 1,
                    "idempotencyKey": "weow-rs-01",
                },
            ),
            None,
        )
        assert reserved["obligation"]["reservedQty"] == 1
        assert reserved["obligation"]["uncoveredQty"] == 1
        # Absolute target: re-setting to 0 RELEASES the reservation.
        released = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": 0,
                    "expectedVersion": 2,
                    "idempotencyKey": "weow-rs-02",
                },
            ),
            None,
        )
        assert released["obligation"]["reservedQty"] == 0
        assert released["obligation"]["uncoveredQty"] == 2
        over = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": 5,
                    "expectedVersion": 3,
                    "idempotencyKey": "weow-rs-03",
                },
            ),
            None,
        )
        assert over["errorCode"] == ErrorCode.CONFLICT

    def test_fulfill_from_kernel_stock(self, t: Dict[str, Any]) -> None:
        obligation = self._with_obligation(t)
        result = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 1,
                    "source": "KERNEL_STOCK",
                    "expectedVersion": 1,
                    "idempotencyKey": "weow-ff-01",
                },
            ),
            None,
        )
        assert result["obligation"]["fulfilledQty"] == 1
        assert result["obligation"]["remainingQty"] == 1
        assert result["fulfillment"]["source"] == "KERNEL_STOCK"
        assert result["inventoryPosition"]["balance"]["kernelPhysicalQty"] == 99
        # Full fulfillment closes the obligation.
        done = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 1,
                    "source": "OTHER",
                    "expectedVersion": 2,
                    "idempotencyKey": "weow-ff-02",
                },
            ),
            None,
        )
        assert done["obligation"]["status"] == "FULFILLED"
        assert done["inventoryPosition"] is None

    def test_fulfill_over_remaining_conflicts(self, t: Dict[str, Any]) -> None:
        obligation = self._with_obligation(t)
        result = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 9,
                    "source": "KERNEL_STOCK",
                    "expectedVersion": 1,
                    "idempotencyKey": "weow-ff-03",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT


class TestSaleQueries:
    def test_sales_listing_and_filters(self, t: Dict[str, Any]) -> None:
        created = _create_sale(t)
        listing = handler(_ev("showAndSellSales", {"showAndSellId": "ev-1"}), None)
        assert len(listing["items"]) == 1
        voided = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": created["sale"]["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "reason": "x",
                    "idempotencyKey": "weow-q-v01",
                },
            ),
            None,
        )
        assert voided["sale"]["status"] == "VOIDED"
        active = handler(_ev("showAndSellSales", {"showAndSellId": "ev-1", "status": "ACTIVE"}), None)
        assert active["items"] == []
        voided_list = handler(_ev("showAndSellSales", {"showAndSellId": "ev-1", "status": "VOIDED"}), None)
        assert len(voided_list["items"]) == 1

    def test_obligation_queries(self, t: Dict[str, Any]) -> None:
        created = _create_sale(t)
        obligation = created["weOweObligations"][0]
        one = handler(_ev("weOweObligation", {"weOweId": obligation["weOweId"]}), None)
        assert one["weOweId"] == obligation["weOweId"]
        listed = handler(_ev("weOweObligations", {"unitCampaignId": "uc-1", "productId": "PROD#1"}), None)
        assert len(listed["items"]) == 1
        by_buyer = handler(_ev("weOweObligations", {"unitCampaignId": "uc-1", "buyerName": "nobody"}), None)
        assert by_buyer["items"] == []
        missing = handler(_ev("weOweObligation", {"weOweId": "WEOWE#ghost"}), None)
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
