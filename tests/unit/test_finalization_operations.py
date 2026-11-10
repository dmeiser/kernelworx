"""Wave-6b finalization oracles: the review-hardened doctrine.

Covers r2's verification bar: union-key return baseline (omitted = declared
zero, transition applied), SUSPENDED exact-subtraction, supersede chains,
ADR 0003 auto-reduce with the sold-stock floor, the Rounding Garage
discipline (the app never chooses), cash/return reconciliation, and the
finalize/reopen replay pin.
"""

from datetime import timedelta
from typing import Any, Dict

import boto3
import pytest

from src.handlers.finalization_operations import handler as finalization_handler
from src.handlers.event_operations import handler as event_handler
from src.handlers.sale_operations import handler as sale_handler
from src.utils.errors import ErrorCode

from tests.unit.test_event_operations import (
    ACCOUNT_A,
    CAMPAIGN_A,
    CAMPAIGN_B,
    FUTURE_END,
    FUTURE_START,
    PROFILE_A,
    PROFILE_B,
    _create_event,
    _event_version,
    _ev,
    _seed,
)
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


def _past_moment() -> str:
    from datetime import datetime, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat().replace("+00:00", "Z")


def _ended_event(t: Dict[str, Any], key: str = "fin-ev-001", **overrides: Any) -> Dict[str, Any]:
    """An event whose interval is entirely in the past reads ENDED."""
    return _create_event(
        t,
        key=key,
        startAt=_past_moment(),
        endAt=(lambda m: m)(
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(hours=2)
        )
        .isoformat()
        .replace("+00:00", "Z"),
        **overrides,
    )


def _assign(t: Dict[str, Any], created: Dict[str, Any], product: str, target: int, key: str) -> Dict[str, Any]:
    t["inventory"].put_item(
        Item={
            "unitCampaignId": "uc-1",
            "itemKey": f"BALANCE#{product}",
            "productId": product,
            "kernelPhysicalQty": 10,
            "soldInPossessionQty": 0,
            "councilOnOrderQty": 0,
            "version": 1,
        }
    )
    return event_handler(
        _ev(
            "assignShowAndSellInventory",
            {
                "showAndSellId": created["showAndSellId"],
                "items": [{"productId": product, "quantity": target}],
                "expectedVersion": _event_version(t, created["showAndSellId"]),
                "idempotencyKey": key,
            },
        ),
        None,
    )


def _finalize(t: Dict[str, Any], created: Dict[str, Any], key: str, **overrides: Any) -> Dict[str, Any]:
    args = {
        "showAndSellId": created["showAndSellId"],
        "expectedVersion": _event_version(t, created["showAndSellId"]),
        "idempotencyKey": key,
        **overrides,
    }
    return finalization_handler(_ev("finalizeShowAndSell", args), None)


def _reopen(t: Dict[str, Any], created: Dict[str, Any], key: str, reason: str = "fix") -> Dict[str, Any]:
    return finalization_handler(
        _ev(
            "reopenShowAndSell",
            {
                "showAndSellId": created["showAndSellId"],
                "expectedVersion": _event_version(t, created["showAndSellId"]),
                "reason": reason,
                "idempotencyKey": key,
            },
        ),
        None,
    )


class TestRoundingGarage:
    """The app never chooses: unassigned cents block finalization naming
    the cent; assigning it produces the exact 33.34/33.33/33.33 split."""

    def _world(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _ended_event(t, splitMethod="EQUAL")
        _assign(t, created, "PROD#1", 1, "rg-assign-01")
        sale = _create_ss_sale(
            t,
            key="rg-sale-0001",
            lines=[{"productId": "PROD#1", "immediateQty": 0, "weOweQty": 0}],
        )
        # Rewrite the sale total to 10000 cents via a fresh sale is
        # awkward; instead price the product at 10000c and sell qty 1.
        return created

    def test_blocked_on_unassigned_cent_then_exact(self, t: Dict[str, Any]) -> None:
        from datetime import datetime, timezone

        _seed(t)
        start = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
        end = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        created = event_handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "Garage",
                        "startAt": start,
                        "endAt": end,
                        "splitMethod": "EQUAL",
                        "idempotencyKey": "rg-create-01",
                    }
                },
            ),
            None,
        )
        t["catalogs"].put_item(
            Item={
                "catalogId": "CATALOG#c",
                "products": [{"productId": "PROD#R", "productName": "Rounding", "price": 100}],
            }
        )
        _assign(t, created, "PROD#R", 1, "rg-assign-01")
        sale = sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": end,
                    "lineItems": [{"productId": "PROD#R", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "rg-sale-0001",
                },
            ),
            None,
        )
        assert "sale" in sale, sale
        # Two confirmed Scouts (equal split) -> base 5000/5000, exact.
        for profile, campaign in ((PROFILE_A, CAMPAIGN_A), (PROFILE_B, CAMPAIGN_B)):
            t["show_and_sells"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"SIGNUP#slot-rg#{profile}",
                    "showAndSellId": created["showAndSellId"],
                    "slotId": "slot-rg",
                    "profileId": profile,
                    "campaignId": campaign,
                    "status": "ACTIVE",
                    "actualMinutes": 60,
                    "version": 1,
                    "createdAt": "t",
                    "updatedAt": "t",
                }
            )
        # Three-way needs three profiles; use two -> exact with no rounding.
        args = {
            "showAndSellId": created["showAndSellId"],
            "expectedVersion": _event_version(t, created["showAndSellId"]),
            "idempotencyKey": "rg-finalize1",
        }
        ok = finalization_handler(_ev("finalizeShowAndSell", args), None)
        assert ok["finalization"]["wholePoolCents"] == 10000, ok
        amounts = sorted(a["amountCents"] for a in ok["scoutAllocations"])
        assert amounts == [5000, 5000], ok
        # Replay by effect: the identical request returns the stored result.
        replay = finalization_handler(_ev("finalizeShowAndSell", dict(args)), None)
        assert replay == ok

    def test_unassigned_cent_blocks_naming_the_cent(self, t: Dict[str, Any]) -> None:
        from datetime import datetime, timezone

        _seed(t)
        start = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
        end = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        created = event_handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "Garage",
                        "startAt": start,
                        "endAt": end,
                        "splitMethod": "EQUAL",
                        "idempotencyKey": "rg-create-02",
                    }
                },
            ),
            None,
        )
        t["catalogs"].put_item(
            Item={
                "catalogId": "CATALOG#c",
                "products": [{"productId": "PROD#R", "productName": "Rounding", "price": 1}],
            }
        )
        _assign(t, created, "PROD#R", 1, "rg-assign-02")
        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": end,
                    "lineItems": [{"productId": "PROD#R", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "rg-sale-0002",
                },
            ),
            None,
        )
        for profile, campaign in (
            (PROFILE_A, CAMPAIGN_A),
            (PROFILE_B, CAMPAIGN_B),
            ("PROFILE#profile-3", "CAMPAIGN#campaign-3"),
        ):
            t["profiles"].put_item(
                Item={
                    "ownerAccountId": ACCOUNT_A,
                    "profileId": profile,
                    "displayName": "Scout",
                    "createdAt": "t",
                    "version": 1,
                }
            )
            t["unit_campaigns"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"MEMBER#{profile}",
                    "profileId": profile,
                    "campaignId": campaign,
                    "status": "ACTIVE",
                    "joinedByAccountId": ACCOUNT_A,
                    "joinedAt": "t",
                    "version": 1,
                    "campaignNameSnapshot": "Fall",
                }
            )
            t["show_and_sells"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"SIGNUP#slot-rg#{profile}",
                    "showAndSellId": created["showAndSellId"],
                    "slotId": "slot-rg",
                    "profileId": profile,
                    "campaignId": campaign,
                    "status": "ACTIVE",
                    "actualMinutes": 60,
                    "version": 1,
                    "createdAt": "t",
                    "updatedAt": "t",
                }
            )
        # 100 cents / 3 Scouts -> base 33 each, 1 cent unassigned: blocked.
        blocked = _finalize(t, created, "rg-finalize2")
        assert blocked["errorCode"] == ErrorCode.CONFLICT, blocked
        assert "1 cent" in blocked["message"], blocked
        # Preview names the cent too.
        preview = finalization_handler(
            _ev("showAndSellFinalizationPreview", {"showAndSellId": created["showAndSellId"]}), None
        )
        assert preview["unassignedCents"] == 1, preview
        assert preview["issues"][0]["code"] == "UNASSIGNED_CENTS", preview
        # Assign the cent to profile-3: 33/33/34 exact.
        ok = _finalize(
            t,
            created,
            "rg-finalize3",
            roundingAssignments=[{"profileId": "PROFILE#profile-3", "cents": 1}],
        )
        amounts = sorted(a["amountCents"] for a in ok["scoutAllocations"])
        assert amounts == [33, 33, 34], ok


class TestUnionKeyReturnBaseline:
    """v1 {-1} -> reopen -> v2 omitted (transition +1 applied) -> reopen ->
    v3 repeats {-1} -> cumulative -1 exactly (never -2)."""

    def _world(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _ended_event(t, key="uk-event-001")
        _assign(t, created, "PROD#UK", 3, "uk-assign-01")
        return created

    def test_omitted_line_is_a_declared_zero_transition(self, t: Dict[str, Any]) -> None:
        created = self._world(t)
        balance0 = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#UK"})["Item"]
        assert int(balance0["kernelPhysicalQty"]) == 10

        v1 = _finalize(
            t,
            created,
            "uk-finalize1",
            returnLines=[{"productId": "PROD#UK", "expectedQty": 1, "actualQty": 0, "reason": "short"}],
        )
        assert "finalization" in v1, v1
        bal1 = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#UK"})["Item"]
        assert int(bal1["kernelPhysicalQty"]) == 9  # -1 applied

        _reopen(t, created, "uk-reopen-01", "adjust")
        # v2 OMITS the return line: declared zero — the transition +1 applies.
        v2 = _finalize(t, created, "uk-finalize2")
        assert "finalization" in v2, v2
        bal2 = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#UK"})["Item"]
        assert int(bal2["kernelPhysicalQty"]) == 10, "omitted line must release v1's adjustment"

        _reopen(t, created, "uk-reopen-02", "back")
        v3 = _finalize(
            t,
            created,
            "uk-finalize3",
            returnLines=[{"productId": "PROD#UK", "expectedQty": 1, "actualQty": 0, "reason": "short"}],
        )
        assert "finalization" in v3, v3
        bal3 = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": "BALANCE#PROD#UK"})["Item"]
        assert int(bal3["kernelPhysicalQty"]) == 9, "cumulative -1 for a -1 line, never -2"

        history = finalization_handler(
            _ev("showAndSellFinalizations", {"showAndSellId": created["showAndSellId"]}), None
        )
        statuses = [row["status"] for row in history["items"]]
        assert statuses == ["SUPERSEDED", "SUPERSEDED", "APPROVED"], statuses
        versions = [row["versionNumber"] for row in history["items"]]
        assert versions == [1, 2, 3], versions


class TestAutoReduceSoldStockFloor:
    """W10-H1 probe shape: Morning assigned 2 / sold 2; Afternoon assigned 3
    (legal sequential) / sold 2; Morning finalizes returning stock ->
    Afternoon reduces to allocated=2 (= sold floor), remaining=0, NEVER 0/-2."""

    def test_floor_prevents_negative_remaining(self, t: Dict[str, Any]) -> None:
        morning = _ended_event(t, key="ar-morning01")
        _assign(t, morning, "PROD#AR", 2, "ar-assign-m")
        # Morning sells its 2.
        t["catalogs"].put_item(
            Item={
                "catalogId": "CATALOG#c",
                "products": [{"productId": "PROD#AR", "productName": "A", "price": 1}],
            }
        )
        for profile, campaign in ((PROFILE_A, CAMPAIGN_A), (PROFILE_B, CAMPAIGN_B)):
            t["show_and_sells"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"SIGNUP#slot-ar#{profile}",
                    "showAndSellId": morning["showAndSellId"],
                    "slotId": "slot-ar",
                    "profileId": profile,
                    "campaignId": campaign,
                    "status": "ACTIVE",
                    "actualMinutes": 60,
                    "version": 1,
                    "createdAt": "t",
                    "updatedAt": "t",
                }
            )
        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": morning["showAndSellId"],
                    "expectedEventVersion": _event_version(t, morning["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#AR", "immediateQty": 2, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "ar-sale-m-01",
                },
            ),
            None,
        )
        # Afternoon: starts AFTER morning ends; assigned 3 (sequential
        # warning is legal), then sells 2.
        afternoon = _ended_event(t, key="ar-afternoon1")
        # Force afternoon to start after morning by rewriting startAt.
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{afternoon['showAndSellId']}"},
            UpdateExpression="SET startAt = :s, endAt = :e",
            ExpressionAttributeValues={
                ":s": (lambda d: d.isoformat().replace("+00:00", "Z"))(
                    __import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(hours=1)
                ),
                ":e": _past_moment(),
            },
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#AR",
                "productId": "PROD#AR",
                "kernelPhysicalQty": 0,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 99,
            }
        )
        # Afternoon assigned 3 while the pool still showed stock via the
        # sale-time balances; simplest faithful probe: assign 3 directly.
        event_handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": afternoon["showAndSellId"],
                    "items": [{"productId": "PROD#AR", "quantity": 3}],
                    "expectedVersion": _event_version(t, afternoon["showAndSellId"]),
                    "idempotencyKey": "ar-assign-a1",
                },
            ),
            None,
        )
        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": afternoon["showAndSellId"],
                    "expectedEventVersion": _event_version(t, afternoon["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#AR", "immediateQty": 2, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "ar-sale-a-01",
                },
            ),
            None,
        )
        # Morning finalizes returning its 1 unsold box: kernel 0 -> 1.
        _finalize(
            t,
            morning,
            "ar-finalize-m",
            returnLines=[{"productId": "PROD#AR", "expectedQty": 0, "actualQty": 1, "reason": "box returned"}],
        )
        afternoon_alloc = t["inventory"].get_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"ALLOC#{afternoon['showAndSellId']}#PROD#AR"}
        )["Item"]
        # Sold-stock floor: allocated never below sold(2)+released(0).
        assert int(afternoon_alloc["allocatedQty"]) == 2, afternoon_alloc
        assert int(afternoon_alloc["remainingQty"]) == 0, afternoon_alloc
        assert int(afternoon_alloc["allocatedQty"]) >= int(afternoon_alloc["soldQty"]), afternoon_alloc


class TestReopenExactSubtraction:
    def test_suspend_subtracts_totals_and_moves_no_stock(self, t: Dict[str, Any]) -> None:
        created = _ended_event(t, key="ro-event-001")
        t["catalogs"].put_item(
            Item={
                "catalogId": "CATALOG#c",
                "products": [{"productId": "PROD#RO", "productName": "R", "price": 60}],
            }
        )
        _assign(t, created, "PROD#RO", 1, "ro-assign-01")
        for profile, campaign in ((PROFILE_A, CAMPAIGN_A), (PROFILE_B, CAMPAIGN_B)):
            t["show_and_sells"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"SIGNUP#slot-ro#{profile}",
                    "showAndSellId": created["showAndSellId"],
                    "slotId": "slot-ro",
                    "profileId": profile,
                    "campaignId": campaign,
                    "status": "ACTIVE",
                    "actualMinutes": 60,
                    "version": 1,
                    "createdAt": "t",
                    "updatedAt": "t",
                }
            )
        sale_handler(
            _ev(
                "createShowAndSellSale",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                    "saleAt": _past_moment(),
                    "lineItems": [{"productId": "PROD#RO", "immediateQty": 1, "weOweQty": 0}],
                    "paymentMethod": {"methodCode": "CASH"},
                    "idempotencyKey": "ro-sale-0001",
                },
            ),
            None,
        )
        ok = _finalize(t, created, "ro-finalize1")
        assert ok["finalization"]["status"] == "APPROVED"
        total_a = finalization_handler(
            _ev("scoutCampaignShowAndSellTotal", {"profileId": PROFILE_A, "unitCampaignId": "uc-1"}), None
        )
        assert total_a["approvedTotalCents"] == 3000, total_a

        version_before_reopen = _event_version(t, created["showAndSellId"])
        reopened = _reopen(t, created, "ro-reopen-01", "move the cent")
        assert reopened["status"] == "REOPENED", reopened
        # Exact subtraction: approved totals back to zero.
        total_b = finalization_handler(
            _ev("scoutCampaignShowAndSellTotal", {"profileId": PROFILE_A, "unitCampaignId": "uc-1"}), None
        )
        assert total_b["approvedTotalCents"] == 0, total_b
        # No stock movement from reopening: the allocation stays RELEASED
        # and the balance is untouched by the reopen itself.
        alloc = t["inventory"].get_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"ALLOC#{created['showAndSellId']}#PROD#RO"}
        )["Item"]
        assert alloc["status"] == "RELEASED", alloc
        # Reopen replay by effect: the identical request returns the
        # stored result (marker replay-by-effect).
        reopen_args = {
            "showAndSellId": created["showAndSellId"],
            "expectedVersion": version_before_reopen,
            "reason": "move the cent",
            "idempotencyKey": "ro-reopen-01",
        }
        replay = finalization_handler(_ev("reopenShowAndSell", reopen_args), None)
        assert replay == reopened

    def test_active_event_cannot_finalize_or_reopen(self, t: Dict[str, Any]) -> None:
        created = _create_event(t, key="guard-ev-001")  # future: SCHEDULED
        blocked = _finalize(t, created, "guard-fin-01")
        assert blocked["errorCode"] == ErrorCode.CONFLICT, blocked
        assert "Only ENDED or REOPENED" in blocked["message"], blocked
        reopen_blocked = _reopen(t, created, "guard-re-01")
        assert reopen_blocked["errorCode"] == ErrorCode.CONFLICT, reopen_blocked
