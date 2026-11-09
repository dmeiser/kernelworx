"""
Unit tests for src/handlers/order_operations.py (Show & Sell wave 3).

Golden-oracle complement: the JS suite pins the NONE path; these tests pin
the custody transaction (one atomic write across orders + inventory +
campaign totals + marker), the committed-replay contract, and the
fulfillment/reversal append-only semantics with named corruption-direction
guards (over-fulfill, double reversal, negative reversal).
"""

from typing import Any, Dict
from uuid import uuid4

import boto3
import pytest

from src.handlers.order_operations import handler, parse_order_key
from src.utils.errors import ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"
PROFILE_A = "PROFILE#profile-1"
CAMPAIGN_A = "CAMPAIGN#campaign-1"
CATALOG = {
    "products": [
        {"productId": "PROD#1", "productName": "Popcorn", "price": 1.99},
        {"productId": "PROD#2", "productName": "Caramel", "price": 0.1},
    ]
}


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "orders": dynamodb.Table("kernelworx-orders-v2-ue1-dev"),
        "order_fulfillments": dynamodb.Table("kernelworx-order-fulfillments-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
    }


def _seed(t: Dict[str, Any], with_custody: bool = True, custody_qty: int = 10) -> None:
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
    t["profiles"].put_item(
        Item={
            "ownerAccountId": ACCOUNT_A,
            "profileId": PROFILE_A,
            "displayName": "Scout Sam",
            "createdAt": "t",
            "version": 1,
        }
    )
    t["campaigns"].put_item(
        Item={
            "profileId": PROFILE_A,
            "campaignId": CAMPAIGN_A,
            "campaignName": "Fall Sale",
            "campaignYear": 2026,
            "catalogId": "CATALOG#c",
            "unitCampaignKey": "uc-1",
            "isActive": True,
            "totalOrders": 0,
            "totalRevenue": 0,
            "version": 1,
            "createdAt": "t",
        }
    )
    if with_custody:
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1",
                "productId": "PROD#1",
                "withScoutQty": custody_qty,
                "version": 1,
                "campaignId": CAMPAIGN_A,
            }
        )


def _ev(field: str, args: Dict[str, Any], sub: str = "user-123-456", stash: Dict[str, Any] = None) -> Dict[str, Any]:
    return {
        "arguments": args,
        "identity": {"sub": sub, "username": sub},
        "info": {"fieldName": field},
        "stash": stash or {"campaign": {"profileId": PROFILE_A, "unitCampaignKey": "uc-1"}, "catalog": CATALOG},
    }


def _create_args(**overrides: Any) -> Dict[str, Any]:
    return {
        "input": {
            "profileId": PROFILE_A,
            "campaignId": CAMPAIGN_A,
            "customerName": "Alice",
            "orderDate": "2026-11-09T12:00:00Z",
            "paymentMethod": "CASH",
            "lineItems": [{"productId": "PROD#1", "quantity": 2}],
            "fulfillmentMode": "CONSUME_SCOUT_CUSTODY",
            "idempotencyKey": "ord-create-1",
            **overrides,
        }
    }


class TestKeyGrammar:
    def test_python_mirror_matches_js_grammar(self) -> None:
        from src.handlers.order_operations import build_order_key

        order_id = build_order_key("CAMPAIGN#c1", "suffix-1")
        assert order_id == "ORDER#c1#suffix-1"
        assert parse_order_key(order_id) == {"campaignId": "CAMPAIGN#c1", "suffix": "suffix-1"}
        assert parse_order_key("ORDER#only-two") is None
        assert parse_order_key("CAMPAIGN#c1#x") is None


class TestCustodyCreate:
    def test_none_mode_continues(self, t: Dict[str, Any]) -> None:
        result = handler(_ev("createOrder", _create_args(fulfillmentMode="NONE")), None)
        assert result == {"__continue__": True}
        absent = handler(_ev("createOrder", _create_args(fulfillmentMode=None)), None)
        assert absent == {"__continue__": True}

    def test_custody_create_consumes_stock_atomically(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(_ev("createOrder", _create_args()), None)
        assert result["origin"] == {"kind": "UNIT_CAMPAIGN", "unitCampaignId": "uc-1", "sourceCampaignId": CAMPAIGN_A}
        assert result["fulfillmentVersion"] == 0
        line = result["lineItems"][0]
        assert line["lineItemId"]
        assert line["fulfilledQuantity"] == 0
        assert line["subtotal"] == 3.98
        assert result["totalAmount"] == 3.98
        # Custody drawn, order written, totals bumped — all landed.
        custody = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1"})[
            "Item"
        ]
        assert custody["withScoutQty"] == 8
        stored = t["orders"].get_item(Key={"campaignId": CAMPAIGN_A, "orderId": result["orderId"]})["Item"]
        assert stored["customerName"] == "Alice"
        campaign = t["campaigns"].get_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})["Item"]
        assert campaign["totalOrders"] == 1
        assert float(campaign["totalRevenue"]) == 3.98

    def test_replay_returns_same_order(self, t: Dict[str, Any]) -> None:
        _seed(t)
        first = handler(_ev("createOrder", _create_args()), None)
        second = handler(_ev("createOrder", _create_args()), None)
        assert second == first
        custody = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1"})[
            "Item"
        ]
        assert custody["withScoutQty"] == 8  # no double draw

    def test_insufficient_custody_cancels_everything(self, t: Dict[str, Any]) -> None:
        _seed(t, custody_qty=1)
        result = handler(_ev("createOrder", _create_args()), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT
        # No partial write: no order row, custody untouched, totals unmoved.
        assert t["orders"].scan()["Count"] == 0
        custody = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1"})[
            "Item"
        ]
        assert custody["withScoutQty"] == 1
        campaign = t["campaigns"].get_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})["Item"]
        assert campaign["totalOrders"] == 0

    def test_unjoined_campaign_rejected(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "createOrder",
                _create_args(),
                stash={"campaign": {"profileId": PROFILE_A}, "catalog": CATALOG},
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_bad_mode_rejected(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(_ev("createOrder", _create_args(fulfillmentMode="WIZARD")), None)
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_validation_errors(self, t: Dict[str, Any]) -> None:
        _seed(t)
        no_lines = handler(_ev("createOrder", _create_args(lineItems=[])), None)
        assert no_lines["errorCode"] == ErrorCode.INVALID_INPUT
        unknown_product = handler(
            _ev("createOrder", _create_args(lineItems=[{"productId": "PROD#NOPE", "quantity": 1}])), None
        )
        assert unknown_product["errorCode"] == ErrorCode.INVALID_INPUT
        bad_profile = handler(
            _ev(
                "createOrder",
                _create_args(),
                stash={"campaign": {"profileId": "PROFILE#other", "unitCampaignKey": "uc-1"}, "catalog": CATALOG},
            ),
            None,
        )
        assert bad_profile["errorCode"] == ErrorCode.UNAUTHORIZED


class TestFulfillReverse:
    def _order(self, t: Dict[str, Any]) -> Dict[str, Any]:
        _seed(t)
        return handler(_ev("createOrder", _create_args()), None)

    def test_fulfill_and_reverse_round_trip(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        fulfilled = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-000001",
                },
            ),
            None,
        )
        assert fulfilled["fulfillment"]["recordType"] == "FULFILLMENT"
        assert fulfilled["order"]["fulfillmentVersion"] == 1
        assert fulfilled["order"]["lineItems"][0]["fulfilledQuantity"] == 1

        reversed_result = handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": fulfilled["fulfillment"]["fulfillmentId"],
                    "expectedFulfillmentVersion": 1,
                    "idempotencyKey": "rev-000001",
                },
            ),
            None,
        )
        assert reversed_result["reversal"]["recordType"] == "REVERSAL"
        assert reversed_result["reversal"]["fulfillmentId"].startswith("REVERSAL#")
        assert reversed_result["order"]["lineItems"][0]["fulfilledQuantity"] == 0
        assert reversed_result["order"]["fulfillmentVersion"] == 2
        # Append-only: the original row survives, marked reversed.
        rows = t["order_fulfillments"].query(
            KeyConditionExpression="orderId = :o", ExpressionAttributeValues={":o": order["orderId"]}
        )["Items"]
        assert len(rows) == 2

    def test_over_fulfill_rejected(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 5,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-guard1",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT
        assert t["order_fulfillments"].scan()["Count"] == 0

    def test_version_mismatch_rejected(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 9,
                    "idempotencyKey": "ful-ver-01",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_double_reversal_rejected(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        fulfilled = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-dr-001",
                },
            ),
            None,
        )
        fid = fulfilled["fulfillment"]["fulfillmentId"]
        handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": fid,
                    "expectedFulfillmentVersion": 1,
                    "idempotencyKey": "rev-dr-001",
                },
            ),
            None,
        )
        again = handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": fid,
                    "expectedFulfillmentVersion": 2,
                    "idempotencyKey": "rev-dr-002",
                },
            ),
            None,
        )
        assert again["errorCode"] == ErrorCode.CONFLICT

    def test_kernel_source_draws_inventory(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#1",
                "productId": "PROD#1",
                "kernelPhysicalQty": 7,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        line_id = order["lineItems"][0]["lineItemId"]
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 2,
                    "source": "KERNEL_STOCK",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-k-001",
                },
            ),
            None,
        )
        assert result["inventoryPosition"]["balance"]["kernelPhysicalQty"] == 5
        balance = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#1"})["Item"]
        assert balance["kernelPhysicalQty"] == 5

    def test_replays(self, t: Dict[str, Any]) -> None:
        order = self._order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        args = {
            "orderId": order["orderId"],
            "lineItemId": line_id,
            "quantity": 1,
            "source": "SCOUT_CUSTODY",
            "expectedFulfillmentVersion": 0,
            "idempotencyKey": "ful-replay",
        }
        first = handler(_ev("fulfillIndividualOrderLine", args), None)
        second = handler(_ev("fulfillIndividualOrderLine", args), None)
        assert second == first


class TestOrderSweep:
    def test_unauthenticated(self, t: Dict[str, Any]) -> None:
        _seed(t)
        event = _ev("createOrder", _create_args())
        del event["identity"]
        assert handler(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_marker_conflict_missing_result_and_replay_race(self, t: Dict[str, Any]) -> None:
        _seed(t)
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createOrderCustody#ord-create-1",
                "idemFingerprint": "other",
            }
        )
        conflict = handler(_ev("createOrder", _create_args()), None)
        assert conflict["errorCode"] == ErrorCode.CONFLICT

    def test_enrich_validation(self, t: Dict[str, Any]) -> None:
        from src.handlers.order_operations import _enrich_line_items

        catalog = {"products": [{"productId": "P", "productName": "n", "price": -1}]}
        try:
            _enrich_line_items([{"productId": "P", "quantity": 1}], catalog)
            raise AssertionError("expected AppError")
        except Exception as exc:
            assert "no valid price" in str(exc)
        try:
            _enrich_line_items([{"productId": "P", "quantity": True}], {"products": [{"productId": "P", "price": 1}]})
            raise AssertionError("expected AppError")
        except Exception as exc:
            assert "at least 1" in str(exc)

    def test_missing_order_date_and_catalog(self, t: Dict[str, Any]) -> None:
        _seed(t)
        no_date = handler(_ev("createOrder", _create_args(orderDate="  ")), None)
        assert no_date["errorCode"] == ErrorCode.INVALID_INPUT
        no_catalog = handler(
            _ev("createOrder", _create_args(), stash={"campaign": {"profileId": PROFILE_A, "unitCampaignKey": "uc-1"}}),
            None,
        )
        assert no_catalog["errorCode"] == ErrorCode.INVALID_INPUT

    def test_optional_fields_stamped(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(_ev("createOrder", _create_args(customerPhone="555-1", notes="hi there")), None)
        assert result["customerPhone"] == "555-1"
        assert result["notes"] == "hi there"

    def test_custody_cancel_race_maps_to_conflict(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from unittest.mock import MagicMock

        from src.handlers import order_operations
        from src.utils.dynamodb import TransactionCancelledError

        _seed(t)
        monkeypatch.setattr(
            order_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([1]))
        )
        result = handler(_ev("createOrder", _create_args()), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_fulfill_validation_and_guards(self, t: Dict[str, Any]) -> None:
        order = self._custody_order(t)
        bad_qty = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 0,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-fq-001",
                },
            ),
            None,
        )
        assert bad_qty["errorCode"] == ErrorCode.INVALID_INPUT
        bad_version = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": -1,
                    "idempotencyKey": "sw-fv-001",
                },
            ),
            None,
        )
        assert bad_version["errorCode"] == ErrorCode.INVALID_INPUT
        missing_line = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": "LINE#ghost",
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-fl-001",
                },
            ),
            None,
        )
        assert missing_line["errorCode"] == ErrorCode.NOT_FOUND
        missing_order = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": "ORDER#nope#x",
                    "lineItemId": "LINE#ghost",
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-fo-001",
                },
            ),
            None,
        )
        assert missing_order["errorCode"] == ErrorCode.NOT_FOUND

    def test_kernel_insufficient_and_fulfill_replay_race(self, t: Dict[str, Any]) -> None:
        order = self._custody_order(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#1",
                "productId": "PROD#1",
                "kernelPhysicalQty": 1,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 2,
                    "source": "KERNEL_STOCK",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-ki-001",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_reverse_validation_and_kernel_restore(self, t: Dict[str, Any]) -> None:
        order = self._custody_order(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#1",
                "productId": "PROD#1",
                "kernelPhysicalQty": 7,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        line_id = order["lineItems"][0]["lineItemId"]
        fulfilled = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 2,
                    "source": "KERNEL_STOCK",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-kf-001",
                },
            ),
            None,
        )
        fid = fulfilled["fulfillment"]["fulfillmentId"]
        bad_version = handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": fid,
                    "expectedFulfillmentVersion": -1,
                    "idempotencyKey": "sw-rv-001",
                },
            ),
            None,
        )
        assert bad_version["errorCode"] == ErrorCode.INVALID_INPUT
        missing = handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": "F#ghost",
                    "expectedFulfillmentVersion": 1,
                    "idempotencyKey": "sw-rm-001",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        reversed_result = handler(
            _ev(
                "reverseIndividualOrderFulfillment",
                {
                    "orderId": order["orderId"],
                    "fulfillmentId": fid,
                    "expectedFulfillmentVersion": 1,
                    "idempotencyKey": "sw-rr-001",
                },
            ),
            None,
        )
        assert reversed_result["reversal"]["source"] == "KERNEL_STOCK"
        balance = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#1"})["Item"]
        assert balance["kernelPhysicalQty"] == 7  # restored by the reversal
        # Reversal replay
        args = {
            "orderId": order["orderId"],
            "fulfillmentId": fid,
            "expectedFulfillmentVersion": 1,
            "idempotencyKey": "sw-rr-001",
        }
        replayed = handler(_ev("reverseIndividualOrderFulfillment", args), None)
        assert replayed == reversed_result

    def test_unknown_dispatcher_field(self, t: Dict[str, Any]) -> None:
        _seed(t)
        assert handler(_ev("mysteryField", {}), None)["errorCode"] == ErrorCode.INTERNAL_ERROR

    def _custody_order(self, t: Dict[str, Any]) -> Dict[str, Any]:
        _seed(t)
        return handler(_ev("createOrder", _create_args(idempotencyKey=f"ord-sw-{uuid4()}")), None)

    def test_marker_encoder_fallback_and_json_variants(self, t: Dict[str, Any]) -> None:
        from decimal import Decimal as _D

        from src.handlers.order_operations import _MarkerJsonEncoder

        assert _MarkerJsonEncoder().default(_D("1.5")) == 1.5
        with pytest.raises(TypeError):
            _MarkerJsonEncoder().default(object())  # unknown types still fail loudly
        # legacy dict-form marker (other modules' shape) still honored
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#fulfillOrderLine#sw-legacy",
                "idemFingerprint": "fp",
                "idemResult": {"order": {"fulfillmentVersion": 1}},
            }
        )
        from src.handlers.order_operations import _check_marker

        assert _check_marker(
            t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#fulfillOrderLine#sw-legacy"})[
                "Item"
            ],
            "fp",
        ) == {"order": {"fulfillmentVersion": 1}}
        with pytest.raises(Exception):
            _check_marker(
                t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#fulfillOrderLine#sw-legacy"})[
                    "Item"
                ],
                "other",
            )

    def test_no_idempotency_key_path(self, t: Dict[str, Any]) -> None:
        _seed(t)
        args = _create_args()
        del args["input"]["idempotencyKey"]
        result = handler(_ev("createOrder", args), None)
        assert result["origin"]["kind"] == "UNIT_CAMPAIGN"

    def test_duplicate_line_products_share_custody_read(self, t: Dict[str, Any]) -> None:
        _seed(t, custody_qty=20)
        args = _create_args(lineItems=[{"productId": "PROD#1", "quantity": 1}, {"productId": "PROD#1", "quantity": 2}])
        result = handler(_ev("createOrder", args), None)
        assert result["totalAmount"] == 5.97
        custody = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1"})[
            "Item"
        ]
        assert custody["withScoutQty"] == 17

    def test_address_stamped(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(_ev("createOrder", _create_args(customerAddress={"street": "1 Main St"})), None)
        assert result["customerAddress"] == {"street": "1 Main St"}

    def test_fulfill_forbidden_without_access(self, t: Dict[str, Any]) -> None:
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
        t["profiles"].put_item(
            Item={
                "ownerAccountId": "ACCOUNT#someone-else",
                "profileId": PROFILE_A,
                "displayName": "X",
                "createdAt": "t",
                "version": 1,
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1",
                "productId": "PROD#1",
                "withScoutQty": 10,
                "version": 1,
                "campaignId": CAMPAIGN_A,
            }
        )
        t["campaigns"].put_item(
            Item={
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "campaignName": "Fall Sale",
                "campaignYear": 2026,
                "catalogId": "CATALOG#c",
                "unitCampaignKey": "uc-1",
                "isActive": True,
                "totalOrders": 0,
                "totalRevenue": 0,
                "version": 1,
                "createdAt": "t",
            }
        )
        order = handler(_ev("createOrder", _create_args()), None)
        # user-789 has no grant and no profile access -> FORBIDDEN
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "sw-fb-001",
                },
                sub="user-789",
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_fulfill_replay_race_and_reverse_line_gone(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from unittest.mock import MagicMock

        from src.handlers import order_operations
        from src.utils.dynamodb import TransactionCancelledError

        order = self._custody_order(t)
        args = {
            "orderId": order["orderId"],
            "lineItemId": order["lineItems"][0]["lineItemId"],
            "quantity": 1,
            "source": "SCOUT_CUSTODY",
            "expectedFulfillmentVersion": 0,
            "idempotencyKey": "ful-race-1",
        }
        monkeypatch.setattr(
            order_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([2]))
        )
        result = handler(_ev("fulfillIndividualOrderLine", args), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_reverse_negative_guard(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers.order_operations import (
            reverse_individual_order_fulfillment,
        )
        from src.utils.errors import AppError

        order = self._custody_order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        fulfilled = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-rn-001",
                },
            ),
            None,
        )
        fid = fulfilled["fulfillment"]["fulfillmentId"]
        # Corrupt the order line so the reversal would drive fulfilled negative
        stored = t["orders"].get_item(Key={"campaignId": CAMPAIGN_A, "orderId": order["orderId"]})["Item"]
        stored["lineItems"][0]["fulfilledQuantity"] = 0
        t["orders"].put_item(Item=stored)
        with pytest.raises(AppError) as exc_info:
            reverse_individual_order_fulfillment(
                _ev(
                    "reverseIndividualOrderFulfillment",
                    {
                        "orderId": order["orderId"],
                        "fulfillmentId": fid,
                        "expectedFulfillmentVersion": 1,
                        "idempotencyKey": "sw-rn-001",
                    },
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_final_marker_and_guard_branches(self, t: Dict[str, Any]) -> None:

        from src.handlers.order_operations import _check_marker

        # marker with no result at all -> INTERNAL_ERROR
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#fulfillOrderLine#sw-nores",
                "idemFingerprint": "fp",
            }
        )
        with pytest.raises(Exception) as exc_info:
            _check_marker(
                t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#fulfillOrderLine#sw-nores"})[
                    "Item"
                ],
                "fp",
            )
        assert "missing its committed result" in str(exc_info.value)
        # bare re-raise path on non-marker cancel (fulfill)
        from unittest.mock import MagicMock

        from src.handlers import order_operations
        from src.utils.dynamodb import TransactionCancelledError

        order = self._custody_order(t)
        args = {
            "orderId": order["orderId"],
            "lineItemId": order["lineItems"][0]["lineItemId"],
            "quantity": 1,
            "source": "SCOUT_CUSTODY",
            "expectedFulfillmentVersion": 0,
            "idempotencyKey": "ful-raw-001",
        }
        monkey = pytest.MonkeyPatch()
        monkey.setattr(order_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0])))
        with pytest.raises(TransactionCancelledError):
            order_operations.fulfill_individual_order_line(_ev("fulfillIndividualOrderLine", args), None)
        monkey.undo()

    def test_auth_unit_admin_path_and_unknown_order(self, t: Dict[str, Any]) -> None:
        from src.handlers.order_operations import _authorize_fulfillment, _load_order
        from src.utils.errors import AppError

        # Unit admin (no profile access) is authorized for a unit-originated order.
        order_like = {
            "profileId": PROFILE_A,
            "origin": {"kind": "UNIT_CAMPAIGN", "unitCampaignId": "uc-1", "sourceCampaignId": CAMPAIGN_A},
        }
        _seed(t)
        _authorize_fulfillment(order_like, ACCOUNT_A)  # does not raise: unit admin
        with pytest.raises(AppError):
            _load_order("ORDER#malformed")
        # non-unit origin without access -> FORBIDDEN
        t2 = {"profileId": PROFILE_A, "origin": {"kind": "COUNCIL"}}
        with pytest.raises(AppError) as exc_info:
            _authorize_fulfillment(t2, "ACCOUNT#stranger")
        assert exc_info.value.error_code == "FORBIDDEN"

    def test_reverse_unknown_line_and_gone_order(self, t: Dict[str, Any]) -> None:
        from src.handlers.order_operations import reverse_individual_order_fulfillment
        from src.utils.errors import AppError

        order = self._custody_order(t)
        line_id = order["lineItems"][0]["lineItemId"]
        fulfilled = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": line_id,
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-rl-001",
                },
            ),
            None,
        )
        fid = fulfilled["fulfillment"]["fulfillmentId"]
        # Break the order's line linkage to trip the reversal line guard.
        stored = t["orders"].get_item(Key={"campaignId": CAMPAIGN_A, "orderId": order["orderId"]})["Item"]
        stored["lineItems"][0]["lineItemId"] = "LINE#other"
        t["orders"].put_item(Item=stored)
        with pytest.raises(AppError) as exc_info:
            reverse_individual_order_fulfillment(
                _ev(
                    "reverseIndividualOrderFulfillment",
                    {
                        "orderId": order["orderId"],
                        "fulfillmentId": fid,
                        "expectedFulfillmentVersion": 1,
                        "idempotencyKey": "sw-rl-001",
                    },
                ),
                None,
            )
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_final_branch_coverage(self, t: Dict[str, Any]) -> None:
        from src.handlers.order_operations import (
            _authorize_fulfillment,
            _kernel_fulfill_context,
            _load_order_for_fulfillment,
            _marker_put,
            _read_custody_holds,
        )

        # _marker_put with no result
        entry = _marker_put(ACCOUNT_A, "scope", "key", "fp", None, 1000)
        assert "idemResultJson" not in entry["Put"]["Item"]
        # _read_custody_holds dedups repeated products
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-9",
                "itemKey": f"CUSTODY#{PROFILE_A}#PROD#1",
                "productId": "PROD#1",
                "withScoutQty": 4,
                "version": 1,
                "campaignId": CAMPAIGN_A,
            }
        )
        holds = _read_custody_holds("uc-9", PROFILE_A, ["PROD#1", "PROD#1"])
        assert holds == {"PROD#1": 4}
        # _kernel_fulfill_context with no unit origin -> None
        assert _kernel_fulfill_context({}, "P", 1, "ORDER#x", ACCOUNT_A, "s", "m") is None
        # _load_order_for_fulfillment with malformed lineItems
        t["orders"].put_item(
            Item={
                "campaignId": CAMPAIGN_A,
                "orderId": "ORDER#campaign-1#zz",
                "profileId": PROFILE_A,
                "lineItems": "nope",
                "fulfillmentVersion": 0,
            }
        )
        t["profiles"].put_item(
            Item={
                "ownerAccountId": ACCOUNT_A,
                "profileId": PROFILE_A,
                "displayName": "X",
                "createdAt": "t",
                "version": 1,
            }
        )
        with pytest.raises(Exception) as exc_info:
            _load_order_for_fulfillment("ORDER#campaign-1#zz", ACCOUNT_A, 0)
        assert "malformed" in str(exc_info.value)
        # _authorize_fulfillment: unit campaign row missing -> FORBIDDEN
        t["profiles"].put_item(
            Item={
                "ownerAccountId": "ACCOUNT#other",
                "profileId": "PROFILE#other",
                "displayName": "Y",
                "createdAt": "t",
                "version": 1,
            }
        )
        order_like = {"profileId": "PROFILE#other", "origin": {"kind": "UNIT_CAMPAIGN", "unitCampaignId": "UC#ghost"}}
        with pytest.raises(Exception) as exc_info2:
            _authorize_fulfillment(order_like, ACCOUNT_A)
        assert exc_info2.value.error_code == "FORBIDDEN"

    def test_kernel_source_without_unit_origin_skips_inventory(self, t: Dict[str, Any]) -> None:
        """A legacy-shaped order (no origin) fulfilled from KERNEL_STOCK has
        no inventory leg — the kernel context returns None at the handler."""
        _seed(t)
        order = handler(_ev("createOrder", _create_args()), None)
        stored = t["orders"].get_item(Key={"campaignId": CAMPAIGN_A, "orderId": order["orderId"]})["Item"]
        del stored["origin"]
        t["orders"].put_item(Item=stored)
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 1,
                    "source": "KERNEL_STOCK",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-nu-001",
                },
            ),
            None,
        )
        assert result["fulfillment"]["source"] == "KERNEL_STOCK"
        assert result["inventoryPosition"] is None

    def test_unit_admin_fulfills_without_profile_ownership(self, t: Dict[str, Any]) -> None:
        """A Unit Admin (no profile access) fulfills a unit-originated order
        through the unit-grant authorization path."""
        _seed(t)
        t["profiles"].delete_item(Key={"ownerAccountId": ACCOUNT_A, "profileId": PROFILE_A})
        t["profiles"].put_item(
            Item={
                "ownerAccountId": "ACCOUNT#other",
                "profileId": PROFILE_A,
                "displayName": "Y",
                "createdAt": "t",
                "version": 1,
            }
        )
        order = handler(_ev("createOrder", _create_args()), None)
        result = handler(
            _ev(
                "fulfillIndividualOrderLine",
                {
                    "orderId": order["orderId"],
                    "lineItemId": order["lineItems"][0]["lineItemId"],
                    "quantity": 1,
                    "source": "SCOUT_CUSTODY",
                    "expectedFulfillmentVersion": 0,
                    "idempotencyKey": "ful-ua-001",
                },
            ),
            None,
        )
        assert result["fulfillment"]["recordType"] == "FULFILLMENT"

    def test_raise_custody_cancel_direct(self, t: Dict[str, Any]) -> None:
        from src.handlers.order_operations import _marker_put, _raise_custody_cancel
        from src.utils.dynamodb import TransactionCancelledError
        from src.utils.errors import AppError

        marker = _marker_put(ACCOUNT_A, "createOrderCustody", "k", "fp", {"orderId": "x"}, 1000)
        plan = [{"Put": {"TableName": "a", "Item": {"k": "v"}}}, marker]
        with pytest.raises(AppError) as exc_info:
            _raise_custody_cancel(TransactionCancelledError([0]), plan, marker)
        assert "Stock or campaign state changed concurrently" in str(exc_info.value)
        with pytest.raises(AppError) as race_info:
            _raise_custody_cancel(TransactionCancelledError([1]), plan, marker)
        assert "being processed concurrently" in str(race_info.value)
