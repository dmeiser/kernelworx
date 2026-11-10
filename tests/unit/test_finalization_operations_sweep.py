"""Coverage sweep for finalization_operations.py: error branches, guards,
marker mappings, query filters, and the pure helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock

import boto3
import pytest

import src.handlers.finalization_operations as fin
from src.handlers.finalization_operations import handler
from src.handlers.event_operations import handler as event_handler
from src.utils.dynamodb import TransactionCancelledError
from src.utils.errors import AppError, ErrorCode

from tests.unit.test_event_operations import (
    ACCOUNT_A,
    CAMPAIGN_A,
    PROFILE_A,
    PROFILE_B,
    _create_event,
    _event_version,
    _ev,
    _seed,
)
from tests.unit.test_finalization_operations import _assign, _ended_event, _finalize, _past_moment, _reopen
from tests.unit.test_sale_operations import _create_sale as _create_ss_sale


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "catalogs": dynamodb.Table("kernelworx-catalogs-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "show_and_sells": dynamodb.Table("kernelworx-show-and-sells-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
    }


def _confirmed(t: Dict[str, Any], created: Dict[str, Any]) -> None:
    for profile, campaign in ((PROFILE_A, CAMPAIGN_A), (PROFILE_B, "CAMPAIGN#campaign-2")):
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#slot-sw#{profile}",
                "showAndSellId": created["showAndSellId"],
                "slotId": "slot-sw",
                "profileId": profile,
                "campaignId": campaign,
                "status": "ACTIVE",
                "actualMinutes": 60,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )


class TestPureHelpers:
    def test_preflight_and_int_helpers(self, t: Any) -> None:
        fin._preflight_named(90, "ok")  # boundary passes
        with pytest.raises(AppError) as exc:
            fin._preflight_named(91, "finalizeShowAndSell")
        assert "OPERATION_TOO_LARGE" in exc.value.message and "Remediation" in exc.value.message
        fin._require_int(5, "f")
        with pytest.raises(AppError):
            fin._require_int("x", "f")
        assert fin._non_negative_int(0, "f") == 0
        with pytest.raises(AppError):
            fin._non_negative_int(-1, "f")

    def test_confirmed_work_skips(self, t: Any) -> None:
        _seed(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#s1#P1",
                "showAndSellId": "ev-x",
                "slotId": "s1",
                "profileId": "P1",
                "campaignId": "C1",
                "status": "CANCELLED",
                "actualMinutes": 30,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#s1#P2",
                "showAndSellId": "ev-x",
                "slotId": "s1",
                "profileId": "P2",
                "campaignId": "C2",
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#s1#P3",
                "showAndSellId": "ev-OTHER",
                "slotId": "s1",
                "profileId": "P3",
                "campaignId": "C3",
                "status": "ACTIVE",
                "actualMinutes": 30,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        work = fin._confirmed_work("uc-1", "ev-x")
        assert work == {"P1": {"campaignId": "C1", "minutes": 30}}, work

    def test_time_worked_split(self, t: Any) -> None:
        base, unassigned = fin._compute_split(
            100, "TIME_WORKED", {"P1": {"campaignId": "C1", "minutes": 1}, "P2": {"campaignId": "C2", "minutes": 3}}
        )
        assert [b["baseAmountCents"] for b in base] == [25, 75] and unassigned == 0
        assert base[0]["campaignId"] == "C1" and base[1]["minutes"] == 3
        with pytest.raises(AppError):
            fin._compute_split(100, "TIME_WORKED", {"P1": {"campaignId": "C1", "minutes": 0}})
        base2, un2 = fin._compute_split(100, "EQUAL", {})
        assert base2 == [] and un2 == 100

    def test_credit_projection(self, t: Any) -> None:
        row = fin._credit_to_graphql(
            {
                "allocationId": "A1",
                "finalizationId": "F1",
                "showAndSellId": "S1",
                "unitCampaignId": "uc-1",
                "campaignId": "C1",
                "profileId": "P1",
                "amountCents": 5,
                "status": "APPROVED",
                "createdAt": "t",
            }
        )
        assert row["suspendedAt"] is None and row["amountCents"] == 5

    def test_balance_and_total_guards(self, t: Any) -> None:
        _seed(t)
        with pytest.raises(AppError) as exc:
            fin._balance_update(
                "uc-1", {"itemKey": "BALANCE#P", "productId": "P", "kernelPhysicalQty": 0, "version": 1}, -1, "s"
            )
        assert exc.value.error_code == ErrorCode.CONFLICT
        with pytest.raises(AppError):
            fin._total_apply_entry("uc-1", "C9", "P9", -5, "s")  # totals would go negative
        entry = fin._total_apply_entry("uc-1", "C9", "P9", 5, "s")
        assert "attribute_not_exists(#version)" in entry["Update"]["ConditionExpression"]

    def test_return_and_rounding_validation(self, t: Any) -> None:
        with pytest.raises(AppError):
            fin._validate_return_line("nope")
        with pytest.raises(AppError):
            fin._validate_return_line({})
        with pytest.raises(AppError):
            fin._validate_return_line({"productId": "P", "expectedQty": -1, "actualQty": 0})
        with pytest.raises(AppError):
            fin._validate_return_line({"productId": "P", "expectedQty": 0, "actualQty": 0.5})
        with pytest.raises(AppError):
            fin._validate_return_line({"productId": "P", "expectedQty": 1, "actualQty": 0})
        pid, parsed = fin._validate_return_line({"productId": "P", "expectedQty": 1, "actualQty": 0, "reason": "r"})
        assert pid == "P" and parsed["reason"] == "r"
        with pytest.raises(AppError):
            fin._normalize_return_lines("nope", [])
        with pytest.raises(AppError):
            fin._normalize_return_lines(
                [
                    {"productId": "P", "expectedQty": 0, "actualQty": 0},
                    {"productId": "P", "expectedQty": 0, "actualQty": 0},
                ],
                [],
            )
        normalized = fin._normalize_return_lines(None, [{"productId": "P", "status": "OPEN"}])
        assert normalized == {"P": {"expectedQty": 0, "actualQty": 0, "reason": None}}
        with pytest.raises(AppError):
            fin._normalize_rounding_entries("nope", {})
        with pytest.raises(AppError):
            fin._normalize_rounding_entries(["x"], {})
        with pytest.raises(AppError):
            fin._normalize_rounding_entries([{"profileId": "GHOST", "cents": 1}], {"P1": 1})
        with pytest.raises(AppError):
            fin._normalize_rounding_entries(
                [{"profileId": "P1", "cents": 1}, {"profileId": "P1", "cents": 1}], {"P1": 1}
            )
        with pytest.raises(AppError):
            fin._normalize_rounding_entries([{"profileId": "P1", "cents": -1}], {"P1": 1})

    def test_draft_entry_validation(self, t: Any) -> None:
        with pytest.raises(AppError):
            fin._validate_draft_entry("x", set(), set())
        with pytest.raises(AppError):
            fin._validate_draft_entry({"profileId": "G", "cents": 1}, {"P1"}, set())
        seen: set[str] = {"P1"}
        with pytest.raises(AppError):
            fin._validate_draft_entry({"profileId": "P1", "cents": 1}, {"P1"}, seen)
        with pytest.raises(AppError):
            fin._validate_draft_entry({"profileId": "P2", "cents": True}, {"P2"}, set())
        assert fin._validate_draft_entry({"profileId": "P2", "cents": 3}, {"P2"}, set()) == ("P2", 3)
        with pytest.raises(AppError) as exc:
            fin._normalize_draft(
                [{"profileId": "P1", "cents": 5}],
                {"baseAllocations": [{"profileId": "P1", "baseAmountCents": 1}], "unassignedCents": 0},
            )
        assert "exceed" in exc.value.message

    def test_stock_delta_unknown_product(self, t: Any) -> None:
        _seed(t)
        with pytest.raises(AppError) as exc:
            fin._stock_delta_entries({"GHOST": 1}, {}, {}, "uc-1", "ACTOR", "s")
        assert exc.value.error_code == ErrorCode.CONFLICT

    def test_supplemental_and_retarget_paths(self, t: Any) -> None:
        sale = {"saleId": "S1", "showAndSellId": "E1", "buyerName": "B"}
        line = {"lineItemId": "L1", "productId": "P", "weOweQty": 3}
        item = fin._supplemental_obligation(sale, line, 3, "uc-1", "s")
        assert item["originalQty"] == 3 and item["remainingQty"] == 3
        entries = fin._publish_one_line(sale, line, [], "uc-1", "s")
        assert len(entries) == 1 and entries[0]["Put"]["Item"]["originalQty"] == 3
        none_entries = fin._publish_one_line(sale, {**line, "weOweQty": 0}, [], "uc-1", "s")
        assert none_entries == []
        # Retarget: consistent row produces no entry.
        row = {
            "itemKey": "WEOWE#x",
            "originalQty": 2,
            "fulfilledQty": 0,
            "cancelledQty": 0,
            "remainingQty": 2,
            "status": "OPEN",
            "version": 1,
            "createdAt": "t",
        }
        assert fin._obligation_retarget_entry(row, 2, "uc-1", "s") is None
        changed = fin._obligation_retarget_entry(row, 0, "uc-1", "s")
        assert changed is not None and changed["Update"]["ExpressionAttributeValues"][":cancelled"] == 2
        # Mixed: excess over the original materializes a supplemental.
        entries2 = fin._publish_one_line(sale, {**line, "weOweQty": 5}, [row], "uc-1", "s")
        assert any("Put" in e for e in entries2)

    def test_obligation_grouping(self, t: Any) -> None:
        sale = {
            "saleId": "S1",
            "showAndSellId": "E1",
            "buyerName": "",
            "lineItems": [{"lineItemId": "L1", "productId": "P", "weOweQty": 0}],
        }
        obligation = {
            "itemKey": "WEOWE#w1",
            "lineItemId": "L1",
            "originalQty": 2,
            "fulfilledQty": 0,
            "cancelledQty": 2,
            "remainingQty": 0,
            "status": "CLOSED",
            "version": 1,
            "createdAt": "t",
        }
        entries = fin._obligation_publish_entries([obligation], [sale], "uc-1", "s")
        assert entries == []

    def test_supersede_and_handler_edges(self, t: Any) -> None:
        previous = {"itemKey": "FINAL#f1", "finalizationId": "f1"}
        entries = fin._supersede_entries(previous, "uc-1", "s")
        assert len(entries) == 1  # no credits in table
        unknown = handler(_ev("mysteryFinalizationOp", {}), None)
        assert unknown["errorCode"] == ErrorCode.INTERNAL_ERROR
        event = _ev("showAndSellFinalizations", {"showAndSellId": "E"})
        del event["identity"]
        unauthorized = handler(event, None)
        assert unauthorized["errorCode"] == ErrorCode.UNAUTHORIZED


class TestDraftMutation:
    def _world(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _ended_event(t, key="sw-draft-001")
        _assign(t, created, "PROD#SW", 1, "sw-draft-assign1")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#SW", "productName": "S", "price": 1}]}
        )
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#SW", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-draft-sale-01",
                },
            ),
            None,
        )
        _confirmed(t, created)
        return created

    def test_happy_replay_and_guards(self, t: Dict[str, Any]) -> None:
        created = self._world(t)
        args = {
            "showAndSellId": created["showAndSellId"],
            "expectedVersion": _event_version(t, created["showAndSellId"]),
            "draft": [{"profileId": PROFILE_A, "cents": 0}],
            "idempotencyKey": "sw-draft-key01",
        }
        ok = handler(_ev("updateShowAndSellRoundingDraft", args), None)
        assert "showAndSellId" in ok, ok
        replay = handler(_ev("updateShowAndSellRoundingDraft", dict(args)), None)
        assert replay == ok
        # Guards.
        bad = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {"showAndSellId": "", "expectedVersion": 1, "draft": [], "idempotencyKey": "sw-draft-key02"},
            ),
            None,
        )
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        bad2 = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 0,
                    "draft": [],
                    "idempotencyKey": "sw-draft-key03",
                },
            ),
            None,
        )
        assert bad2["errorCode"] == ErrorCode.INVALID_INPUT
        bad3 = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "draft": "x",
                    "idempotencyKey": "sw-draft-key04",
                },
            ),
            None,
        )
        assert bad3["errorCode"] == ErrorCode.INVALID_INPUT
        bad4 = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "draft": [],
                    "idempotencyKey": "short",
                },
            ),
            None,
        )
        assert bad4["errorCode"] == ErrorCode.INVALID_INPUT
        stale = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 99,
                    "draft": [],
                    "idempotencyKey": "sw-draft-key05",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        ghost = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {"showAndSellId": "SS#ghost", "expectedVersion": 1, "draft": [], "idempotencyKey": "sw-draft-key06"},
            ),
            None,
        )
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND
        # Marker race mapping.
        import src.handlers.finalization_operations as fin_mod

        original = fin_mod.execute_transaction

        def _cancel(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        fin_mod.execute_transaction = _cancel
        try:
            raced = handler(_ev("updateShowAndSellRoundingDraft", dict(args, idempotencyKey="sw-draft-key07")), None)
            assert raced["errorCode"] == ErrorCode.CONFLICT and "concurrently" in raced["message"]
            raced2 = handler(
                _ev(
                    "updateShowAndSellRoundingDraft",
                    dict(
                        args,
                        idempotencyKey="sw-draft-key08",
                        expectedVersion=_event_version(t, created["showAndSellId"]),
                    ),
                ),
                None,
            )
            assert raced2["errorCode"] == ErrorCode.CONFLICT
        finally:
            fin_mod.execute_transaction = original


class TestFinalizeAndReopenGuards:
    def test_finalize_arg_guards(self, t: Dict[str, Any]) -> None:
        created = _create_event(t, key="sw-guard-ev01")
        bad = handler(
            _ev("finalizeShowAndSell", {"showAndSellId": "", "expectedVersion": 1, "idempotencyKey": "sw-fin-key-001"}),
            None,
        )
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        bad2 = handler(
            _ev(
                "finalizeShowAndSell",
                {"showAndSellId": created["showAndSellId"], "expectedVersion": 0, "idempotencyKey": "sw-fin-key-002"},
            ),
            None,
        )
        assert bad2["errorCode"] == ErrorCode.INVALID_INPUT
        bad3 = handler(
            _ev(
                "finalizeShowAndSell",
                {"showAndSellId": created["showAndSellId"], "expectedVersion": 1, "idempotencyKey": "short"},
            ),
            None,
        )
        assert bad3["errorCode"] == ErrorCode.INVALID_INPUT
        ghost = handler(
            _ev(
                "finalizeShowAndSell",
                {"showAndSellId": "SS#ghost", "expectedVersion": 1, "idempotencyKey": "sw-fin-key-003"},
            ),
            None,
        )
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND
        stale = handler(
            _ev(
                "finalizeShowAndSell",
                {"showAndSellId": created["showAndSellId"], "expectedVersion": 99, "idempotencyKey": "sw-fin-key-004"},
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT

    def test_cash_rules(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-cash-ev001")
        no_reason = _finalize(t, created, "sw-cash-key01", cashAdjustmentCents=100)
        assert no_reason["errorCode"] == ErrorCode.INVALID_INPUT
        bad_type = _finalize(t, created, "sw-cash-key02", cashAdjustmentCents="x")
        assert bad_type["errorCode"] == ErrorCode.INVALID_INPUT
        bad_actual = _finalize(t, created, "sw-cash-key03", actualCashCents=1.5)
        assert bad_actual["errorCode"] == ErrorCode.INVALID_INPUT
        no_expl = _finalize(t, created, "sw-cash-key04", actualCashCents=100)
        assert no_expl["errorCode"] == ErrorCode.INVALID_INPUT

    def test_finalize_marker_race_and_cancel(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-race-ev001")
        _assign(t, created, "PROD#RC", 1, "sw-race-assign1")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#RC", "productName": "R", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#RC", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-race-sale-01",
                },
            ),
            None,
        )

        def _cancel_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_marker)
        raced = _finalize(t, created, "sw-race-key-01")
        assert raced["errorCode"] == ErrorCode.CONFLICT and "processed concurrently" in raced["message"]
        # Cancelled event cannot hold a draft.
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        draft_blocked = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": _event_version(t, created["showAndSellId"]),
                    "draft": [],
                    "idempotencyKey": "sw-race-key-02",
                },
            ),
            None,
        )
        assert draft_blocked["errorCode"] == ErrorCode.CONFLICT

    def test_reopen_guards(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-ro-guards1")
        bad = handler(
            _ev(
                "reopenShowAndSell",
                {"showAndSellId": "", "expectedVersion": 1, "reason": "r", "idempotencyKey": "sw-ro-key-001"},
            ),
            None,
        )
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        bad2 = handler(
            _ev(
                "reopenShowAndSell",
                {"showAndSellId": "SS#ghost", "expectedVersion": 1, "reason": "r", "idempotencyKey": "sw-ro-key-002"},
            ),
            None,
        )
        assert bad2["errorCode"] == ErrorCode.NOT_FOUND
        bad3 = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 99,
                    "reason": "r",
                    "idempotencyKey": "sw-ro-key-003",
                },
            ),
            None,
        )
        assert bad3["errorCode"] == ErrorCode.CONFLICT
        not_finalized = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "reason": "r",
                    "idempotencyKey": "sw-ro-key-004",
                },
            ),
            None,
        )
        assert not_finalized["errorCode"] == ErrorCode.CONFLICT
        no_reason = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "reason": "",
                    "idempotencyKey": "sw-ro-key-005",
                },
            ),
            None,
        )
        assert no_reason["errorCode"] == ErrorCode.INVALID_INPUT
        # FINALIZED but no approvedFinalizationId row.
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "FINALIZED"},
        )
        missing = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "reason": "r",
                    "idempotencyKey": "sw-ro-key-006",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.CONFLICT

    def test_reopen_marker_race(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-ro-race001")
        _assign(t, created, "PROD#RR", 1, "sw-ro-assign-01")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#RR", "productName": "R", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#RR", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-ro-sale-001",
                },
            ),
            None,
        )
        _finalize(t, created, "sw-ro-fin-001")

        def _cancel_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_marker)
        raced = _reopen(t, created, "sw-ro-race01")
        assert raced["errorCode"] == ErrorCode.CONFLICT and "processed concurrently" in raced["message"]


class TestPreviewAndQueries:
    def test_preview_adjustments_and_guards(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-pv-ev0001")
        preview = handler(
            _ev(
                "showAndSellFinalizationPreview",
                {"showAndSellId": created["showAndSellId"], "cashAdjustmentCents": 50, "actualCashCents": 80},
            ),
            None,
        )
        assert preview["expectedCashCents"] == 50 and preview["cashDiscrepancyCents"] == 30, preview
        bad = handler(_ev("showAndSellFinalizationPreview", {"showAndSellId": ""}), None)
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        ghost = handler(_ev("showAndSellFinalizationPreview", {"showAndSellId": "SS#ghost"}), None)
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND
        blocked = handler(_ev("showAndSellFinalizations", {"showAndSellId": "SS#ghost"}), None)
        assert blocked["errorCode"] == ErrorCode.NOT_FOUND

    def test_credits_query_filters(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-cq-ev0001")
        _assign(t, created, "PROD#CQ", 1, "sw-cq-assign-01")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#CQ", "productName": "C", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#CQ", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-cq-sale-001",
                },
            ),
            None,
        )
        ok = _finalize(t, created, "sw-cq-fin-001")
        finalization_id = ok["finalization"]["finalizationId"]
        filtered = handler(
            _ev(
                "showAndSellFinalizationCredits",
                {"showAndSellId": created["showAndSellId"], "finalizationId": finalization_id, "status": "APPROVED"},
            ),
            None,
        )
        assert len(filtered["items"]) == 2, filtered
        empty = handler(
            _ev(
                "showAndSellFinalizationCredits",
                {"showAndSellId": created["showAndSellId"], "status": "SUPERSEDED"},
            ),
            None,
        )
        assert empty["items"] == []
        bad = handler(_ev("showAndSellFinalizationCredits", {"showAndSellId": ""}), None)
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        uc = handler(_ev("unitCampaignCreditAllocations", {"unitCampaignId": "uc-1"}), None)
        assert len(uc["items"]) == 2, uc
        uc_filtered = handler(
            _ev("unitCampaignCreditAllocations", {"unitCampaignId": "uc-1", "status": "SUSPENDED"}), None
        )
        assert uc_filtered["items"] == []
        uc_bad = handler(_ev("unitCampaignCreditAllocations", {"unitCampaignId": ""}), None)
        assert uc_bad["errorCode"] == ErrorCode.INVALID_INPUT
        uc_ghost = handler(_ev("unitCampaignCreditAllocations", {"unitCampaignId": "UC#ghost"}), None)
        assert uc_ghost["errorCode"] == ErrorCode.NOT_FOUND
        total = handler(_ev("scoutCampaignShowAndSellTotal", {"profileId": PROFILE_A, "unitCampaignId": "uc-1"}), None)
        assert total["approvedTotalCents"] == 50, total
        total_bad = handler(_ev("scoutCampaignShowAndSellTotal", {"profileId": "", "unitCampaignId": "uc-1"}), None)
        assert total_bad["errorCode"] == ErrorCode.INVALID_INPUT
        total_ghost = handler(
            _ev("scoutCampaignShowAndSellTotal", {"profileId": PROFILE_A, "unitCampaignId": "UC#ghost"}), None
        )
        assert total_ghost["errorCode"] == ErrorCode.NOT_FOUND


class TestAutoReduceBranches:
    def test_no_open_allocs_and_missing_balance(self, t: Dict[str, Any]) -> None:
        _seed(t)
        later = _create_event(t, key="sw-ar-branch1")  # future event, no allocations
        finalized = _ended_event(t, key="sw-ar-branch2")
        warnings = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert warnings == []

    def test_no_reduction_when_target_covers(self, t: Dict[str, Any]) -> None:
        finalized = _ended_event(t, key="sw-ar-branch3")
        later = _ended_event(t, key="sw-ar-branch4")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{later['showAndSellId']}"},
            UpdateExpression="SET startAt = :s",
            ExpressionAttributeValues={
                ":s": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            },
        )
        _assign(t, later, "PROD#NR", 1, "sw-ar-assign-nr")
        warnings = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert warnings == []


class TestFinalCoverage:
    def test_draft_stock_fallback_mapping(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-fc-draft01")

        def _cancel_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_first)
        raced = handler(
            _ev(
                "updateShowAndSellRoundingDraft",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "draft": [],
                    "idempotencyKey": "sw-fc-draft-key1",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT and "concurrently" in raced["message"], raced

    def test_cash_discrepancy_with_explanation_ok(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-fc-cash001")
        _assign(t, created, "PROD#FC", 1, "sw-fc-assign-01")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#FC", "productName": "F", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#FC", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-fc-sale-001",
                },
            ),
            None,
        )
        ok = _finalize(
            t,
            created,
            "sw-fc-fin-001",
            actualCashCents=90,
            discrepancyExplanation="a dollar short at closeout",
        )
        assert ok["finalization"]["cashDiscrepancyCents"] == -10, ok

    def test_publish_retarget_entry_appended(self, t: Any) -> None:
        # A row whose retarget produces an entry (decrease below original).
        sale = {"saleId": "S1", "showAndSellId": "E1", "buyerName": ""}
        line = {"lineItemId": "L1", "productId": "P", "weOweQty": 1}
        row = {
            "itemKey": "WEOWE#w9",
            "lineItemId": "L1",
            "originalQty": 3,
            "fulfilledQty": 0,
            "cancelledQty": 0,
            "remainingQty": 3,
            "status": "OPEN",
            "version": 1,
            "createdAt": "t",
        }
        entries = fin._publish_one_line(sale, line, [row], "uc-1", "s")
        assert any("Update" in e for e in entries)

    def test_supersede_with_credit_rows(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="sw-fc-sup-001")
        _assign(t, created, "PROD#SP", 1, "sw-fc-assign-sp")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#SP", "productName": "S", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#SP", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-fc-sale-sp1",
                },
            ),
            None,
        )
        ok = _finalize(t, created, "sw-fc-fin-sp1")
        assert ok["finalization"]["status"] == "APPROVED"
        _reopen(t, created, "sw-fc-reopen-sp1")
        v2 = _finalize(t, created, "sw-fc-fin-sp2")
        assert v2["finalization"]["versionNumber"] == 2, v2

    def test_finalize_stock_fallback_mapping(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-fc-finrace1")
        _assign(t, created, "PROD#FR", 1, "sw-fc-assign-fr")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#FR", "productName": "F", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#FR", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-fc-sale-fr1",
                },
            ),
            None,
        )

        def _cancel_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_first)
        raced = _finalize(t, created, "sw-fc-finrace01")
        assert raced["errorCode"] == ErrorCode.CONFLICT and "re-read" in raced["message"], raced

    def test_reopen_targets_and_commit_branches(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-fc-robr-001")
        _assign(t, created, "PROD#RB", 1, "sw-fc-assign-rb")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#RB", "productName": "R", "price": 1}]}
        )
        _confirmed(t, created)
        from src.handlers.sale_operations import handler as sale_handler

        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#RB", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "sw-fc-sale-rb1",
                },
            ),
            None,
        )
        _finalize(t, created, "sw-fc-fin-rb1")
        _reopen(t, created, "sw-fc-reopen-rb1")
        # Second reopen: the approved finalization is gone (SUSPENDED).
        again = _reopen(t, created, "sw-fc-reopen-rb2")
        assert again["errorCode"] == ErrorCode.CONFLICT, again
        # Arg guards.
        bad1 = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": "x",
                    "reason": "r",
                    "idempotencyKey": "sw-fc-key-rb1",
                },
            ),
            None,
        )
        assert bad1["errorCode"] == ErrorCode.INVALID_INPUT
        bad2 = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "r",
                    "idempotencyKey": "short",
                },
            ),
            None,
        )
        assert bad2["errorCode"] == ErrorCode.INVALID_INPUT

        # Stock fallback mapping on reopen.
        def _cancel_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_first)
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s, #version = :v",
            ExpressionAttributeNames={"#status": "status", "#version": "version"},
            ExpressionAttributeValues={":s": "FINALIZED", ":v": 7},
        )
        # Re-point approvedFinalizationId at a fake APPROVED row.
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "FINALAL#nope",
                "finalizationId": "F#fake",
                "showAndSellId": created["showAndSellId"],
                "versionNumber": 1,
                "status": "APPROVED",
                "createdAt": "t",
            }
        )
        raced = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 7,
                    "reason": "r",
                    "idempotencyKey": "sw-fc-race-rb1",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT, raced

    def test_earlier_open_totals_and_reduce_branches(self, t: Dict[str, Any]) -> None:
        finalized = _ended_event(t, key="sw-fc-ar1-ev1")
        later = _ended_event(t, key="sw-fc-ar1-ev2")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{later['showAndSellId']}"},
            UpdateExpression="SET startAt = :s",
            ExpressionAttributeValues={
                ":s": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            },
        )
        # finalized event holds an OPEN allocation from an even-earlier
        # event so _earlier_open_totals accumulates it.
        _assign(t, finalized, "PROD#EO", 1, "sw-fc-assign-eo")
        # Later event: allocation for a product with NO balance row -> skip.
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{later['showAndSellId']}#PROD#NOBAL",
                "productId": "PROD#NOBAL",
                "showAndSellId": later["showAndSellId"],
                "allocatedQty": 1,
                "soldQty": 0,
                "releasedQty": 0,
                "remainingQty": 1,
                "status": "OPEN",
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        warnings = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert warnings == []
        # Earlier start (<= finalized) is skipped by the loop guard.
        earlier = _ended_event(t, key="sw-fc-ar1-ev3")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{earlier['showAndSellId']}"},
            UpdateExpression="SET startAt = :s",
            ExpressionAttributeValues={
                ":s": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
            },
        )
        warnings2 = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert warnings2 == []

    def test_floored_reduction_warns(self, t: Dict[str, Any]) -> None:
        finalized = _ended_event(t, key="sw-fc-ar2-ev1")
        later = _ended_event(t, key="sw-fc-ar2-ev2")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{later['showAndSellId']}"},
            UpdateExpression="SET startAt = :s",
            ExpressionAttributeValues={
                ":s": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            },
        )
        # Balance: sellable 0; allocation sold 2 -> floor forces target 2.
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#FW",
                "productId": "PROD#FW",
                "kernelPhysicalQty": 0,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{later['showAndSellId']}#PROD#FW",
                "productId": "PROD#FW",
                "showAndSellId": later["showAndSellId"],
                "allocatedQty": 3,
                "soldQty": 2,
                "releasedQty": 0,
                "remainingQty": 1,
                "status": "OPEN",
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        warnings = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert len(warnings) == 1 and "floor" in str(warnings[0].get("warning", "")).lower(), warnings

    def test_finalizations_and_credits_guards(self, t: Dict[str, Any]) -> None:
        bad = handler(_ev("showAndSellFinalizations", {"showAndSellId": ""}), None)
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        created = _ended_event(t, key="sw-fc-lf-001")
        empty = handler(_ev("showAndSellFinalizations", {"showAndSellId": created["showAndSellId"]}), None)
        assert empty["items"] == []
        # A credit row for ANOTHER event is skipped (showAndSellId filter).
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "CREDIT#F#other#P9",
                "allocationId": "A9",
                "finalizationId": "F#other",
                "showAndSellId": "SS#other",
                "unitCampaignId": "uc-1",
                "campaignId": "C9",
                "profileId": "P9",
                "amountCents": 1,
                "status": "APPROVED",
                "createdAt": "t",
            }
        )
        filtered = handler(_ev("showAndSellFinalizationCredits", {"showAndSellId": created["showAndSellId"]}), None)
        assert filtered["items"] == []

    def test_reopen_suspended_target_and_stock_fallback(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        created = _ended_event(t, key="sw-fc-rb2-001")
        # FINALIZED event whose approved finalization is already SUSPENDED.
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s, #approved = :fid",
            ExpressionAttributeNames={"#status": "status", "#approved": "approvedFinalizationId"},
            ExpressionAttributeValues={":s": "FINALIZED", ":fid": "F#sus"},
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "FINAL#F#sus",
                "finalizationId": "F#sus",
                "showAndSellId": created["showAndSellId"],
                "versionNumber": 1,
                "status": "SUSPENDED",
                "createdAt": "t",
            }
        )
        suspended = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "reason": "r",
                    "idempotencyKey": "sw-fc-rb2-key1",
                },
            ),
            None,
        )
        assert suspended["errorCode"] == ErrorCode.CONFLICT, suspended
        # Stock-fallback mapping on reopen (non-marker cancel index).
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": "FINAL#F#sus"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "APPROVED"},
        )
        _assign(t, created, "PROD#RF", 0, "sw-fc-assign-rf")
        t["catalogs"].put_item(
            Item={"catalogId": "CATALOG#c", "products": [{"productId": "PROD#RF", "productName": "R", "price": 1}]}
        )
        _confirmed(t, created)

        def _cancel_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_first)
        raced = handler(
            _ev(
                "reopenShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": created["version"],
                    "reason": "r",
                    "idempotencyKey": "sw-fc-rb2-key2",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT and "concurrently" in raced["message"], raced

        # Marker-race mapping: cancel AT the marker index.
        def _cancel_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(fin, "execute_transaction", _cancel_marker)
        raced2 = handler(
            _ev("reopenShowAndSell", {"showAndSellId": created["showAndSellId"], "expectedVersion": _event_version(t, created["showAndSellId"]), "reason": "r", "idempotencyKey": "sw-fc-rb2-key3"}),
            None,
        )
        assert raced2["errorCode"] == ErrorCode.CONFLICT and "processed concurrently" in raced2["message"], raced2

    def test_reduce_at_floor_without_warning(self, t: Dict[str, Any]) -> None:
        finalized = _ended_event(t, key="sw-fc-ar3-ev1")
        later = _ended_event(t, key="sw-fc-ar3-ev2")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{later['showAndSellId']}"},
            UpdateExpression="SET startAt = :s",
            ExpressionAttributeValues={
                ":s": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            },
        )
        # Sellable 2, allocated 3, sold 2: unconverged target 2 == floor 2
        # -> reduces without the floor warning arc.
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#NW",
                "productId": "PROD#NW",
                "kernelPhysicalQty": 2,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{later['showAndSellId']}#PROD#NW",
                "productId": "PROD#NW",
                "showAndSellId": later["showAndSellId"],
                "allocatedQty": 3,
                "soldQty": 2,
                "releasedQty": 0,
                "remainingQty": 1,
                "status": "OPEN",
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        warnings = fin._auto_reduce_later_events({**finalized, "unitCampaignId": "uc-1"}, "ACTOR", "s")
        assert warnings == [
            {
                "showAndSellId": later["showAndSellId"],
                "productId": "PROD#NW",
                "previousAllocatedQty": 3,
                "allocatedQty": 2,
            }
        ], warnings
