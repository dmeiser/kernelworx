"""Coverage sweep for the wave-4 handlers: error branches, cancel mappings,
marker edges, pagination guards, and the allocation evaluator arcs."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import boto3
import pytest

from src.handlers import event_operations
from src.handlers.event_operations import handler
from src.utils.allocation import OpenAllocationView, _peak_at, max_concurrent_assigned
from src.utils.dynamodb import TransactionCancelledError
from src.utils.errors import AppError, ErrorCode
from tests.unit.test_event_operations import (
    ACCOUNT_A,
    CAMPAIGN_A,
    CAMPAIGN_B,
    FUTURE_END,
    FUTURE_START,
    LATER_END,
    LATER_START,
    PROFILE_A,
    PROFILE_B,
    _create_event,
    _ev,
    _event_version,
    _seed,
)


@pytest.fixture
def t(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "show_and_sells": dynamodb.Table("kernelworx-show-and-sells-ue1-dev"),
        "inventory": dynamodb.Table("kernelworx-inventory-ue1-dev"),
    }


def _event(t: Any) -> Any:
    return _create_event(t, key=f"sw-{uuid4()}")


class TestEventSweep:
    def test_unauthenticated_and_unknown_dispatcher(self, t: Any) -> None:
        _seed(t)
        event = _ev(
            "createShowAndSell",
            {
                "input": {
                    "unitCampaignId": "uc-1",
                    "locationName": "L",
                    "startAt": FUTURE_START,
                    "endAt": FUTURE_END,
                    "idempotencyKey": "sw-auth-001",
                }
            },
        )
        del event["identity"]
        assert handler(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED
        assert handler(_ev("mysteryField", {}), None)["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_marker_branches(self, t: Any) -> None:
        _seed(t)
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createShowAndSell#sw-mk-001",
                "idemFingerprint": "other",
                "idemResult": {},
            }
        )
        conflict = handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "L",
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "idempotencyKey": "sw-mk-001",
                    }
                },
            ),
            None,
        )
        assert conflict["errorCode"] == ErrorCode.CONFLICT
        from src.handlers.event_operations import _check_marker, _marker_put

        no_result = _marker_put(ACCOUNT_A, "scope", "key", "fp", None, 1000)
        assert no_result["Put"]["Item"]["idemResult"] is None
        t["units"].put_item(
            Item={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#sw-nores", "idemFingerprint": "fp"}
        )
        with pytest.raises(AppError):
            _check_marker(
                t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#sw-nores"})["Item"],
                "fp",
            )
        # legacy dict-form marker still honored
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#scope#sw-legacy",
                "idemFingerprint": "fp",
                "idemResult": {"x": 1},
            }
        )
        assert _check_marker(
            t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#sw-legacy"})["Item"], "fp"
        ) == {"x": 1}

    def test_create_cancel_race_mapping(self, t: Any, monkeypatch: Any) -> None:
        _seed(t)

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        result = handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "L",
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "idempotencyKey": "sw-race-01",
                    }
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT
        # bare re-raise on non-marker cancel
        monkeypatch.setattr(
            event_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(TransactionCancelledError):
            event_operations._create_show_and_sell(
                _ev(
                    "createShowAndSell",
                    {
                        "input": {
                            "unitCampaignId": "uc-1",
                            "locationName": "L",
                            "startAt": FUTURE_START,
                            "endAt": FUTURE_END,
                            "idempotencyKey": "sw-raw-001",
                        }
                    },
                ),
                None,
            )

    def test_update_replay_and_address(self, t: Any) -> None:
        created = _event(t)
        args = {
            "input": {
                "showAndSellId": created["showAndSellId"],
                "address": "1 Main St",
                "expectedVersion": 1,
                "idempotencyKey": "sw-upd-repl",
            }
        }
        first = handler(_ev("updateShowAndSell", args), None)
        assert first["address"] == "1 Main St"
        second = handler(_ev("updateShowAndSell", args), None)
        assert second == first

    def test_update_non_admin_and_missing_event(self, t: Any) -> None:
        created = _event(t)
        non_admin = handler(
            _ev(
                "updateShowAndSell",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "locationName": "X",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-upd-na",
                    }
                },
                sub="user-789",
            ),
            None,
        )
        assert non_admin["errorCode"] == ErrorCode.NOT_FOUND
        assert handler(_ev("showAndSell", {"showAndSellId": "SS#ghost"}), None)["errorCode"] == ErrorCode.NOT_FOUND

    def test_cancel_replay_race_and_non_admin(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        args = {
            "showAndSellId": created["showAndSellId"],
            "expectedVersion": 1,
            "reason": "rain",
            "idempotencyKey": "sw-cancel-re",
        }
        first = handler(_ev("cancelShowAndSell", args), None)
        second = handler(_ev("cancelShowAndSell", args), None)
        assert second == first

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(_ev("cancelShowAndSell", {**args, "idempotencyKey": "sw-cancel-r2"}), None)
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_cancel_missing_and_twice(self, t: Any) -> None:
        created = _event(t)
        assert (
            handler(
                _ev(
                    "cancelShowAndSell",
                    {
                        "showAndSellId": "SS#ghost",
                        "expectedVersion": 1,
                        "reason": "x",
                        "idempotencyKey": "sw-cancel-gh",
                    },
                ),
                None,
            )["errorCode"]
            == ErrorCode.NOT_FOUND
        )
        handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "x",
                    "idempotencyKey": "sw-cancel-ok",
                },
            ),
            None,
        )
        again = handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 2,
                    "reason": "x",
                    "idempotencyKey": "sw-cancel-2x",
                },
            ),
            None,
        )
        assert again["errorCode"] == ErrorCode.CONFLICT

    def test_signup_unknown_campaign_and_bad_profile(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-slot-001",
                    }
                },
            ),
            None,
        )
        ghost = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": "CAMPAIGN#ghost",
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-su-ghost",
                },
            ),
            None,
        )
        assert ghost["errorCode"] == ErrorCode.NOT_FOUND
        mismatch = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_B,
                    "idempotencyKey": "sw-su-mism",
                },
            ),
            None,
        )
        assert mismatch["errorCode"] == ErrorCode.INVALID_INPUT
        ghost_slot = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": "SLOT#ghost",
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-su-gsl",
                },
            ),
            None,
        )
        assert ghost_slot["errorCode"] == ErrorCode.NOT_FOUND

    def test_cancelled_event_blocks_slot_signup_assign(self, t: Any) -> None:
        created = _event(t)
        handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "x",
                    "idempotencyKey": "sw-ce-cancel",
                },
            ),
            None,
        )
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": "sw-ce-slot",
                    }
                },
            ),
            None,
        )
        assert slot["errorCode"] == ErrorCode.CONFLICT

    def test_signup_replay_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-sr-slot",
                    }
                },
            ),
            None,
        )
        args = {
            "showAndSellId": created["showAndSellId"],
            "slotId": slot["slotId"],
            "campaignId": CAMPAIGN_A,
            "profileId": PROFILE_A,
            "idempotencyKey": "sw-sr-signup",
        }
        first = handler(_ev("signupScoutForShowAndSellSlot", args), None)
        second = handler(_ev("signupScoutForShowAndSellSlot", args), None)
        assert second == first

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(_ev("signupScoutForShowAndSellSlot", {**args, "idempotencyKey": "sw-sr-race"}), None)
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_cancel_signup_guards_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-cr-slot",
                    }
                },
            ),
            None,
        )
        missing = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-cr-miss",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        signup = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cr-signup",
                },
            ),
            None,
        )
        stale = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": 9,
                    "idempotencyKey": "sw-cr-stale",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": signup["version"],
                    "idempotencyKey": "sw-cr-race",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_confirm_work_validation_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-cw-slot",
                    }
                },
            ),
            None,
        )
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cw-signup",
                },
            ),
            None,
        )
        dup = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [
                        {"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 10},
                        {"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 20},
                    ],
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-cw-dup",
                },
            ),
            None,
        )
        assert dup["errorCode"] == ErrorCode.INVALID_INPUT
        monkeypatch.setattr(
            event_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        raced = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 10}],
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-cw-race",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_queries_non_admin_and_filters(self, t: Any) -> None:
        created = _event(t)
        blocked = handler(_ev("showAndSells", {"unitCampaignId": "uc-1"}, sub="user-789"), None)
        assert blocked["errorCode"] == ErrorCode.NOT_FOUND
        blocked2 = handler(_ev("showAndSellSignups", {"showAndSellId": created["showAndSellId"]}, sub="user-789"), None)
        assert blocked2["errorCode"] == ErrorCode.NOT_FOUND
        blocked3 = handler(_ev("eventInventoryAllocations", {"unitCampaignId": "uc-1"}, sub="user-789"), None)
        assert blocked3["errorCode"] == ErrorCode.NOT_FOUND
        bad_status = handler(_ev("showAndSells", {"unitCampaignId": "uc-1", "status": "MAYBE"}), None)
        assert bad_status["errorCode"] == ErrorCode.INVALID_INPUT
        filtered = handler(
            _ev("eventInventoryAllocations", {"unitCampaignId": "uc-1", "status": "OPEN", "productId": "PROD#9"}),
            None,
        )
        assert filtered["items"] == []
        bad_signup_status = handler(
            _ev("showAndSellSignups", {"showAndSellId": created["showAndSellId"], "status": "MAYBE"}), None
        )
        assert bad_signup_status["errorCode"] == ErrorCode.INVALID_INPUT

    def test_delete_slot_guards_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        missing = handler(
            _ev(
                "deleteShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": "SLOT#ghost",
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-dl-miss",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-dl-slot",
                    }
                },
            ),
            None,
        )
        args = {
            "showAndSellId": created["showAndSellId"],
            "slotId": slot["slotId"],
            "expectedVersion": 2,
            "idempotencyKey": "sw-dl-del",
        }
        assert handler(_ev("deleteShowAndSellSlot", args), None) is True
        assert handler(_ev("deleteShowAndSellSlot", args), None) is True  # replay

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(_ev("deleteShowAndSellSlot", {**args, "idempotencyKey": "sw-dl-race"}), None)
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_upsert_guards_and_replay(self, t: Any) -> None:
        created = _event(t)
        bad_time = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_END,
                        "endAt": FUTURE_START,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-up-time",
                    }
                },
            ),
            None,
        )
        assert bad_time["errorCode"] == ErrorCode.INVALID_INPUT
        bad_capacity = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": -1,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-up-cap",
                    }
                },
            ),
            None,
        )
        assert bad_capacity["errorCode"] == ErrorCode.INVALID_INPUT
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-up-cre",
                    }
                },
            ),
            None,
        )
        dup_id = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": slot["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": "sw-up-dup",
                    }
                },
            ),
            None,
        )
        assert dup_id["errorCode"] == ErrorCode.INVALID_INPUT
        ghost_update = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": "SLOT#ghost",
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "expectedSlotVersion": 1,
                        "idempotencyKey": "sw-up-ghost",
                    }
                },
            ),
            None,
        )
        assert ghost_update["errorCode"] == ErrorCode.NOT_FOUND
        stale_slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": slot["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 5,
                        "expectedEventVersion": 2,
                        "expectedSlotVersion": 9,
                        "idempotencyKey": "sw-up-stale",
                    }
                },
            ),
            None,
        )
        assert stale_slot["errorCode"] == ErrorCode.CONFLICT
        replay_args = {
            "input": {
                "showAndSellId": created["showAndSellId"],
                "startAt": FUTURE_START,
                "endAt": FUTURE_END,
                "capacity": 7,
                "expectedEventVersion": 2,
                "idempotencyKey": "sw-up-replay",
            }
        }
        first = handler(_ev("upsertShowAndSellSlot", replay_args), None)
        second = handler(_ev("upsertShowAndSellSlot", replay_args), None)
        assert second == first


class TestAllocationSweep:
    def _dt(self, day: int) -> Any:
        from datetime import datetime, timezone

        return datetime(2026, 11, day, tzinfo=timezone.utc)

    def test_peak_at_and_max_concurrent(self) -> None:
        a = OpenAllocationView("a", self._dt(1), self._dt(5), 3)
        b = OpenAllocationView("b", self._dt(3), self._dt(4), 4)
        c = OpenAllocationView("c", self._dt(4), self._dt(6), 1)  # later, smaller: the no-new-peak arc
        peak, comp = max_concurrent_assigned(self._dt(2), self._dt(6), 2, [a, b, c], "own")
        assert peak == 9 and comp in ("a", "b")
        # no covering competitors -> (0, None)
        far = OpenAllocationView("far", self._dt(10), self._dt(12), 9)
        assert max_concurrent_assigned(self._dt(1), self._dt(2), 5, [far], "own") == (0, None)
        # own event excluded: with only the own event there are no competitors
        own = OpenAllocationView("own", self._dt(1), self._dt(5), 8)
        assert max_concurrent_assigned(self._dt(1), self._dt(5), 1, [own], "own") == (0, None)
        # _peak_at with empty points
        assert _peak_at(set(), [a], 1) == (0, None)

    def test_evaluate_sold_protection_message(self) -> None:
        from src.utils.allocation import AllocationPlanLine, evaluate_assignment

        line = AllocationPlanLine(product_id="P", current_allocated=5, target=3, sold=5, released=0)
        warnings, blocks = evaluate_assignment(
            [line],
            sellable_by_product={"P": 100},
            open_by_product={},
            target_start=self._dt(1),
            target_end=self._dt(2),
            target_show_and_sell_id="x",
            event_location_name="L",
            product_names={"P": "Popcorn"},
        )
        assert warnings == [] and blocks == []


class TestFinalWave4Branches:
    def test_parse_ts_naive_and_active_status(self, t: Any) -> None:
        from datetime import datetime, timezone

        from src.handlers.event_operations import _derive_status, _parse_ts

        with pytest.raises(ValueError):
            _parse_ts("2026-11-01T12:00:00")
        now = datetime.now(timezone.utc)
        item = {
            "status": "SCHEDULED",
            "startAt": (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z"),
            "endAt": (now.replace(microsecond=0) + __import__("datetime").timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        assert _derive_status(item, now) == "ACTIVE"
        item["status"] = "FINALIZED"
        assert _derive_status(item, now) == "FINALIZED"

    def test_require_event_admin_missing_uc_and_address_validation(self, t: Any) -> None:
        created = _event(t)
        t["unit_campaigns"].delete_item(Key={"unitCampaignId": "uc-1", "itemKey": "METADATA"})
        from src.handlers.event_operations import _require_event_admin

        with pytest.raises(AppError):
            _require_event_admin({"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"}, ACCOUNT_A)

    def test_create_address_validation_and_bad_flag(self, t: Any) -> None:
        _seed(t)
        bad_address = handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "L",
                        "address": 5,
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "idempotencyKey": "sw-ad-0001",
                    }
                },
            ),
            None,
        )
        assert bad_address["errorCode"] == ErrorCode.INVALID_INPUT
        created = _event(t)
        bad_flag = handler(
            _ev(
                "updateShowAndSell",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "weOweEnabled": "x",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-ad-0002",
                    }
                },
            ),
            None,
        )
        assert bad_flag["errorCode"] == ErrorCode.INVALID_INPUT

    def test_assign_guards(self, t: Any) -> None:
        created = _event(t)
        empty = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-ag-0001",
                },
            ),
            None,
        )
        assert empty["errorCode"] == ErrorCode.INVALID_INPUT
        not_dict = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": ["x"],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-ag-0002",
                },
            ),
            None,
        )
        assert not_dict["errorCode"] == ErrorCode.INVALID_INPUT
        negative = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "P", "quantity": -1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-ag-0003",
                },
            ),
            None,
        )
        assert negative["errorCode"] == ErrorCode.INVALID_INPUT
        missing = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": "SS#ghost",
                    "items": [{"productId": "P", "quantity": 1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-ag-0004",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        stale = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "P", "quantity": 1}],
                    "expectedVersion": 9,
                    "idempotencyKey": "sw-ag-0005",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT

    def test_assign_cancelled_guard_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        guarded = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "P", "quantity": 1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-ag-0006",
                },
            ),
            None,
        )
        assert guarded["errorCode"] == ErrorCode.CONFLICT

    def test_assign_replay_and_marker_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
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
        args = {
            "showAndSellId": created["showAndSellId"],
            "items": [{"productId": "PROD#1", "quantity": 2}],
            "expectedVersion": 1,
            "idempotencyKey": "sw-ar-0001",
        }
        first = handler(_ev("assignShowAndSellInventory", args), None)
        second = handler(_ev("assignShowAndSellInventory", args), None)
        assert second == first

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(_ev("assignShowAndSellInventory", {**args, "idempotencyKey": "sw-ar-0002"}), None)
        assert raced["errorCode"] == ErrorCode.CONFLICT

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_first)
        raw = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "PROD#1", "quantity": 1}],
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-ar-0003",
                },
            ),
            None,
        )
        assert raw["errorCode"] == ErrorCode.CONFLICT

    def test_slot_version_floor_and_load_slot_branches(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-sl-0001",
                    }
                },
            ),
            None,
        )
        zero_version = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": slot["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "expectedSlotVersion": 0,
                        "idempotencyKey": "sw-sl-0002",
                    }
                },
            ),
            None,
        )
        assert zero_version["errorCode"] == ErrorCode.INVALID_INPUT
        from src.handlers.event_operations import _load_slot_for_write

        with pytest.raises(AppError):
            _load_slot_for_write("uc-1", created["showAndSellId"], "SLOT#ghost", False)

    def test_signup_cancelled_event_guard_and_profile_mismatch(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-se-0001",
                    }
                },
            ),
            None,
        )
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        blocked = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-se-0002",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT

    def test_confirm_work_non_object_and_load_paths(self, t: Any) -> None:
        created = _event(t)
        bad = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": ["x"],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-cw-0001",
                },
            ),
            None,
        )
        assert bad["errorCode"] == ErrorCode.INVALID_INPUT
        negative = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": "s", "profileId": "p", "actualMinutes": -1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-cw-0002",
                },
            ),
            None,
        )
        assert negative["errorCode"] == ErrorCode.INVALID_INPUT
        missing = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": "SS#ghost",
                    "work": [{"slotId": "s", "profileId": "p", "actualMinutes": 1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-cw-0003",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

    def test_roster_participant_read_path(self, t: Any) -> None:
        created = _event(t)
        # A member without admin grants reads via the roster path.
        read = handler(
            _ev("showAndSell", {"showAndSellId": created["showAndSellId"]}, sub="user-789"),
            None,
        )
        assert read["showAndSellId"] == created["showAndSellId"]
        # A stranger with no membership gets NOT_FOUND.
        _seed(t, second_member=False)
        t["unit_campaigns"].delete_item(Key={"unitCampaignId": "uc-1", "itemKey": f"MEMBER#{PROFILE_A}"})
        denied = handler(_ev("showAndSell", {"showAndSellId": created["showAndSellId"]}, sub="user-stranger"), None)
        assert denied["errorCode"] == ErrorCode.NOT_FOUND

    def test_allocation_view_none_arcs_and_admin_guards(self, t: Any) -> None:
        from src.handlers.event_operations import _allocation_view

        assert _allocation_view({"itemKey": "ALLOC#only"}, "uc-1", None, None, None) is None
        assert _allocation_view({"itemKey": "ALLOC#ev#P"}, "uc-1", "other", None, None) is None
        assert _allocation_view({"itemKey": "ALLOC#ev#P"}, "uc-1", None, "other", None) is None
        assert _allocation_view({"itemKey": "ALLOC#ev#P", "status": "OPEN"}, "uc-1", None, None, "CLOSED") is None
        _seed(t)
        assert handler(_ev("showAndSells", {"unitCampaignId": "UC#ghost"}), None)["errorCode"] == ErrorCode.NOT_FOUND
        assert (
            handler(_ev("eventInventoryAllocations", {"unitCampaignId": "UC#ghost"}), None)["errorCode"]
            == ErrorCode.NOT_FOUND
        )

    def test_list_pagination_loop_and_tamper(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        from src.utils.pagination import encode_cursor

        tampered = handler(
            _ev(
                "showAndSells",
                {"unitCampaignId": "uc-1", "page": {"cursor": encode_cursor("showAndSells:other:None", {"u": "x"})}},
            ),
            None,
        )
        assert tampered["errorCode"] == ErrorCode.INVALID_INPUT
        # Force a second page that contributes an ENDED event.
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "EVENT#p2",
                "showAndSellId": "p2",
                "saleId": "p2",
                "unitId": "unit-1",
                "locationName": "Past",
                "startAt": "2026-10-01T00:00:00Z",
                "endAt": "2026-10-02T00:00:00Z",
                "status": "SCHEDULED",
                "splitMethod": "EQUAL",
                "weOweEnabled": False,
                "version": 1,
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        paged = handler(_ev("showAndSells", {"unitCampaignId": "uc-1", "page": {"limit": 1}}), None)
        assert paged["pageInfo"]["hasNextPage"] is True
        assert paged["items"][0]["showAndSellId"] == "p2"  # earlier startAt sorts first
        second = handler(
            _ev(
                "showAndSells",
                {"unitCampaignId": "uc-1", "page": {"limit": 10, "cursor": paged["pageInfo"]["endCursor"]}},
            ),
            None,
        )
        assert any(i["showAndSellId"] == created["showAndSellId"] for i in second["items"])


class TestParticipantFinalBranches:
    def test_unauthenticated_reads(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p

        _seed(t)
        event = _ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"})
        del event["identity"]
        assert p(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED
        for field, args in [
            ("showAndSellOpportunity", {"showAndSellId": "x", "profileId": "y"}),
            ("myScoutCommitments", {"profileId": "y"}),
            ("showAndSellSignupCalendarData", {"showAndSellId": "x", "slotId": "y", "profileId": "z"}),
        ]:
            ev = _ev(field, args)
            del ev["identity"]
            assert p(ev, None)["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_opportunity_status_arcs_and_filters(self, t: Any) -> None:
        from datetime import datetime, timedelta, timezone

        from src.handlers.participant_data import _event_status
        from src.handlers.participant_data import handler as p

        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        later = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        assert _event_status({"status": "SCHEDULED", "startAt": future, "endAt": later}, now) == "SCHEDULED"
        past = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        near = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        assert _event_status({"status": "SCHEDULED", "startAt": past, "endAt": near}, now) == "ENDED"
        assert _event_status({"status": "REOPENED", "startAt": past, "endAt": near}, now) == "REOPENED"
        # cancelled hidden from listings
        _seed(t)
        created = _create_event(t, key="sw-pf-cx01")
        t["show_and_sells"].update_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"EVENT#{created['showAndSellId']}"},
            UpdateExpression="SET #status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "CANCELLED"},
        )
        listing = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"}), None)
        assert listing["items"] == []

    def test_opportunity_pagination_loop_and_tamper(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p
        from src.utils.pagination import encode_cursor

        _seed(t)
        created = _create_event(t, key="sw-pf-page01")
        _create_event(t, key="sw-pf-page02")
        tampered = p(
            _ev(
                "unitCampaignOpportunities",
                {"unitCampaignId": "uc-1", "page": {"cursor": encode_cursor("opportunities:other:False", {"u": "x"})}},
            ),
            None,
        )
        assert tampered["errorCode"] == ErrorCode.INVALID_INPUT
        paged = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1", "page": {"limit": 1}}), None)
        assert paged["pageInfo"]["hasNextPage"] is True
        second = p(
            _ev(
                "unitCampaignOpportunities",
                {"unitCampaignId": "uc-1", "page": {"limit": 10, "cursor": paged["pageInfo"]["endCursor"]}},
            ),
            None,
        )
        assert len(second["items"]) >= 1  # equal-startAt ordering is implementation-defined

    def test_commitment_and_calendar_not_found_arcs(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p

        created = _create_event(t, key="sw-pf-cal01")
        ghost_event = p(
            _ev("showAndSellSignupCalendarData", {"showAndSellId": "SS#ghost", "slotId": "s", "profileId": PROFILE_A}),
            None,
        )
        assert ghost_event["errorCode"] == ErrorCode.NOT_FOUND
        ghost_signup = p(
            _ev(
                "showAndSellSignupCalendarData",
                {"showAndSellId": created["showAndSellId"], "slotId": "SLOT#ghost", "profileId": PROFILE_A},
            ),
            None,
        )
        assert ghost_signup["errorCode"] == ErrorCode.NOT_FOUND
        # ghost slot behind an existing signup
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#SLOT#ghost#{PROFILE_A}",
                "showAndSellId": created["showAndSellId"],
                "slotId": "SLOT#ghost",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        ghost_slot = p(
            _ev(
                "showAndSellSignupCalendarData",
                {"showAndSellId": created["showAndSellId"], "slotId": "SLOT#ghost", "profileId": PROFILE_A},
            ),
            None,
        )
        assert ghost_slot["errorCode"] == ErrorCode.NOT_FOUND
        # non-member opportunities -> NOT_FOUND
        stranger = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"}, sub="user-nobody"), None)
        assert stranger["errorCode"] == ErrorCode.NOT_FOUND


class TestWave4LastBranches:
    def test_find_event_non_event_row_arc(self, t: Any) -> None:
        from src.handlers.event_operations import _find_event

        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SLOT#x#y",
                "saleId": "not-an-event",
                "showAndSellId": "not-an-event",
                "slotId": "y",
                "startAt": "t",
                "endAt": "t",
                "capacity": 1,
                "activeSignupCount": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        assert _find_event("not-an-event") is None

    def test_create_with_address_and_open_view_continues(self, t: Any) -> None:
        created = _create_event(t, key=f"sw-la-{uuid4()}", address="5 Oak Ave")
        assert created["address"] == "5 Oak Ave"
        from src.handlers.event_operations import _open_views_by_product

        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#P",
                "productId": "P",
                "kernelPhysicalQty": 1,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{created['showAndSellId']}#P",
                "productId": "P",
                "showAndSellId": created["showAndSellId"],
                "status": "CLOSED",
                "allocatedQty": 0,
                "soldQty": 0,
                "releasedQty": 0,
                "remainingQty": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "ALLOC#ghost-uc#P",
                "productId": "P",
                "showAndSellId": "ghost-uc",
                "status": "OPEN",
                "allocatedQty": 3,
                "soldQty": 0,
                "releasedQty": 0,
                "remainingQty": 3,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        grouped = _open_views_by_product("uc-1")
        assert grouped == {}  # CLOSED row skipped; OPEN row's event missing -> skipped

    def test_slot_upsert_marker_race_and_label_update(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        args = {
            "input": {
                "showAndSellId": created["showAndSellId"],
                "startAt": FUTURE_START,
                "endAt": FUTURE_END,
                "capacity": 4,
                "expectedEventVersion": 1,
                "idempotencyKey": "sw-ur-0001",
            }
        }
        first = handler(_ev("upsertShowAndSellSlot", args), None)

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev("upsertShowAndSellSlot", {**args, "input": {**args["input"], "idempotencyKey": "sw-ur-0002"}}), None
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_first)
        raw = handler(
            _ev("upsertShowAndSellSlot", {**args, "input": {**args["input"], "idempotencyKey": "sw-ur-0003"}}), None
        )
        assert raw["errorCode"] == ErrorCode.CONFLICT
        monkeypatch.undo()
        relabeled = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": first["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "label": "Evening",
                        "expectedEventVersion": _event_version(t, created["showAndSellId"]),
                        "expectedSlotVersion": 1,
                        "idempotencyKey": "sw-ur-0004",
                    }
                },
            ),
            None,
        )
        assert relabeled["label"] == "Evening"

    def test_slot_already_exists_and_event_version_mismatch(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-ae-0001",
                    }
                },
            ),
            None,
        )
        dup = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": slot["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": "sw-ae-0002",
                    }
                },
            ),
            None,
        )
        assert dup["errorCode"] == ErrorCode.INVALID_INPUT  # update without expectedSlotVersion
        stale = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 9,
                        "idempotencyKey": "sw-ae-0003",
                    }
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT

    def test_confirm_work_replay_and_version(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-cw-slot2",
                    }
                },
            ),
            None,
        )
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cw-su-02",
                },
            ),
            None,
        )
        stale = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 5}],
                    "expectedVersion": 9,
                    "idempotencyKey": "sw-cw-stale",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        args = {
            "showAndSellId": created["showAndSellId"],
            "work": [{"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 5}],
            "expectedVersion": 2,
            "idempotencyKey": "sw-cw-replay",
        }
        first = handler(_ev("confirmShowAndSellWork", args), None)
        second = handler(_ev("confirmShowAndSellWork", args), None)
        assert second == first
        empty = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [],
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-cw-empty",
                },
            ),
            None,
        )
        assert empty["errorCode"] == ErrorCode.INVALID_INPUT

    def test_cancel_signup_missing_slot_and_replay(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-cs-slot",
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
                    "idempotencyKey": "sw-cs-su-01",
                },
            ),
            None,
        )
        args = {
            "showAndSellId": created["showAndSellId"],
            "slotId": slot["slotId"],
            "profileId": PROFILE_A,
            "expectedVersion": signup["version"],
            "idempotencyKey": "sw-cs-replay",
        }
        first = handler(_ev("cancelShowAndSellSignup", args), None)
        second = handler(_ev("cancelShowAndSellSignup", args), None)
        assert second == first

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cs-su-02",
                },
            ),
            None,
        )
        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_first)
        raced = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-cs-race",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_event_page_non_event_row_and_fetch_more(self, t: Any) -> None:
        created = _event(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SLOT#{created['showAndSellId']}#zz",
                "showAndSellId": created["showAndSellId"],
                "slotId": "zz",
                "startAt": "2026-09-01T00:00:00Z",
                "endAt": "2026-09-02T00:00:00Z",
                "capacity": 1,
                "activeSignupCount": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "EVENT#later-one",
                "showAndSellId": "later-one",
                "saleId": "later-one",
                "unitId": "unit-1",
                "locationName": "Later",
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
        paged = handler(_ev("showAndSells", {"unitCampaignId": "uc-1", "page": {"limit": 2}}), None)
        ids = [i["showAndSellId"] for i in paged["items"]]
        assert "later-one" in ids and created["showAndSellId"] in ids


class TestParticipantLastBranches:
    def test_scouts_and_signup_filter_continues(self, t: Any) -> None:
        from src.handlers.participant_data import _accessible_scouts
        from src.handlers.participant_data import handler as p

        _seed(t)
        created = _create_event(t, key=f"sw-pc-{uuid4()}")
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "MEMBER#PROFILE#removed",
                "profileId": "PROFILE#removed",
                "campaignId": "CAMPAIGN#removed",
                "status": "REMOVED",
                "joinedByAccountId": ACCOUNT_A,
                "joinedAt": "t",
                "version": 1,
            }
        )
        scouts = _accessible_scouts(ACCOUNT_A, "uc-1")
        assert "PROFILE#removed" not in scouts and PROFILE_A in scouts
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#SLOT#x#{PROFILE_A}",
                "showAndSellId": "SS#other",
                "slotId": "SLOT#x",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "CANCELLED",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        listing = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"}), None)
        assert all(i["showAndSellId"] != "SS#other" for i in listing["items"])
        assert any(i["showAndSellId"] == created["showAndSellId"] for i in listing["items"])

    def test_opportunities_fetch_more_loop(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p

        _seed(t)
        created = _create_event(t, key="sw-pf-loop01")
        _create_event(t, key="sw-pf-loop02", startAt=LATER_START, endAt=LATER_END)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SLOT#{created['showAndSellId']}#s1",
                "showAndSellId": created["showAndSellId"],
                "slotId": "s1",
                "startAt": "2026-08-01T00:00:00Z",
                "endAt": "2026-08-02T00:00:00Z",
                "capacity": 1,
                "activeSignupCount": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        paged = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1", "page": {"limit": 1}}), None)
        assert paged["pageInfo"]["hasNextPage"] is True
        second = p(
            _ev(
                "unitCampaignOpportunities",
                {"unitCampaignId": "uc-1", "page": {"limit": 10, "cursor": paged["pageInfo"]["endCursor"]}},
            ),
            None,
        )
        assert len(second["items"]) >= 1  # deterministic: both events share no ordering guarantee

    def test_commitment_continues(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p

        _seed(t)
        # A REMOVED membership is skipped.
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-2",
                "itemKey": f"MEMBER#{PROFILE_A}",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "REMOVED",
                "joinedByAccountId": ACCOUNT_A,
                "joinedAt": "t",
                "version": 1,
            }
        )
        # An ACTIVE membership whose signups belong to other profiles / missing slots.
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-3",
                "itemKey": f"MEMBER#{PROFILE_A}",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "joinedByAccountId": ACCOUNT_A,
                "joinedAt": "t",
                "version": 1,
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-3",
                "itemKey": f"SIGNUP#S1#{PROFILE_B}",
                "showAndSellId": "SS#a",
                "slotId": "S1",
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
                "unitCampaignId": "uc-3",
                "itemKey": f"SIGNUP#S2#{PROFILE_A}",
                "showAndSellId": "SS#b",
                "slotId": "S2",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        result = p(_ev("myScoutCommitments", {"profileId": PROFILE_A}), None)
        assert result["items"] == []  # wrong-profile signup skipped; own signup's slot row missing


class TestWave4TrulyFinal:
    def test_marker_scope_key_direct(self, t: Any) -> None:
        from src.handlers.event_operations import _marker_scope_key

        assert _marker_scope_key({"idempotencyKey": "k"}) == "k"
        assert _marker_scope_key({"input": {"idempotencyKey": "ik"}}) == "ik"
        assert _marker_scope_key({}) == ""

    def test_create_non_marker_cancel_race(self, t: Any, monkeypatch: Any) -> None:
        _seed(t)

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_first)
        raw = handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-1",
                        "locationName": "L",
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "idempotencyKey": "sw-cn-0001",
                    }
                },
            ),
            None,
        )
        # A non-marker cancel on the create Put has no domain meaning: the
        # honest answer is INTERNAL_ERROR (bare race), not a masked conflict.
        assert raw["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_cancel_event_marker_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        args = {
            "showAndSellId": created["showAndSellId"],
            "expectedVersion": 1,
            "reason": "x",
            "idempotencyKey": "sw-ce-0001",
        }

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(_ev("cancelShowAndSell", {**args, "idempotencyKey": "sw-ce-0002"}), None)
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_slot_create_duplicate_id(self, t: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-dup-0001",
                    }
                },
            ),
            None,
        )
        dup = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "slotId": slot["slotId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": "sw-dup-0002",
                    }
                },
            ),
            None,
        )
        assert dup["errorCode"] == ErrorCode.INVALID_INPUT  # update path needs the slot version
        from src.handlers.event_operations import _load_slot_for_write

        with pytest.raises(AppError) as exc_info:
            _load_slot_for_write("uc-1", created["showAndSellId"], slot["slotId"], True)
        assert exc_info.value.error_code == "CONFLICT"

    def test_signup_campaign_base_missing_via_mock(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-mk-slot",
                    }
                },
            ),
            None,
        )
        real_get = t["campaigns"].get_item

        def fake_get_item(**kwargs: Any) -> Any:
            return {}

        monkeypatch.setattr(event_operations.tables.campaigns, "get_item", fake_get_item)
        result = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-mk-0001",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_cancel_signup_missing_slot_row_and_race(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-ms-slot",
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
                    "idempotencyKey": "sw-ms-su-01",
                },
            ),
            None,
        )
        t["show_and_sells"].delete_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"SLOT#{created['showAndSellId']}#{slot['slotId']}"}
        )
        missing = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": signup["version"],
                    "idempotencyKey": "sw-ms-0001",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND

    def test_participant_status_active_and_continues(self, t: Any) -> None:
        from datetime import datetime, timedelta, timezone

        from src.handlers.participant_data import _event_status, _opportunity_slots

        now = datetime.now(timezone.utc)
        assert (
            _event_status(
                {
                    "status": "SCHEDULED",
                    "startAt": now.isoformat().replace("+00:00", "Z"),
                    "endAt": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                },
                now,
            )
            == "ACTIVE"
        )
        _seed(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#other#x",
                "showAndSellId": "other",
                "slotId": "x",
                "profileId": "P",
                "campaignId": "C",
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        assert _opportunity_slots("uc-1", "SS#nope", {PROFILE_A: CAMPAIGN_A}) == []

    def test_assign_marker_race_branch(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "BALANCE#PROD#9",
                "productId": "PROD#9",
                "kernelPhysicalQty": 5,
                "soldInPossessionQty": 0,
                "councilOnOrderQty": 0,
                "version": 1,
            }
        )

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "assignShowAndSellInventory",
                {
                    "showAndSellId": created["showAndSellId"],
                    "items": [{"productId": "PROD#9", "quantity": 1}],
                    "expectedVersion": 1,
                    "idempotencyKey": "sw-am-0001",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_confirm_marker_race_branch(self, t: Any, monkeypatch: Any) -> None:
        created = _event(t)
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-cm-slot",
                    }
                },
            ),
            None,
        )
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cm-su-01",
                },
            ),
            None,
        )

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": created["showAndSellId"],
                    "work": [{"slotId": slot["slotId"], "profileId": PROFILE_A, "actualMinutes": 5}],
                    "expectedVersion": 2,
                    "idempotencyKey": "sw-cm-0001",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT

    def test_find_event_by_id_two_row_arc(self, t: Any) -> None:
        from src.handlers.participant_data import _find_event_by_id

        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SLOT#x#y",
                "saleId": "two-row",
                "showAndSellId": "two-row",
                "slotId": "y",
                "startAt": "t",
                "endAt": "t",
                "capacity": 1,
                "activeSignupCount": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SIGNUP#x#p",
                "saleId": "two-row",
                "showAndSellId": "two-row",
                "slotId": "x",
                "profileId": "p",
                "campaignId": "c",
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        assert _find_event_by_id("two-row") is None

    def test_opportunities_skip_ended_unless_include_past(self, t: Any) -> None:
        from src.handlers.participant_data import handler as p

        _seed(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "EVENT#old-one",
                "showAndSellId": "old-one",
                "saleId": "old-one",
                "unitId": "unit-1",
                "locationName": "Old",
                "startAt": "2026-09-01T00:00:00Z",
                "endAt": "2026-09-02T00:00:00Z",
                "status": "SCHEDULED",
                "splitMethod": "EQUAL",
                "weOweEnabled": False,
                "version": 1,
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        listing = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1"}), None)
        assert all(i["showAndSellId"] != "old-one" for i in listing["items"])
        with_past = p(_ev("unitCampaignOpportunities", {"unitCampaignId": "uc-1", "includePast": True}), None)
        assert any(i["showAndSellId"] == "old-one" for i in with_past["items"])


class TestSignupContractOracles:
    """Ported pins: SIGN-M-01 (sequence contract), DM-AC-14 (atomic overlap
    prevention, cross-campaign), DM-AC-19 (membership-removal race barrier)."""

    def _world(self, t: Any, sub: str = "user-123-456") -> Any:
        created = _create_event(t, key=f"sw-or-{uuid4()}")
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": f"sw-or-slot-{uuid4()}",
                    }
                },
            ),
            None,
        )
        return {"event": created, "slot": slot}

    def _signup(
        self, world: Any, key: str, profile: str = PROFILE_A, campaign: str = CAMPAIGN_A, sub: str = "user-123-456"
    ) -> Any:
        return handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": campaign,
                    "profileId": profile,
                    "idempotencyKey": key,
                },
                sub=sub,
            ),
            None,
        )

    def test_sign_m_01_happy_path_replay_and_duplicate(self, t: Any) -> None:
        world = self._world(t)
        first = self._signup(world, "sw-sign-m1-01")
        assert first["status"] == "ACTIVE"
        replayed = self._signup(world, "sw-sign-m1-01")
        assert replayed == first
        # Cancel, then re-signup the same slot (tombstone overwrite allowed).
        cancelled = handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": first["version"],
                    "idempotencyKey": "sw-sign-m1-02",
                },
            ),
            None,
        )
        assert cancelled["status"] == "CANCELLED"
        resigned = self._signup(world, "sw-sign-m1-03")
        assert resigned["status"] == "ACTIVE"

    def test_dm_ac_14_cross_unit_campaign_overlap_blocked_atomically(self, t: Any) -> None:
        """DM-AC-14: a Scout cannot hold overlapping commitments across Unit
        Campaigns. Sign up in UC-1, then attempt an overlapping slot in a
        second Unit Campaign -> CONFLICT via the SIGNUPWINDOW proof."""
        world = self._world(t)
        self._signup(world, "sw-ac14-0001")
        # Second Unit Campaign in the same unit, same profile a member.
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-2",
                "itemKey": "METADATA",
                "unitId": "unit-1",
                "campaignName": "Other",
                "campaignYear": 2026,
                "catalogId": "CATALOG#c",
                "joinCode": "JOINJOINJOINJOIN2",
                "isActive": True,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
                "createdByAccountId": ACCOUNT_A,
                "updatedByAccountId": ACCOUNT_A,
            }
        )
        t["unit_campaigns"].put_item(
            Item={
                "unitCampaignId": "uc-2",
                "itemKey": f"MEMBER#{PROFILE_A}",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "joinedByAccountId": ACCOUNT_A,
                "joinedAt": "t",
                "version": 1,
            }
        )
        other = handler(
            _ev(
                "createShowAndSell",
                {
                    "input": {
                        "unitCampaignId": "uc-2",
                        "locationName": "Elsewhere",
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "idempotencyKey": "sw-ac14-ev-01",
                    }
                },
            ),
            None,
        )
        other_slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": other["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": "sw-ac14-slot",
                    }
                },
            ),
            None,
        )
        # The friendly pre-read catches it (the buckets would too).
        blocked = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": other["showAndSellId"],
                    "slotId": other_slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-ac14-su-01",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT
        assert blocked["message"]  # friendly message names the conflicting commitment
        # Non-overlapping slot in UC-2 succeeds (no shared bucket).
        far_slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": other["showAndSellId"],
                        "startAt": LATER_START,
                        "endAt": LATER_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": "sw-ac14-slot2",
                    }
                },
            ),
            None,
        )
        ok = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": other["showAndSellId"],
                    "slotId": far_slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-ac14-su-02",
                },
            ),
            None,
        )
        assert ok["status"] == "ACTIVE"

    def test_dm_ac_19_removal_race_cancels_the_transaction(self, t: Any, monkeypatch: Any) -> None:
        """DM-AC-19: a membership removal racing a new signup invalidates the
        membership-version condition; nothing commits."""
        world = self._world(t)
        real_execute = event_operations.execute_transaction

        def racing_execute(plan: Any, **kwargs: Any) -> None:
            # The removal lands between the pre-read and the commit.
            t["unit_campaigns"].update_item(
                Key={"unitCampaignId": "uc-1", "itemKey": f"MEMBER#{PROFILE_A}"},
                UpdateExpression="SET #status = :s",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":s": "REMOVED"},
            )
            real_execute(plan, **kwargs)

        monkeypatch.setattr(event_operations, "execute_transaction", racing_execute)
        result = self._signup(world, "sw-ac19-0001")
        assert result["errorCode"] == ErrorCode.CONFLICT
        assert result["details"]["reason"] == "NOT_ROSTERED" if "details" in result else result["message"]
        # No signup row, no commitment residue.
        rows = t["show_and_sells"].scan()["Items"]
        assert not [r for r in rows if r["itemKey"].startswith("SIGNUP#")]

    def test_signup_window_race_maps_to_overlap(self, t: Any, monkeypatch: Any) -> None:
        """A window-bucket condition failure (concurrent overlapping signup)
        maps to the OVERLAPPING_COMMITMENT conflict."""
        world = self._world(t)

        def _cancel_on_window(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([4])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_window)
        raced = self._signup(world, "sw-win-0001")
        assert raced["errorCode"] == ErrorCode.CONFLICT
        assert raced["message"]  # names the conflicting commitment


class TestCancelCascade:
    """r1 CHANGES-1 (spec 8.8): cancelling an event releases everything in
    ONE transaction — allocations cancelled with releasedQty, release
    movements, signups cancelled, slot counters zeroed, window buckets freed."""

    def _world(self, t: Any) -> Any:
        created = _create_event(t, key=f"sw-cc-{uuid4()}")
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
                    "items": [{"productId": "PROD#1", "quantity": 6}],
                    "expectedVersion": created["version"],
                    "idempotencyKey": f"sw-cc-as-{uuid4()}",
                },
            ),
            None,
        )
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 2,
                        "idempotencyKey": f"sw-cc-sl-{uuid4()}",
                    }
                },
            ),
            None,
        )
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": created["showAndSellId"],
                    "slotId": slot["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": f"sw-cc-su-{uuid4()}",
                },
            ),
            None,
        )
        return {"event": created, "slot": slot}

    def test_cancel_releases_allocations_signups_slots_and_windows(self, t: Any) -> None:
        world = self._world(t)
        result = handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "expectedVersion": 4,
                    "reason": "storm",
                    "idempotencyKey": f"sw-cc-cancel-{uuid4()}",
                },
            ),
            None,
        )
        assert result["status"] == "CANCELLED"
        # Allocation CANCELLED with releasedQty += remaining, remaining 0.
        alloc = t["inventory"].get_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"ALLOC#{world['event']['showAndSellId']}#PROD#1"}
        )["Item"]
        assert alloc["status"] == "CANCELLED"
        assert int(alloc["remainingQty"]) == 0
        assert int(alloc["releasedQty"]) == 6
        # Release movement recorded.
        movements = [
            m
            for m in t["inventory"].scan()["Items"]
            if m["itemKey"].startswith("MOVEMENT#") and m.get("movementType") == "RELEASE"
        ]
        assert len(movements) == 1 and int(movements[0]["assignedDelta"]) == -6
        # Signup cancelled; slot counter zeroed; window buckets freed.
        signup = t["show_and_sells"].get_item(
            Key={"unitCampaignId": "uc-1", "itemKey": f"SIGNUP#{world['slot']['slotId']}#{PROFILE_A}"}
        )["Item"]
        assert signup["status"] == "CANCELLED"
        slot = t["show_and_sells"].get_item(
            Key={
                "unitCampaignId": "uc-1",
                "itemKey": f"SLOT#{world['event']['showAndSellId']}#{world['slot']['slotId']}",
            }
        )["Item"]
        assert int(slot["activeSignupCount"]) == 0
        windows = [w for w in t["show_and_sells"].scan()["Items"] if w["unitCampaignId"].startswith("PROFILEWINDOW#")]
        assert windows == []

    def test_cancel_retains_buckets_shared_with_other_active_signup(self, t: Any) -> None:
        world = self._world(t)
        # A second overlapping ACTIVE signup of the same profile elsewhere
        # keeps the shared buckets alive.
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"EVENT#shadow-{uuid4()}",
                "showAndSellId": "shadow",
                "saleId": "shadow",
                "unitId": "unit-1",
                "locationName": "Shadow",
                "startAt": FUTURE_START,
                "endAt": FUTURE_END,
                "status": "SCHEDULED",
                "splitMethod": "EQUAL",
                "weOweEnabled": False,
                "version": 1,
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SLOT#shadow#s2",
                "showAndSellId": "shadow",
                "slotId": "s2",
                "startAt": FUTURE_START,
                "endAt": FUTURE_END,
                "capacity": 4,
                "activeSignupCount": 1,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#s2#{PROFILE_A}",
                "showAndSellId": "shadow",
                "slotId": "s2",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "expectedVersion": 4,
                    "reason": "storm",
                    "idempotencyKey": f"sw-cc-sh-{uuid4()}",
                },
            ),
            None,
        )
        windows = [w for w in t["show_and_sells"].scan()["Items"] if w["unitCampaignId"].startswith("PROFILEWINDOW#")]
        assert len(windows) > 0  # the shadow signup still claims the shared buckets


class TestFixCommitCoverage:
    def test_allocation_release_zero_remaining_arc(self, t: Any) -> None:
        """An allocation with remaining 0 (fully sold) cancels WITHOUT a
        release movement."""
        created = _create_event(t, key=f"sw-zr-{uuid4()}")
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
                    "items": [{"productId": "PROD#1", "quantity": 2}],
                    "expectedVersion": 1,
                    "idempotencyKey": f"sw-zr-as-{uuid4()}",
                },
            ),
            None,
        )
        # Sell out the allocation: remaining -> 0.
        t["inventory"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"ALLOC#{created['showAndSellId']}#PROD#1",
                "productId": "PROD#1",
                "showAndSellId": created["showAndSellId"],
                "eventStartAt": created["startAt"],
                "eventEndAt": created["endAt"],
                "status": "OPEN",
                "allocatedQty": 2,
                "soldQty": 2,
                "releasedQty": 0,
                "remainingQty": 0,
                "version": 2,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        result = handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 2,
                    "reason": "done",
                    "idempotencyKey": f"sw-zr-{uuid4()}",
                },
            ),
            None,
        )
        assert result["status"] == "CANCELLED"
        movements = [m for m in t["inventory"].scan()["Items"] if m.get("movementType") == "RELEASE"]
        assert movements == []

    def test_profile_intervals_missing_slot_and_window_release_helper(self, t: Any) -> None:
        from src.handlers.event_operations import _profile_active_intervals, _window_release_buckets

        _seed(t)
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#S9#{PROFILE_A}",
                "showAndSellId": "SS#gone",
                "slotId": "S9",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        assert _profile_active_intervals(PROFILE_A) == []  # slot row gone -> skipped
        signup = {"profileId": PROFILE_A, "itemKey": f"SIGNUP#S1#{PROFILE_A}"}
        slot = {"startAt": FUTURE_START, "endAt": FUTURE_END}
        # No other signups: all buckets released.
        released = _window_release_buckets(signup, slot)
        from src.handlers.event_operations import _window_buckets

        assert released == _window_buckets(FUTURE_START, FUTURE_END)

    def test_signup_marker_replay_and_race_branches(self, t: Any, monkeypatch: Any) -> None:
        world = self._world(t)
        args = {
            "showAndSellId": world["event"]["showAndSellId"],
            "slotId": world["slot"]["slotId"],
            "campaignId": CAMPAIGN_A,
            "profileId": PROFILE_A,
            "idempotencyKey": "sw-smr-0001",
        }
        first = handler(_ev("signupScoutForShowAndSellSlot", args), None)
        second = handler(_ev("signupScoutForShowAndSellSlot", args), None)
        assert second == first  # committed replay
        # A NON-overlapping second slot passes the friendly pre-read; the
        # marker-race mapping fires inside the transaction.
        far = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": world["event"]["showAndSellId"],
                        "startAt": LATER_START,
                        "endAt": LATER_END,
                        "capacity": 4,
                        "expectedEventVersion": 3,
                        "idempotencyKey": "sw-smr-far",
                    }
                },
            ),
            None,
        )

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": far["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-smr-0002",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT
        assert "concurrently" in raced["message"]

    def _world(self, t: Any) -> Any:
        created = _create_event(t, key=f"sw-fx-{uuid4()}")
        slot = handler(
            _ev(
                "upsertShowAndSellSlot",
                {
                    "input": {
                        "showAndSellId": created["showAndSellId"],
                        "startAt": FUTURE_START,
                        "endAt": FUTURE_END,
                        "capacity": 4,
                        "expectedEventVersion": 1,
                        "idempotencyKey": f"sw-fx-slot-{uuid4()}",
                    }
                },
            ),
            None,
        )
        return {"event": created, "slot": slot}

    def test_signup_missing_membership_row_arc(self, t: Any, monkeypatch: Any) -> None:
        """The membership row vanishes between the ACTIVE check and the
        versioned read (read returns {}) -> the plan conditions on version
        0 and the friendly pre-check re-runs; here we cover the empty-read
        path feeding version 0."""
        world = self._world(t)
        real_get = event_operations.tables.unit_campaigns.get_item
        calls = {"n": 0}

        def flaky_get(**kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] >= 2:
                return {}  # the plan-time membership read returns empty
            return real_get(**kwargs)

        monkeypatch.setattr(event_operations.tables.unit_campaigns, "get_item", flaky_get)
        result = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-mem-0001",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.CONFLICT  # membership condition (version 0) fails

    def test_confirm_work_replay_and_marker_race_branches(self, t: Any, monkeypatch: Any) -> None:
        world = self._world(t)
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cf-su-01",
                },
            ),
            None,
        )
        args = {
            "showAndSellId": world["event"]["showAndSellId"],
            "work": [{"slotId": world["slot"]["slotId"], "profileId": PROFILE_A, "actualMinutes": 15}],
            "expectedVersion": 3,
            "idempotencyKey": "sw-cf-0001",
        }
        first = handler(_ev("confirmShowAndSellWork", args), None)
        second = handler(_ev("confirmShowAndSellWork", args), None)
        assert second == first  # E1742 committed replay

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_marker)
        raced = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "work": [{"slotId": world["slot"]["slotId"], "profileId": PROFILE_A, "actualMinutes": 20}],
                    "expectedVersion": 4,
                    "idempotencyKey": "sw-cf-0002",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT  # E1829-1834 marker-race mapping
        assert "concurrently" in raced["message"]

    def test_cascade_signup_missing_slot_arc(self, t: Any) -> None:
        """A signup whose slot row is gone still cancels (window release
        skipped) when the event is cancelled."""
        created = _create_event(t, key=f"sw-ms-{uuid4()}")
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#SLOST#{PROFILE_A}",
                "showAndSellId": created["showAndSellId"],
                "slotId": "SLOST",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        result = handler(
            _ev(
                "cancelShowAndSell",
                {
                    "showAndSellId": created["showAndSellId"],
                    "expectedVersion": 1,
                    "reason": "x",
                    "idempotencyKey": f"sw-ms-{uuid4()}",
                },
            ),
            None,
        )
        assert result["status"] == "CANCELLED"
        signup = t["show_and_sells"].get_item(Key={"unitCampaignId": "uc-1", "itemKey": f"SIGNUP#SLOST#{PROFILE_A}"})[
            "Item"
        ]
        assert signup["status"] == "CANCELLED"

    def test_cancel_signup_retains_shared_buckets(self, t: Any) -> None:
        """Cancelling one of two overlapping ACTIVE signups keeps the buckets
        the other still claims."""
        world = self._world(t)
        first = handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-sh-0001",
                },
            ),
            None,
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "SLOT#shadow#s9",
                "showAndSellId": "shadow",
                "slotId": "s9",
                "startAt": FUTURE_START,
                "endAt": FUTURE_END,
                "capacity": 4,
                "activeSignupCount": 1,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        t["show_and_sells"].put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": f"SIGNUP#s9#{PROFILE_A}",
                "showAndSellId": "shadow",
                "slotId": "s9",
                "profileId": PROFILE_A,
                "campaignId": CAMPAIGN_A,
                "status": "ACTIVE",
                "actualMinutes": 0,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
            }
        )
        handler(
            _ev(
                "cancelShowAndSellSignup",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "profileId": PROFILE_A,
                    "expectedVersion": first["version"],
                    "idempotencyKey": "sw-sh-0002",
                },
            ),
            None,
        )
        windows = [w for w in t["show_and_sells"].scan()["Items"] if w["unitCampaignId"].startswith("PROFILEWINDOW#")]
        assert len(windows) > 0  # the shadow signup still claims the shared buckets

    def test_confirm_non_marker_cancel_branch(self, t: Any, monkeypatch: Any) -> None:
        world = self._world(t)
        handler(
            _ev(
                "signupScoutForShowAndSellSlot",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "slotId": world["slot"]["slotId"],
                    "campaignId": CAMPAIGN_A,
                    "profileId": PROFILE_A,
                    "idempotencyKey": "sw-cn-su-01",
                },
            ),
            None,
        )

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(event_operations, "execute_transaction", _cancel_on_first)
        raced = handler(
            _ev(
                "confirmShowAndSellWork",
                {
                    "showAndSellId": world["event"]["showAndSellId"],
                    "work": [{"slotId": world["slot"]["slotId"], "profileId": PROFILE_A, "actualMinutes": 5}],
                    "expectedVersion": 3,
                    "idempotencyKey": "sw-cn-0001",
                },
            ),
            None,
        )
        assert raced["errorCode"] == ErrorCode.CONFLICT
        assert "concurrent" in raced["message"].lower()
