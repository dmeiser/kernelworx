"""Coverage sweep for src/handlers/sale_operations.py: error branches,
marker edges, guards, and replay paths."""

from typing import Any

import boto3
import pytest

from src.handlers import sale_operations
from src.handlers.sale_operations import handler
from src.utils.dynamodb import TransactionCancelledError
from src.utils.errors import AppError, ErrorCode
from tests.unit.test_sale_operations import ACCOUNT_A, SALE_AT, _create_sale, _ev, _sale_args


@pytest.fixture
def t(dynamodb_table: Any) -> Any:
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


class TestSaleSweep:
    def test_unauthorized_and_unknown(self, t: Any) -> None:
        event = _ev(
            "createShowAndSellSale", _sale_args("sw-auth-001", [{"productId": "P", "immediateQty": 1, "weOweQty": 0}])
        )
        del event["identity"]
        assert handler(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED
        assert handler(_ev("mysterySaleOp", {}), None)["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_marker_branches(self, t: Any) -> None:
        created = _create_sale(t, key="sw-mk-001")
        # Same key AND same payload replays; a same-key/different-payload
        # call is the CONFLICT case (asserted next).
        args = _sale_args("sw-mk-001", [{"productId": "PROD#1", "immediateQty": 3, "weOweQty": 2}])
        replayed = handler(_ev("createShowAndSellSale", args), None)
        assert replayed["sale"]["saleId"] == created["sale"]["saleId"]
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#voidShowAndSellSale#sw-mk-002",
                "idemFingerprint": "other",
                "idemResult": {},
            }
        )
        conflict = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": "S#x",
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "reason": "x",
                    "idempotencyKey": "sw-mk-002",
                },
            ),
            None,
        )
        assert conflict["errorCode"] == ErrorCode.CONFLICT

    def test_event_guards(self, t: Any) -> None:
        _create_sale(t, key="sw-eg-001")
        missing = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-eg-002", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], showAndSellId="SS#ghost"
                ),
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        stale_version = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-eg-003", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=9
                ),
            ),
            None,
        )
        assert stale_version["errorCode"] == ErrorCode.CONFLICT
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": "EVENT#ev-1"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        cancelled = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-eg-004", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=3
                ),
            ),
            None,
        )
        assert cancelled["errorCode"] == ErrorCode.CONFLICT

    def test_validation_branches(self, t: Any) -> None:
        _create_sale(t, key="sw-vb-001")
        bad_event_version = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-vb-002", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=-1
                ),
            ),
            None,
        )
        assert bad_event_version["errorCode"] == ErrorCode.INVALID_INPUT
        dup = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-vb-003",
                    [
                        {"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0},
                        {"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0},
                    ],
                    expectedEventVersion=3,
                ),
            ),
            None,
        )
        assert dup["errorCode"] == ErrorCode.INVALID_INPUT
        zero_line = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-vb-004", [{"productId": "PROD#1", "immediateQty": 0, "weOweQty": 0}], expectedEventVersion=3
                ),
            ),
            None,
        )
        assert zero_line["errorCode"] == ErrorCode.INVALID_INPUT
        bad_line_type = handler(
            _ev("createShowAndSellSale", _sale_args("sw-vb-005", ["nope"], expectedEventVersion=3)),
            None,
        )
        assert bad_line_type["errorCode"] == ErrorCode.INVALID_INPUT

    def test_correction_guards_and_replay(self, t: Any) -> None:
        created = _create_sale(t, key="sw-cg-001")
        sale = created["sale"]
        base = {
            "showAndSellId": "ev-1",
            "saleId": sale["saleId"],
            "expectedRevision": 1,
            "expectedEventVersion": 2,
            "saleAt": SALE_AT,
            "paymentMethod": {"methodCode": "CASH"},
            "reason": "r",
        }
        wrong_event = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "saleId": "S#ghost",
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-cg-002",
                },
            ),
            None,
        )
        assert wrong_event["errorCode"] == ErrorCode.NOT_FOUND
        stale_revision = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "expectedRevision": 9,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-cg-003",
                },
            ),
            None,
        )
        assert stale_revision["errorCode"] == ErrorCode.CONFLICT
        line_mismatch = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "lineItems": [
                        {
                            "lineItemId": sale["lineItems"][0]["lineItemId"],
                            "productId": "PROD#2",
                            "immediateQty": 1,
                            "weOweQty": 0,
                        }
                    ],
                    "idempotencyKey": "sw-cg-004",
                },
            ),
            None,
        )
        assert line_mismatch["errorCode"] == ErrorCode.INVALID_INPUT
        bad_line_entry = handler(
            _ev("correctShowAndSellSale", {**base, "lineItems": ["x"], "idempotencyKey": "sw-cg-005"}),
            None,
        )
        assert bad_line_entry["errorCode"] == ErrorCode.INVALID_INPUT
        over_draw = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "lineItems": [
                        {
                            "lineItemId": sale["lineItems"][0]["lineItemId"],
                            "productId": "PROD#1",
                            "immediateQty": 50,
                            "weOweQty": 0,
                        }
                    ],
                    "idempotencyKey": "sw-cg-006",
                },
            ),
            None,
        )
        assert over_draw["errorCode"] == ErrorCode.CONFLICT
        # Replay.
        args = {
            **base,
            "lineItems": [
                {
                    "lineItemId": sale["lineItems"][0]["lineItemId"],
                    "productId": "PROD#1",
                    "immediateQty": 1,
                    "weOweQty": 0,
                }
            ],
            "idempotencyKey": "sw-cg-007",
        }
        first = handler(_ev("correctShowAndSellSale", args), None)
        second = handler(_ev("correctShowAndSellSale", args), None)
        assert second == first
        # Correcting a voided sale.
        handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 2,
                    "expectedEventVersion": 3,
                    "reason": "v",
                    "idempotencyKey": "sw-cg-008",
                },
            ),
            None,
        )
        voided = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "expectedRevision": 3,
                    "expectedEventVersion": 4,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-cg-009",
                },
            ),
            None,
        )
        assert voided["errorCode"] == ErrorCode.CONFLICT

    def test_void_guards_and_replay(self, t: Any) -> None:
        created = _create_sale(t, key="sw-vg-001")
        sale = created["sale"]
        args = {
            "showAndSellId": "ev-1",
            "saleId": sale["saleId"],
            "expectedRevision": 1,
            "expectedEventVersion": 2,
            "reason": "v",
            "idempotencyKey": "sw-vg-002",
        }
        first = handler(_ev("voidShowAndSellSale", args), None)
        second = handler(_ev("voidShowAndSellSale", args), None)
        assert second == first
        bad_version = handler(
            _ev("voidShowAndSellSale", {**args, "expectedEventVersion": -1, "idempotencyKey": "sw-vg-003"}),
            None,
        )
        assert bad_version["errorCode"] == ErrorCode.INVALID_INPUT

    def test_reservation_guards_and_replay(self, t: Any) -> None:
        created = _create_sale(t, key="sw-rg-001")
        obligation = created["weOweObligations"][0]
        negative = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": -1,
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-rg-002",
                },
            ),
            None,
        )
        assert negative["errorCode"] == ErrorCode.INVALID_INPUT
        stale = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": 1,
                    "expectedVersion": 9,
                    "idempotencyKey": "sw-rg-003",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        args = {
            "weOweId": obligation["weOweId"],
            "targetReservedQty": 1,
            "expectedVersion": 1,
            "idempotencyKey": "sw-rg-004",
        }
        first = handler(_ev("setWeOweReservation", args), None)
        second = handler(_ev("setWeOweReservation", args), None)
        assert second == first
        missing = handler(
            _ev(
                "setWeOweReservation",
                {"weOweId": "WEOWE#ghost", "targetReservedQty": 1, "expectedVersion": 1, "idempotencyKey": "sw-rg-005"},
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

    def test_fulfill_guards_and_replay(self, t: Any) -> None:
        created = _create_sale(t, key="sw-fg-001")
        obligation = created["weOweObligations"][0]
        zero = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 0,
                    "source": "KERNEL_STOCK",
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-fg-002",
                },
            ),
            None,
        )
        assert zero["errorCode"] == ErrorCode.INVALID_INPUT
        stale = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 1,
                    "source": "KERNEL_STOCK",
                    "expectedVersion": 9,
                    "idempotencyKey": "sw-fg-003",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        args = {
            "weOweId": obligation["weOweId"],
            "quantity": 1,
            "source": "OTHER",
            "expectedVersion": 1,
            "idempotencyKey": "sw-fg-004",
        }
        first = handler(_ev("fulfillWeOwe", args), None)
        second = handler(_ev("fulfillWeOwe", args), None)
        assert second == first
        missing = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": "WEOWE#ghost",
                    "quantity": 1,
                    "source": "OTHER",
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-fg-005",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

    def test_query_guards(self, t: Any) -> None:
        _create_sale(t, key="sw-qg-001")
        blocked = handler(_ev("showAndSellSales", {"showAndSellId": "ev-1"}, sub="user-789"), None)
        assert blocked["errorCode"] == ErrorCode.NOT_FOUND
        blocked2 = handler(_ev("weOweObligations", {"unitCampaignId": "uc-1"}, sub="user-789"), None)
        assert blocked2["errorCode"] == ErrorCode.NOT_FOUND
        ghost = handler(_ev("showAndSellSales", {"showAndSellId": "SS#ghost"}), None)
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND

    def test_cancel_mappings(self, t: Any, monkeypatch: Any) -> None:
        _create_sale(t, key="sw-cm-001")

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(sale_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-cm-002", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=3
                ),
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(sale_operations, "execute_transaction", _cancel_on_first)
        raw = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-cm-003", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=3
                ),
            ),
            None,
        )
        assert raw["errorCode"] == ErrorCode.CONFLICT


class TestSaleFinalSweep:
    def test_pure_helpers(self, t: Any) -> None:
        from src.handlers.sale_operations import (
            _idempotency_begin,
            _obligation_matches,
            _parse_ts,
            _product_cents,
            _split_alloc_key,
        )

        with pytest.raises(ValueError):
            _parse_ts("2026-11-01T12:00:00")
        # input-wrapped marker key resolution (inline in _idempotency_begin)
        caller, _, _ = _idempotency_begin(_ev("mystery", {}), {"input": {"idempotencyKey": "sw-ik-01"}}, "scope")
        assert caller == ACCOUNT_A
        assert _split_alloc_key("ALLOC#ev-9#PROD#1") == ("ev-9", "PROD#1")
        with pytest.raises(AppError):
            _product_cents({"productId": "P", "price": "bad"})
        # obligation filter arcs
        item = {"status": "OPEN", "showAndSellId": "s", "productId": "p", "buyerName": "Alice"}
        assert _obligation_matches(item, "OPEN", "s", "p", "ali")
        assert not _obligation_matches(item, "CLOSED", None, None, None)
        assert not _obligation_matches(item, None, "other", None, None)
        assert not _obligation_matches(item, None, None, "other", None)
        assert not _obligation_matches(item, None, None, None, "zzz")

    def test_catalog_and_marker_result_branches(self, t: Any) -> None:
        _create_sale(t, key="sw-fs-001")
        t["unit_campaigns"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": "METADATA"},
            UpdateExpression="REMOVE catalogId",
        )
        no_catalog = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-fs-002", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=2
                ),
            ),
            None,
        )
        assert no_catalog["errorCode"] == ErrorCode.INVALID_INPUT
        # missing-result marker

        from src.handlers.sale_operations import _check_marker

        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#scope#sw-fs-003",
                "idemFingerprint": "fp",
            }
        )
        with pytest.raises(AppError):
            _check_marker(
                t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#sw-fs-003"})["Item"],
                "fp",
            )

    def test_create_with_buyer_and_weowe_only(self, t: Any) -> None:
        _seed_world = _create_sale(
            t,
            key="sw-fs-004",
            lines=[{"productId": "PROD#2", "immediateQty": 0, "weOweQty": 2}],
            buyerName="Jordan",
            buyerPhone="555-0100",
            buyerEmail="jordan@example.com",
        )
        assert _seed_world["sale"]["buyerName"] == "Jordan"
        assert _seed_world["sale"]["buyerPhone"] == "555-0100"
        assert _seed_world["sale"]["buyerEmail"] == "jordan@example.com"
        # We-owe-only line: allocation untouched.
        alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "ALLOC#ev-1#PROD#2"})["Item"]
        assert alloc["remainingQty"] == 10 and alloc["soldQty"] == 0

    def test_create_marker_race_mapping(self, t: Any, monkeypatch: Any) -> None:
        _create_sale(t, key="sw-fs-005")

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(sale_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-fs-006", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=3
                ),
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT
        assert "concurrently" in raced["message"]

    def test_correction_line_validation_branches(self, t: Any) -> None:
        created = _create_sale(t, key="sw-fs-007")
        sale = created["sale"]
        base = {
            "showAndSellId": "ev-1",
            "saleId": sale["saleId"],
            "expectedRevision": 1,
            "expectedEventVersion": 2,
            "saleAt": SALE_AT,
            "paymentMethod": {"methodCode": "CASH"},
            "reason": "r",
        }
        empty = handler(_ev("correctShowAndSellSale", {**base, "lineItems": [], "idempotencyKey": "sw-fs-008"}), None)
        assert empty["errorCode"] == ErrorCode.INVALID_INPUT
        bad_id = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "lineItems": [{"lineItemId": 5, "productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-fs-009",
                },
            ),
            None,
        )
        assert bad_id["errorCode"] == ErrorCode.INVALID_INPUT
        zero = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 0, "weOweQty": 0}],
                    "idempotencyKey": "sw-fs-010",
                },
            ),
            None,
        )
        assert zero["errorCode"] == ErrorCode.INVALID_INPUT
        ghost_product = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "lineItems": [{"productId": "PROD#ghost", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-fs-011",
                },
            ),
            None,
        )
        assert ghost_product["errorCode"] == ErrorCode.INVALID_INPUT

    def test_correction_new_line_and_unchanged_paths(self, t: Any) -> None:
        created = _create_sale(t, key="sw-fs-012")
        sale = created["sale"]
        line = sale["lineItems"][0]
        # Same immediate, same weOwe: no allocation movement, obligation re-projected.
        same = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "saleAt": SALE_AT,
                    "lineItems": [
                        {"lineItemId": line["lineItemId"], "productId": "PROD#1", "immediateQty": 3, "weOweQty": 2}
                    ],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "touch",
                    "idempotencyKey": "sw-fs-013",
                },
            ),
            None,
        )
        assert same["sale"]["revision"] == 2
        assert same["weOweObligations"][0]["originalQty"] == 2
        # Add a NEW line with we-owe demand: mints a fresh obligation.
        added = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 2,
                    "expectedEventVersion": 3,
                    "saleAt": SALE_AT,
                    "lineItems": [
                        {"lineItemId": line["lineItemId"], "productId": "PROD#1", "immediateQty": 3, "weOweQty": 2},
                        {"productId": "PROD#2", "immediateQty": 0, "weOweQty": 5},
                    ],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "add",
                    "idempotencyKey": "sw-fs-014",
                },
            ),
            None,
        )
        assert any(o["originalQty"] == 5 for o in added["weOweObligations"])
        # Drop the PROD#2 we-owe-only line: no release movement, obligation cancelled.
        dropped = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 3,
                    "expectedEventVersion": 4,
                    "saleAt": SALE_AT,
                    "lineItems": [
                        {"lineItemId": line["lineItemId"], "productId": "PROD#1", "immediateQty": 3, "weOweQty": 2}
                    ],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "drop",
                    "idempotencyKey": "sw-fs-015",
                },
            ),
            None,
        )
        cancelled = [o for o in dropped["weOweObligations"] if o["cancelledQty"] == 5]
        assert cancelled

    def test_correction_and_void_cancel_mappings(self, t: Any, monkeypatch: Any) -> None:
        created = _create_sale(t, key="sw-fs-016")
        sale = created["sale"]
        line = sale["lineItems"][0]

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(sale_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "saleAt": SALE_AT,
                    "lineItems": [
                        {"lineItemId": line["lineItemId"], "productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}
                    ],
                    "paymentMethod": {"methodCode": "CASH"},
                    "reason": "r",
                    "idempotencyKey": "sw-fs-017",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT
        raced_void = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 1,
                    "expectedEventVersion": 2,
                    "reason": "v",
                    "idempotencyKey": "sw-fs-018",
                },
            ),
            None,
        )
        assert raced_void["errorCode"] == ErrorCode.CONFLICT

    def test_uc_missing_guards(self, t: Any) -> None:
        created = _create_sale(t, key="sw-fs-019")
        obligation = created["weOweObligations"][0]
        t["unit_campaigns"].delete_item(Key={"unitCampaignId": "uc-1", "itemKey": "METADATA"})
        missing = handler(
            _ev(
                "setWeOweReservation",
                {
                    "weOweId": obligation["weOweId"],
                    "targetReservedQty": 1,
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-fs-020",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        missing2 = handler(
            _ev(
                "fulfillWeOwe",
                {
                    "weOweId": obligation["weOweId"],
                    "quantity": 1,
                    "source": "OTHER",
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-fs-021",
                },
            ),
            None,
        )
        assert missing2["errorCode"] == ErrorCode.NOT_FOUND
        missing3 = handler(_ev("weOweObligation", {"weOweId": obligation["weOweId"]}), None)
        assert missing3["errorCode"] == ErrorCode.NOT_FOUND
        missing4 = handler(_ev("weOweObligations", {"unitCampaignId": "uc-1"}), None)
        assert missing4["errorCode"] == ErrorCode.NOT_FOUND

    def test_find_obligation_miss(self, t: Any) -> None:
        from src.handlers.sale_operations import _find_obligation

        _create_sale(t, key="sw-fs-022")
        with pytest.raises(AppError):
            _find_obligation("uc-1", "S#ghost", "L#ghost")


class TestSaleTrulyFinal:
    def test_direct_helpers(self, t: Any) -> None:
        from src.handlers.sale_operations import (
            _catalog_products,
            _movement_entry,
            _payment_snapshot,
            _product_cents,
            _require_event_admin,
        )

        with pytest.raises(AppError):
            _require_event_admin({"unitCampaignId": "UC#ghost"}, ACCOUNT_A)
        assert _catalog_products("UC#ghost") == {}
        with pytest.raises(AppError):
            _product_cents({"productId": "P", "price": -1})
        with pytest.raises(AppError):
            _payment_snapshot({"paymentMethod": {"methodCode": "CASH", "otherDetails": 5}})
        entry = _movement_entry("uc-1", "P", "TEST", 1, ACCOUNT_A, "s", "ev-1")
        assert "saleId" not in entry["Put"]["Item"]

    def test_catalog_row_missing(self, t: Any) -> None:
        _create_sale(t, key="sw-tf-001")
        t["catalogs"].delete_item(Key={"catalogId": "CATALOG#c"})  # catalogs table missing entirely
        result = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-tf-002", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=2
                ),
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_cancelled_event_create(self, t: Any) -> None:
        _create_sale(t, key="sw-tf-003")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": "EVENT#ev-1"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        result = handler(
            _ev(
                "createShowAndSellSale",
                _sale_args(
                    "sw-tf-004", [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}], expectedEventVersion=2
                ),
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_correction_and_void_guards(self, t: Any) -> None:
        created = _create_sale(t, key="sw-tf-005")
        sale = created["sale"]
        base = {
            "showAndSellId": "ev-1",
            "saleId": sale["saleId"],
            "expectedRevision": 1,
            "saleAt": SALE_AT,
            "paymentMethod": {"methodCode": "CASH"},
            "reason": "r",
        }
        neg = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "expectedEventVersion": -1,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-tf-006",
                },
            ),
            None,
        )
        assert neg["errorCode"] == ErrorCode.INVALID_INPUT
        stale_ev = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "expectedEventVersion": 9,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-tf-007",
                },
            ),
            None,
        )
        assert stale_ev["errorCode"] == ErrorCode.CONFLICT
        stale_rev = handler(
            _ev(
                "voidShowAndSellSale",
                {
                    "showAndSellId": "ev-1",
                    "saleId": sale["saleId"],
                    "expectedRevision": 9,
                    "expectedEventVersion": 2,
                    "reason": "v",
                    "idempotencyKey": "sw-tf-008",
                },
            ),
            None,
        )
        assert stale_rev["errorCode"] == ErrorCode.CONFLICT
        # Sale from a DIFFERENT event (cross-event lookup miss at the guard).
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "EVENT#ev-2",
                "showAndSellId": "ev-2",
                "saleId": "ev-2",
                "unitId": "unit-1",
                "locationName": "Two",
                "startAt": "2026-12-01T00:00:00Z",
                "endAt": "2026-12-02T00:00:00Z",
                "status": "SCHEDULED",
                "splitMethod": "EQUAL",
                "weOweEnabled": False,
                "version": 1,
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        cross = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "showAndSellId": "ev-2",
                    "expectedEventVersion": 1,
                    "lineItems": [{"productId": "PROD#1", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-tf-009",
                },
            ),
            None,
        )
        assert cross["errorCode"] == ErrorCode.NOT_FOUND
        # A correction that prices a NEW product against a bad catalog row
        # surfaces the price error at enrich time (not a silent snapshot).
        t["catalogs"].put_item(
            Item={
                "catalogId": "CATALOG#c",
                "productId": "PROD#3",
                "productName": "Bad",
                "price": "bad",
                "isActive": True,
            }
        )
        bad_price = handler(
            _ev(
                "correctShowAndSellSale",
                {
                    **base,
                    "expectedEventVersion": 2,
                    "lineItems": [{"productId": "PROD#3", "immediateQty": 1, "weOweQty": 0}],
                    "idempotencyKey": "sw-tf-010",
                },
            ),
            None,
        )
        assert bad_price["errorCode"] == ErrorCode.INVALID_INPUT
