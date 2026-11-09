"""
Unit tests for src/handlers/inventory_operations.py and
src/utils/inventory_derived.py (Show & Sell wave 3).

Covers the custody atomicity contract (balance + custody + movement in one
transaction), read-then-plan optimistic concurrency, sufficiency guards
with named CONFLICT reasons, committed-replay idempotency, and the §7
derived-quantity formulas.
"""

from typing import Any, Dict

import boto3
import pytest

from src.handlers.inventory_operations import handler
from src.utils.errors import ErrorCode
from src.utils.inventory_derived import derive_position

ACCOUNT_A = "ACCOUNT#user-123-456"


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


def _ev(field: str, args: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {"arguments": args, "identity": {"sub": sub, "username": sub}, "info": {"fieldName": field}}


def _receipt(t: Dict[str, Any], product: str = "P1", qty: int = 10, key: str = "rc-000001") -> Dict[str, Any]:
    return handler(
        _ev(
            "recordInventoryReceipt",
            {"unitCampaignId": "uc-1", "productId": product, "quantity": qty, "idempotencyKey": key},
        ),
        None,
    )


class TestInventoryDerived:
    def test_sellable_excludes_sold_in_possession(self) -> None:
        assert (
            derive_position(
                unit_campaign_id="uc",
                product_id="P",
                kernel_physical_qty=10,
                sold_in_possession_qty=3,
                council_on_order_qty=0,
                balance_version=1,
                allocations=[],
                custody_rows=[],
            )["sellableKernelQty"]
            == 7
        )

    def test_council_need_excludes_with_scout_and_on_order(self) -> None:
        position = derive_position(
            unit_campaign_id="uc",
            product_id="P",
            kernel_physical_qty=5,
            sold_in_possession_qty=0,
            council_on_order_qty=4,
            balance_version=1,
            allocations=[],
            custody_rows=[{"withScoutQty": 6}],
            unfulfilled_individual_qty=8,
        )
        # Demand 8, sellable 5 -> physical need 3; withScout 6 is NOT demand.
        assert position["physicalStockCouncilNeedQty"] == 3
        assert position["withScoutQty"] == 6
        assert position["totalUnitOwnedUndeliveredQty"] == 11

    def test_assignment_overage(self) -> None:
        position = derive_position(
            unit_campaign_id="uc",
            product_id="P",
            kernel_physical_qty=2,
            sold_in_possession_qty=0,
            council_on_order_qty=0,
            balance_version=1,
            allocations=[{"remainingQty": 5, "status": "OPEN"}],
            custody_rows=[],
        )
        assert position["assignedOpenQty"] == 5
        assert position["assignmentOverageQty"] == 3
        assert position["unassignedKernelQty"] == 0


class TestRecordReceipt:
    def test_creates_balance_and_movement(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = _receipt(t)
        assert result["balance"]["kernelPhysicalQty"] == 10
        assert result["sellableKernelQty"] == 10
        movements = [
            i for i in t["inventory"].scan()["Items"] if i["itemKey"].startswith("MOVEMENT#") and i["productId"] == "P1"
        ]
        assert len(movements) == 1
        assert movements[0]["kernelPhysicalDelta"] == 10
        assert movements[0]["movementType"] == "RECEIPT"

    def test_replay_no_double_count(self, t: Dict[str, Any]) -> None:
        _seed(t)
        first = _receipt(t, key="rc-replay1")
        second = _receipt(t, key="rc-replay1")
        assert second == first
        assert second["balance"]["kernelPhysicalQty"] == 10

    def test_custom_occurred_at(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "recordInventoryReceipt",
                {
                    "unitCampaignId": "uc-1",
                    "productId": "P1",
                    "quantity": 5,
                    "occurredAt": "2026-10-01T12:00:00Z",
                    "idempotencyKey": "rc-custom1",
                },
            ),
            None,
        )
        assert result["balance"]["kernelPhysicalQty"] == 5


class TestAdjustInventory:
    def test_negative_guard_named_conflict(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=3)
        result = handler(
            _ev(
                "adjustInventory",
                {
                    "unitCampaignId": "uc-1",
                    "productId": "P1",
                    "quantityDelta": -5,
                    "reason": "shrink",
                    "idempotencyKey": "adj-guard1",
                },
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_adjust_round_trip(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        result = handler(
            _ev(
                "adjustInventory",
                {
                    "unitCampaignId": "uc-1",
                    "productId": "P1",
                    "quantityDelta": -4,
                    "reason": "damaged",
                    "idempotencyKey": "adj-round1",
                },
            ),
            None,
        )
        assert result["balance"]["kernelPhysicalQty"] == 6

    def test_zero_delta_rejected(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "adjustInventory",
                {
                    "unitCampaignId": "uc-1",
                    "productId": "P1",
                    "quantityDelta": 0,
                    "reason": "noop",
                    "idempotencyKey": "adj-zero-1",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT


class TestAdjustCouncilOnOrder:
    def test_council_bucket_separate_from_kernel(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        result = handler(
            _ev(
                "adjustCouncilOnOrder",
                {
                    "unitCampaignId": "uc-1",
                    "productId": "P1",
                    "quantityDelta": 7,
                    "idempotencyKey": "council-001",
                },
            ),
            None,
        )
        assert result["balance"]["councilOnOrderQty"] == 7
        assert result["balance"]["kernelPhysicalQty"] == 10
        assert result["sellableKernelQty"] == 10  # on-order never reduces council need


class TestCustody:
    def test_issue_moves_stock_atomically(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        result = handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 4,
                    "idempotencyKey": "iss-000001",
                },
            ),
            None,
        )
        assert result["inventoryPosition"]["balance"]["kernelPhysicalQty"] == 6
        assert result["custodyBalance"]["withScoutQty"] == 4
        movement = next(
            i
            for i in t["inventory"].scan()["Items"]
            if i["itemKey"].startswith("MOVEMENT#") and i["movementType"] == "ISSUE"
        )
        assert movement["withScoutDelta"] == 4
        assert movement["kernelPhysicalDelta"] == -4

    def test_issue_insufficient_conflict(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=2)
        result = handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 9,
                    "idempotencyKey": "iss-guard1",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_return_moves_back(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 4,
                    "idempotencyKey": "iss-ret-01",
                },
            ),
            None,
        )
        result = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": [{"productId": "P1", "quantity": 3}],
                    "idempotencyKey": "ret-000001",
                },
            ),
            None,
        )
        assert result["custodyBalances"][0]["withScoutQty"] == 1
        assert result["inventoryPositions"][0]["balance"]["kernelPhysicalQty"] == 9

    def test_return_duplicate_product_rejected(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": [{"productId": "P1", "quantity": 1}, {"productId": "P1", "quantity": 1}],
                    "idempotencyKey": "ret-dup-01",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_issue_replay(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        args = {
            "unitCampaignId": "uc-1",
            "campaignId": "CAMP#1",
            "profileId": "PROF#1",
            "productId": "P1",
            "quantity": 4,
            "idempotencyKey": "iss-replay",
        }
        first = handler(_ev("issueStockToScout", args), None)
        second = handler(_ev("issueStockToScout", args), None)
        assert second == first
        assert second["custodyBalance"]["withScoutQty"] == 4


class TestAuthorization:
    def test_non_admin_blocked(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "recordInventoryReceipt",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 1, "idempotencyKey": "auth-0001"},
                sub="user-789",
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_unknown_operation(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(_ev("mysteryOp", {}), None)
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
    }


class TestInventorySweep:
    def test_marker_conflict_and_missing_result(self, t: Dict[str, Any]) -> None:
        _seed(t)
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#recordInventoryReceipt#sw-mk-01",
                "idemFingerprint": "different",
                "idemResult": {},
            }
        )
        conflict = handler(
            _ev(
                "recordInventoryReceipt",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 1, "idempotencyKey": "sw-mk-01"},
            ),
            None,
        )
        assert conflict["errorCode"] == ErrorCode.CONFLICT

    def test_unauthenticated(self, t: Dict[str, Any]) -> None:
        _seed(t)
        event = _ev(
            "recordInventoryReceipt",
            {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 1, "idempotencyKey": "sw-un-001"},
        )
        del event["identity"]
        assert handler(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_unknown_unit_campaign(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "recordInventoryReceipt",
                {"unitCampaignId": "UC#ghost", "productId": "P1", "quantity": 1, "idempotencyKey": "sw-uc-001"},
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_cancel_mapping_and_reraise(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from unittest.mock import MagicMock

        from src.handlers import inventory_operations
        from src.utils.dynamodb import TransactionCancelledError
        from src.utils.errors import AppError

        _seed(t)
        monkeypatch.setattr(
            inventory_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([2]))
        )
        with pytest.raises(AppError) as exc_info:
            inventory_operations._record_inventory_receipt(
                _ev(
                    "recordInventoryReceipt",
                    {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 1, "idempotencyKey": "sw-race-01"},
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"
        monkeypatch.setattr(
            inventory_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(TransactionCancelledError):
            inventory_operations._record_inventory_receipt(
                _ev(
                    "recordInventoryReceipt",
                    {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 1, "idempotencyKey": "sw-raw-001"},
                ),
                None,
            )

    def test_position_reads_related_rows(self, t: Dict[str, Any]) -> None:
        from src.handlers.inventory_operations import _position

        _seed(t)
        _receipt(t, qty=10)
        handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 4,
                    "idempotencyKey": "sw-pos-001",
                },
            ),
            None,
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "ALLOC#SS#P1",
                "productId": "P1",
                "remainingQty": 2,
                "status": "OPEN",
            }
        )
        position = _position("uc-1", "P1")
        assert position["withScoutQty"] == 4
        assert position["assignedOpenQty"] == 2

    def test_balance_entry_sold_delta_and_movement_order(self, t: Dict[str, Any]) -> None:
        from src.handlers.inventory_operations import _balance_entry, _movement

        entry = _balance_entry("uc-1", "P1", 3, kernel_delta=1, sold_delta=2, council_delta=1, stamp="s")
        assert "soldInPossessionQty" in entry["Update"]["UpdateExpression"]
        assert entry["Update"]["ExpressionAttributeValues"][":sd"] == 2
        movement = _movement(
            unit_campaign_id="uc-1",
            product_id="P1",
            occurred_at="s",
            movement_type="X",
            actor=ACCOUNT_A,
            inventory_version=1,
            order_id="ORDER#1",
        )
        assert movement["orderId"] == "ORDER#1"

    def test_receipt_nonpositive_quantity(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "recordInventoryReceipt",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantity": 0, "idempotencyKey": "sw-q-0001"},
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_adjust_replay_and_council_negative(self, t: Dict[str, Any]) -> None:
        _seed(t)
        args = {
            "unitCampaignId": "uc-1",
            "productId": "P1",
            "quantityDelta": 5,
            "reason": "found",
            "idempotencyKey": "sw-adj-rp",
        }
        first = handler(_ev("adjustInventory", args), None)
        second = handler(_ev("adjustInventory", args), None)
        assert second == first
        negative = handler(
            _ev(
                "adjustCouncilOnOrder",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantityDelta": -1, "idempotencyKey": "sw-cneg-1"},
            ),
            None,
        )
        assert negative["errorCode"] == ErrorCode.CONFLICT

    def test_adjust_council_replay_with_reason(self, t: Dict[str, Any]) -> None:
        _seed(t)
        args = {
            "unitCampaignId": "uc-1",
            "productId": "P1",
            "quantityDelta": 3,
            "reason": "council order placed",
            "idempotencyKey": "sw-crp-001",
        }
        first = handler(_ev("adjustCouncilOnOrder", args), None)
        second = handler(_ev("adjustCouncilOnOrder", args), None)
        assert second == first

    def test_issue_nonpositive(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 0,
                    "idempotencyKey": "sw-isq-001",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_return_replay_and_bad_items(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        handler(
            _ev(
                "issueStockToScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "productId": "P1",
                    "quantity": 4,
                    "idempotencyKey": "sw-ris-001",
                },
            ),
            None,
        )
        args = {
            "unitCampaignId": "uc-1",
            "campaignId": "CAMP#1",
            "profileId": "PROF#1",
            "items": [{"productId": "P1", "quantity": 1}],
            "idempotencyKey": "sw-rret-1",
        }
        first = handler(_ev("returnStockFromScout", args), None)
        second = handler(_ev("returnStockFromScout", args), None)
        assert second == first
        empty = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": [],
                    "idempotencyKey": "sw-rem-001",
                },
            ),
            None,
        )
        assert empty["errorCode"] == ErrorCode.INVALID_INPUT
        not_dict = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": ["nope"],
                    "idempotencyKey": "sw-rnd-001",
                },
            ),
            None,
        )
        assert not_dict["errorCode"] == ErrorCode.INVALID_INPUT

    def test_marker_missing_result_and_council_zero(self, t: Dict[str, Any]) -> None:
        import json as _json

        _seed(t)
        fingerprint = _json.dumps(
            {
                "unitCampaignId": "uc-1",
                "productId": "P1",
                "quantityDelta": 1,
                "idempotencyKey": "sw-mr-001",
                "actor": ACCOUNT_A,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#adjustCouncilOnOrder#sw-mr-001",
                "idemFingerprint": fingerprint,
            }
        )
        result = handler(
            _ev(
                "adjustCouncilOnOrder",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantityDelta": 1, "idempotencyKey": "sw-mr-001"},
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_related_rows_skips_other_products(self, t: Dict[str, Any]) -> None:
        from src.handlers.inventory_operations import _related_rows

        _seed(t)
        _receipt(t, product="P1", qty=5)
        _receipt(t, product="P2", qty=7, key="rc-000002")
        related = _related_rows("uc-1", "P1")
        assert related["custody_rows"] == []
        assert related["allocations"] == []

    def test_council_zero_delta_and_return_validation(self, t: Dict[str, Any]) -> None:
        _seed(t)
        zero = handler(
            _ev(
                "adjustCouncilOnOrder",
                {"unitCampaignId": "uc-1", "productId": "P1", "quantityDelta": 0, "idempotencyKey": "sw-zd-001"},
            ),
            None,
        )
        assert zero["errorCode"] == ErrorCode.INVALID_INPUT
        bad_qty = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": [{"productId": "P1", "quantity": 0}],
                    "idempotencyKey": "sw-rq-001",
                },
            ),
            None,
        )
        assert bad_qty["errorCode"] == ErrorCode.INVALID_INPUT

    def test_return_insufficient_custody(self, t: Dict[str, Any]) -> None:
        _seed(t)
        _receipt(t, qty=10)
        result = handler(
            _ev(
                "returnStockFromScout",
                {
                    "unitCampaignId": "uc-1",
                    "campaignId": "CAMP#1",
                    "profileId": "PROF#1",
                    "items": [{"productId": "P1", "quantity": 1}],
                    "idempotencyKey": "sw-ric-01",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT
