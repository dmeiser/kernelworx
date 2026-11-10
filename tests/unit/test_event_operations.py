"""
Unit tests for src/handlers/event_operations.py and the wave-4 participant
queries (Show & Sell wave 4, checklist 3.1-3.4).

Covers the 9.1 state machine (derived statuses around the interval), time
immutability (update input has no time fields), the allocation planner
(TARGET-not-delta, sold-stock protection, sequential-warn vs
concurrent-block), the 20-slot cap, the signup sequence contract (roster
membership = finalization feasibility), work confirmation, and
committed-replay idempotency.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import boto3
import pytest

from src.handlers.event_operations import handler
from src.utils.errors import ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"
ACCOUNT_B = "ACCOUNT#user-789"
PROFILE_A = "PROFILE#profile-1"
PROFILE_B = "PROFILE#profile-2"
CAMPAIGN_A = "CAMPAIGN#campaign-1"
CAMPAIGN_B = "CAMPAIGN#campaign-2"

NOW = datetime.now(timezone.utc)


def _grid(moment: Any) -> Any:
    return moment.replace(minute=(moment.minute // 30) * 30, second=0, microsecond=0) + timedelta(days=1)


FUTURE_START = _grid(NOW).isoformat().replace("+00:00", "Z")
FUTURE_END = (_grid(NOW) + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
LATER_START = (_grid(NOW) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
LATER_END = (_grid(NOW) + timedelta(days=1, hours=3)).isoformat().replace("+00:00", "Z")
PAST_START = (NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z")
PAST_END = (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "show_and_sells": dynamodb.Table("kernelworx-show-and-sells-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
    }


def _seed(t: Dict[str, Any], second_member: bool = True) -> None:
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
    members = [(PROFILE_A, CAMPAIGN_A, ACCOUNT_A)]
    if second_member:
        members.append((PROFILE_B, CAMPAIGN_B, ACCOUNT_B))
    for profile_id, campaign_id, owner in members:
        t["profiles"].put_item(
            Item={
                "ownerAccountId": owner,
                "profileId": profile_id,
                "displayName": "Scout",
                "createdAt": "t",
                "version": 1,
            }
        )
        t["campaigns"].put_item(
            Item={
                "profileId": profile_id,
                "campaignId": campaign_id,
                "campaignName": "Fall Sale",
                "campaignYear": 2026,
                "catalogId": "CATALOG#c",
                "unitCampaignKey": "uc-1",
                "isActive": True,
                "version": 1,
                "createdAt": "t",
            }
        )
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"MEMBER#{profile_id}",
                "profileId": profile_id,
                "campaignId": campaign_id,
                "status": "ACTIVE",
                "joinedByAccountId": owner,
                "joinedAt": "t",
                "version": 1,
                "campaignNameSnapshot": "Fall Sale",
            }
        )


def _ev(field: str, args: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {"arguments": args, "identity": {"sub": sub, "username": sub}, "info": {"fieldName": field}}


def _create_event(t: Dict[str, Any], key: str = "ev-create-1", **overrides: Any) -> Dict[str, Any]:
    _seed(t)
    input_args = {
        "unitCampaignId": "uc-1",
        "locationName": "Grocery Store",
        "startAt": FUTURE_START,
        "endAt": FUTURE_END,
        "idempotencyKey": key,
        **overrides,
    }
    return handler(_ev("createShowAndSell", {"input": input_args}), None)


def _event_version(t: Dict[str, Any], show_and_sell_id: str) -> int:
    read = handler(_ev("showAndSell", {"showAndSellId": show_and_sell_id}), None)
    return int(read["version"])


class TestCreateEvent:
    def test_success_with_derived_status(self, t: Dict[str, Any]) -> None:
        result = _create_event(t)
        assert result["status"] == "SCHEDULED"
        assert result["splitMethod"] == "EQUAL"
        assert result["weOweEnabled"] is False
        assert result["slots"] == [] and result["slotCount"] == 0
        assert result["createdByAccountId"] == ACCOUNT_A

    def test_end_before_start_rejected(self, t: Dict[str, Any]) -> None:
        result = _create_event(t, startAt=FUTURE_END, endAt=FUTURE_START)
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_bad_enum_and_flag_rejected(self, t: Dict[str, Any]) -> None:
        assert _create_event(t, splitMethod="RATIO")["errorCode"] == ErrorCode.INVALID_INPUT
        assert _create_event(t, weOweEnabled="yes")["errorCode"] == ErrorCode.INVALID_INPUT

    def test_unknown_unit_campaign(self, t: Dict[str, Any]) -> None:
        result = _create_event(t, unitCampaignId="UC#ghost")
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_replay(self, t: Dict[str, Any]) -> None:
        first = _create_event(t, key="ev-replay-1")
        second = _create_event(t, key="ev-replay-1")
        assert second == first


class TestUpdateAndCancel:
    def _created(self, t: Dict[str, Any]) -> Dict[str, Any]:
        return _create_event(t)

    def test_update_fields(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        result = handler(
            _ev(
                "updateShowAndSell",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "locationName": "New Venue",
                        "splitMethod": "TIME_WORKED",
                        "weOweEnabled": True,
                        "expectedVersion": 1,
                        "idempotencyKey": "ev-upd-001",
                    }
                },
            ),
            None,
        )
        assert result["locationName"] == "New Venue"
        assert result["splitMethod"] == "TIME_WORKED"
        assert result["version"] == 2

    def test_version_mismatch_and_cancelled_guard(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        stale = handler(
            _ev(
                "updateShowAndSell",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "locationName": "X",
                        "expectedVersion": 9,
                        "idempotencyKey": "ev-upd-002",
                    }
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "weather",
                    "idempotencyKey": "ev-cancel1",
                },
            ),
            None,
        )
        cancelled_update = handler(
            _ev(
                "updateShowAndSell",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "locationName": "X",
                        "expectedVersion": 2,
                        "idempotencyKey": "ev-upd-003",
                    }
                },
            ),
            None,
        )
        assert cancelled_update["errorCode"] == ErrorCode.CONFLICT

    def test_cancel_marks_status(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        result = handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "weather",
                    "idempotencyKey": "ev-cancel2",
                },
            ),
            None,
        )
        assert result["status"] == "CANCELLED"
        assert result["cancelledByAccountId"] == ACCOUNT_A


class TestAllocationPlanner:
    def _with_stock(self, t: Dict[str, Any], qty: int = 10) -> Dict[str, Any]:
        created = _create_event(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#1",
                "productId": "PROD#1",
                "kernelPhysicalQty": qty,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        return created

    def _assign(self, created: Dict[str, Any], target: int, key: str = "ev-assign1") -> Dict[str, Any]:
        return handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": target}],
                    "expectedVersion": created["version"],
                    "idempotencyKey": key,
                },
            ),
            None,
        )

    def test_target_assignment(self, t: Dict[str, Any]) -> None:
        created = self._with_stock(t)
        result = self._assign(created, 6)
        assert result["allocations"][0]["allocatedQty"] == 6
        assert result["allocations"][0]["remainingQty"] == 6
        assert result["warnings"] == []
        # TARGET-not-delta: re-assigning sets the absolute target.
        bumped = self._assign(
            handler(
                _ev("showAndSell", {"showAndSellId": created["showAndSellId"]}),
                None,
            ),
            8,
            key="ev-assign2",
        )
        assert bumped["allocations"][0]["allocatedQty"] == 8

    def test_sequential_warns_concurrent_blocks(self, t: Dict[str, Any]) -> None:
        created = self._with_stock(t, qty=5)
        first = self._assign(created, 4)
        assert first["warnings"] == []
        # Second event overlapping the first: 4 + 4 = 8 > 5 concurrent -> hard block.
        second = _create_event(t, key="ev-second1", startAt=LATER_START, endAt=LATER_END)
        overlap_start = _grid(NOW) + timedelta(hours=1)
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{second['showAndSellId']}"},
            UpdateExpression="SET startAt = :s, endAt = :e",
            ExpressionAttributeValues={
                ":s": overlap_start.isoformat().replace("+00:00", "Z"),
                ":e": (overlap_start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        )
        blocked = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": second["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": 4}],
                    "expectedVersion": second["version"],
                    "idempotencyKey": "ev-assign3",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT
        # Non-overlapping (sequential): warn, never block.
        far = _create_event(t, key="ev-far-001", startAt=LATER_START, endAt=LATER_END)
        warned = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": far["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": 4}],
                    "expectedVersion": far["version"],
                    "idempotencyKey": "ev-assign4",
                },
            ),
            None,
        )
        assert warned["warnings"][0]["code"] == "SEQUENTIAL_OVER_ASSIGNMENT"

    def test_sold_stock_protection_and_dedup(self, t: Dict[str, Any]) -> None:
        created = self._with_stock(t)
        self._assign(created, 6)
        # Manufacture sold quantity, then try to assign below it.
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{created['showAndSellId']}#PROD#1",
                "productId": "PROD#1",
                "showAndSellId": created["showAndSellId"],
                "eventStartAt": created["startAt"],
                "eventEndAt": created["endAt"],
                "status": "OPEN",
                "allocatedQty": 6,
                "soldQty": 5,
                "releasedQty": 0,
                "remainingQty": 1,
                "version": 2,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        low = self._assign(
            handler(_ev("showAndSell", {"showAndSellId": created["showAndSellId"]}), None),
            3,
            key="ev-assign5",
        )
        assert low["errorCode"] == ErrorCode.CONFLICT
        dup = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": 1}, {"productId": "PROD#1", "quantity": 2}],
                    "expectedVersion": 3,
                    "idempotencyKey": "ev-assign6",
                },
            ),
            None,
        )
        assert dup["errorCode"] == ErrorCode.INVALID_INPUT


class TestSlots:
    def _created(self, t: Dict[str, Any]) -> Dict[str, Any]:
        return _create_event(t)

    def _upsert(self, created: Dict[str, Any], key: str = "ev-slot-01", **kwargs: Any) -> Dict[str, Any]:
        return handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": created["version"],
                        "idempotencyKey": key,
                        **kwargs,
                    }
                },
            ),
            None,
        )

    def test_create_and_update_slot(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        slot = self._upsert(created, label="Morning")
        assert slot["slotId"] and slot["capacity"] == 4
        updated = self._upsert(
            created,
            key="ev-slot-02",
            slotId=slot["slotId"],
            capacity=6,
            expectedEventVersion=_event_version(t, created["showAndSellId"]),
            expectedSlotVersion=1,
        )
        assert updated["capacity"] == 6
        assert updated["version"] == 2

    def test_twenty_cap(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        for i in range(20):
            result = self._upsert(
                created,
                key=f"ev-cap-{i:03d}",
                label=f"S{i}",
                expectedEventVersion=_event_version(t, created["showAndSellId"]),
            )
            assert "slotId" in result, result
        blocked = self._upsert(
            created, key="ev-cap-021", expectedEventVersion=_event_version(t, created["showAndSellId"])
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT

    def test_delete_slot_removes_signups(self, t: Dict[str, Any]) -> None:
        created = self._created(t)
        slot = self._upsert(created)
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "ev-sign-01",
                },
            ),
            None,
        )
        deleted = handler(
            _ev(
                "deleteShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "expectedVersion": _event_version(t, created["showAndSellId"]),
                    "idempotencyKey": "ev-del-001",
                },
            ),
            None,
        )
        assert deleted is True
        signups = t["show_and_sells"].scan()["Items"]
        assert not [s for s in signups if s["itemKey"].startswith("SIGNUP#")]


class TestSignups:
    def _world(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _create_event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 1,
                        "expectedEventVersion": created["version"],
                        "idempotencyKey": "ev-su-slot1",
                    }
                },
            ),
            None,
        )
        return {"event": created, "slot": slot}

    def test_signup_and_cancel(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        signup = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "ev-su-0001",
                },
            ),
            None,
        )
        assert signup["status"] == "ACTIVE"
        cancelled = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": signup["version"],
                    "idempotencyKey": "ev-su-0002",
                },
            ),
            None,
        )
        assert cancelled["status"] == "CANCELLED"

    def test_capacity_blocks(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "ev-su-0003",
                },
            ),
            None,
        )
        full = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_B,
                    "profileId": PROFILE_B,
                    "idempotencyKey": "ev-su-0004",
                },
                sub="user-789",
            ),
            None,
        )
        assert full["errorCode"] == ErrorCode.CONFLICT

    def test_non_member_blocked_and_forbidden(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        t["unit_campaigns"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"MEMBER#{PROFILE_B}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "REMOVED"},
        )
        not_member = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_B,
                    "profileId": PROFILE_B,
                    "idempotencyKey": "ev-su-0005",
                },
                sub="user-789",
            ),
            None,
        )
        assert not_member["errorCode"] == ErrorCode.CONFLICT
        # Caller without campaign access is FORBIDDEN.
        t["unit_campaigns"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"MEMBER#{PROFILE_B}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "ACTIVE"},
        )
        forbidden = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_B,
                    "profileId": PROFILE_B,
                    "idempotencyKey": "ev-su-0006",
                },
            ),
            None,
        )
        assert forbidden["errorCode"] == ErrorCode.FORBIDDEN


class TestWorkConfirmation:
    def test_confirm_work(self, t: Dict[str, Any]) -> None:
        created = _create_event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": created["version"],
                        "idempotencyKey": "ev-wc-slot1",
                    }
                },
            ),
            None,
        )
        signup = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "ev-wc-su-01",
                },
            ),
            None,
        )
        assert signup["status"] == "ACTIVE"
        result = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 90}],
                    "expectedVersion": 3,
                    "idempotencyKey": "ev-wc-0001",
                },
            ),
            None,
        )
        assert result["pendingPreview"]["totalConfirmedMinutes"] == 90
        assert result["signups"][0]["confirmedByAccountId"] == ACCOUNT_A
        missing = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": slot["slotId"], "profileId": PROFILE_B, "actualMinutes": 30}],
                    "expectedVersion": 4,
                    "idempotencyKey": "ev-wc-0002",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND


class TestEventQueries:
    def test_show_and_sell_reads(self, t: Dict[str, Any]) -> None:
        created = _create_event(t)
        read = handler(_ev("showAndSell", {"showAndSellId": created["showAndSellId"]}), None)
        assert read["showAndSellId"] == created["showAndSellId"]
        missing = handler(_ev("showAndSell", {"showAndSellId": "SS#ghost"}), None)
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

    def test_list_with_status_filter_and_past(self, t: Dict[str, Any]) -> None:
        _create_event(t, key="ev-query-001")
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "EVENT#past-one",
                "showAndSellId": "past-one",
                "saleId": "past-one",
                "unitId": "unit-1",
                "locationName": "Old",
                "startAt": PAST_START,
                "endAt": PAST_END,
                "status": "SCHEDULED",
                "splitMethod": "EQUAL",
                "weOweEnabled": False,
                "version": 1,
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        ended = handler(_ev("showAndSells", {"unitCampaignId": "uc-1", "status": "ENDED"}), None)
        assert [i["showAndSellId"] for i in ended["items"]] == ["past-one"]
        scheduled = handler(_ev("showAndSells", {"unitCampaignId": "uc-1", "status": "SCHEDULED"}), None)
        assert len(scheduled["items"]) == 1

    def test_signup_and_allocation_queries(self, t: Dict[str, Any]) -> None:
        created = _create_event(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#1",
                "productId": "PROD#1",
                "kernelPhysicalQty": 10,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": 4}],
                    "expectedVersion": created["version"],
                    "idempotencyKey": "ev-q-assign",
                },
            ),
            None,
        )
        allocations = handler(
            _ev("eventInventoryAllocations", {"unitCampaignId": "uc-1", "showAndSellId": created["showAndSellId"]}),
            None,
        )
        assert allocations["items"][0]["allocatedQty"] == 4
        signups = handler(_ev("showAndSellSignups", {"showAndSellId": created["showAndSellId"]}), None)
        assert signups["items"] == []


class TestParticipantReads:
    def _world(self, t: Dict[str, Any]) -> Dict[str, Any]:
        from src.handlers.participant_data import handler as participant_handler

        created = _create_event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "label": "Shift A",
                        "expectedEventVersion": created["version"],
                        "idempotencyKey": "ev-pr-slot01",
                    }
                },
            ),
            None,
        )
        signup = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "ev-pr-su-001",
                },
            ),
            None,
        )
        return {
            "participant": participant_handler,
            "event": created,
            "slot": slot,
            "signup": signup,
        }

    def test_opportunities_listing(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        result = world["participant"](
            _ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"}, sub="user-123-456"), None
        )
        assert len(result["items"]) == 1
        opp = result["items"][0]
        assert opp["locationName"] == "Grocery Store"
        assert opp["timezone"] == "America/Denver"
        assert opp["eligibleScouts"] == [{"profileId": PROFILE_A, "campaignId": CAMPAIGN_A}]
        assert opp["eligibleProfileIds"] == [PROFILE_A]
        assert opp["slots"][0]["signedUpProfileIds"] == [PROFILE_A]
        # includePast adds nothing here; cancelled events are hidden.
        assert world["participant"](
            _ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1", "includePast": True}), None
        )["items"]

    def test_opportunity_detail_and_guards(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        detail = world["participant"](
            _ev(
                "showAndSellOpportunity",
                {"showAndSellId": world["event"]["showAndSellId"], "profileId": PROFILE_A},
            ),
            None,
        )
        assert detail["showAndSellId"] == world["event"]["showAndSellId"]
        missing = world["participant"](
            _ev("showAndSellOpportunity", {"showAndSellId": "SS#ghost", "profileId": PROFILE_A}), None
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        wrong_scout = world["participant"](
            _ev(
                "showAndSellOpportunity",
                {"showAndSellId": world["event"]["showAndSellId"], "profileId": PROFILE_B},
                sub="user-123-456",
            ),
            None,
        )
        assert wrong_scout["errorCode"] == ErrorCode.NOT_FOUND
        bad_args = world["participant"](_ev("showAndSellOpportunity", {"showAndSellId": 5}), None)
        assert bad_args["errorCode"] == ErrorCode.INVALID_INPUT

    def test_commitments_and_calendar(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        commitments = world["participant"](_ev("myScoutCommitments", {"profileId": PROFILE_A}), None)
        assert len(commitments["items"]) == 1
        assert commitments["items"][0]["slotId"] == world["slot"]["slotId"]
        calendar = world["participant"](
            _ev(
                "showAndSellSignupCalendarData",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "profileId": PROFILE_A,
                },
            ),
            None,
        )
        assert calendar["startAtUtc"] == FUTURE_START
        assert calendar["campaignId"] == CAMPAIGN_A
        missing = world["participant"](
            _ev(
                "showAndSellSignupCalendarData",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "profileId": PROFILE_B,
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        forbidden = world["participant"](_ev("myScoutCommitments", {"profileId": PROFILE_B}, sub="user-123-456"), None)
        assert forbidden["errorCode"] == ErrorCode.NOT_FOUND

    def test_participant_validation_errors(self, t: Dict[str, Any]) -> None:
        world = self._world(t)
        p = world["participant"]
        assert p(_ev("unitCampaignOpportunities", {}), None)["errorCode"] == ErrorCode.INVALID_INPUT
        assert p(_ev("myScoutCommitments", {}), None)["errorCode"] == ErrorCode.INVALID_INPUT
        assert p(_ev("showAndSellSignupCalendarData", {}), None)["errorCode"] == ErrorCode.INVALID_INPUT
        ghost = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "UC#ghost"}), None)
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND
        unknown = p(_ev("mysteryParticipantField", {}), None)
        assert unknown["errorCode"] == ErrorCode.INTERNAL_ERROR


class TestFeasibilityPreflight:
    """Spec 8.10 plan-time feasibility (wave-6 START precondition; record:
    docs/investigations/show-sell-8.10-feasibility-preflight.md). Formulas:
    assign 4+3xproducts <= 90; signup 4+3xproducts+2x(confirmed+active+1)
    +SIGNUPWINDOW bucket Puts <= 90 (buckets counted per the quantized
    duration, matching the write plan's actual Puts)."""

    def _with_stock(self, t: Dict[str, Any], products: int) -> Dict[str, Any]:
        created = _create_event(t)
        for index in range(1, products + 1):
            t["inventory"].put_item(
                Item={
                    "unitCampaignId": "uc-1",
                    "itemKey": f"BALANCE#PROD#{index}",
                    "productId": f"PROD#{index}",
                    "kernelPhysicalQty": 1,
                    "soldInPossessionQty": 0,
                    "councilOnOrderQty": 0,
                    "version": 1,
                }
            )
        return created

    def _assign_products(self, created: Dict[str, Any], count: int, key: str) -> Dict[str, Any]:
        return handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": f"PROD#{i}", "quantity": 1} for i in range(1, count + 1)],
                    "expectedVersion": created["version"],
                    "idempotencyKey": key,
                },
            ),
            None,
        )

    def test_assign_28_products_ok_29th_rejected_no_writes(self, t: Dict[str, Any]) -> None:
        created = self._with_stock(t, 29)
        ok = self._assign_products(created, 28, "pf-assign-28")
        assert "allocations" in ok, ok  # 4 + 3x28 = 88 <= 90
        event_id = created["showAndSellId"]
        version_after = _event_version(t, event_id)
        blocked = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": event_id,
                    "items": [{"productId": "PROD#29", "quantity": 1}],
                    "expectedVersion": version_after,
                    "idempotencyKey": "pf-assign-29",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT, blocked
        assert "OPERATION_TOO_LARGE" in blocked["message"], blocked
        assert "91 transaction actions" in blocked["message"], blocked
        assert "split the event" in blocked["message"], blocked
        # No writes on rejection: no PROD#29 allocation, event version unchanged.
        assert _event_version(t, event_id) == version_after
        alloc = t["inventory"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"ALLOC#{event_id}#PROD#29"})
        assert "Item" not in alloc

    def test_signup_formula_counts_window_buckets(self, t: Dict[str, Any]) -> None:
        created = self._with_stock(t, 25)
        assigned = self._assign_products(created, 25, "pf-signup-25")
        assert "allocations" in assigned, assigned  # 4 + 3x25 = 79
        event_id = created["showAndSellId"]

        def _slot(key: str, start: Any, end: Any) -> Dict[str, Any]:
            return handler(
                _ev(
                    "upsertShowAndSellSlot",
                    {
                        "input": {
                            "showAndSellId": event_id,
                            "startAt": start,
                            "endAt": end,
                            "capacity": 10,
                            "expectedEventVersion": _event_version(t, event_id),
                            "idempotencyKey": key,
                        }
                    },
                ),
                None,
            )

        grid = datetime.fromisoformat(FUTURE_START.replace("Z", "+00:00"))
        slot_short = _slot(
            "pf-slot-short-01",
            FUTURE_START,
            (grid + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        )
        slot_long = _slot("pf-slot-long-01", FUTURE_START, FUTURE_END)  # 3h = 6 buckets
        slot_mid = _slot(
            "pf-slot-mid-001",
            (grid + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            (grid + timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z"),
        )
        version_after_slots = _event_version(t, event_id)
        # confirmed counts actualMinutes > 0 even when the signup is no
        # longer ACTIVE; active counts ACTIVE rows. PROFILE_B's ACTIVE row
        # sits on slot_mid so neither target overlaps it.
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#{slot_short['slotId']}#{PROFILE_A}",
                "showAndSellId": event_id,
                "slotId": slot_short["slotId"],
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
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
                "itemKey": f"SIGNUP#{slot_mid['slotId']}#{PROFILE_B}",
                "showAndSellId": event_id,
                "slotId": slot_mid["slotId"],
                "profileId": PROFILE_B,
                "campaignId": CAMPAIGN_B,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        # confirmed=1, active=1 (the attempt is +1): base 79 + 2x(1+1+1)=85.
        # The ONLY difference between the two attempts is the SIGNUPWINDOW
        # bucket count: 6 buckets -> 91 > 90 rejects; 1 bucket -> 86 passes.
        blocked = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": event_id,
                    "slotId": slot_long["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "pf-signup-block1",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT, blocked
        assert "OPERATION_TOO_LARGE" in blocked["message"], blocked
        assert "91 transaction actions" in blocked["message"], blocked
        assert "actualMinutes = 0" in blocked["message"], blocked
        assert _event_version(t, event_id) == version_after_slots  # no writes
        ok = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": event_id,
                    "slotId": slot_short["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "pf-signup-ok-01",
                },
            ),
            None,
        )
        assert ok["status"] == "ACTIVE", ok  # 79 + 6 + 1 bucket = 86 <= 90

    def test_signup_stats_counts_per_event(self, t: Dict[str, Any]) -> None:
        from src.handlers.event_operations import _event_signup_stats

        _seed(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#s1#PROFILE#profile-1",
                "showAndSellId": "ev-1",
                "slotId": "s1",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 60,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#s1#PROFILE#profile-2",
                "showAndSellId": "ev-1",
                "slotId": "s1",
                "profileId": PROFILE_B,
                "campaignId": CAMPAIGN_B,
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
                "itemKey": "SIGNUP#s1#PROFILE#profile-x",
                "showAndSellId": "ev-OTHER",
                "slotId": "s1",
                "profileId": PROFILE_B,
                "campaignId": CAMPAIGN_B,
                "status": "ACTIVE",
                "actualMinutes": 45,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        assert _event_signup_stats("uc-1", "ev-1") == (1, 2)
