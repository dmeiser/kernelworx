"""The WORK-168 lane's cleanup gates, tested without a live stack.

``tests/e2e/show_sell_stage3_lane.py`` mutates shared ``dev``, so its own verdicts are only as good as the
code that produces them.  These tests drive that module against a fake GraphQL transport and check the four
things its evidence depends on:

1. **Recovery is bounded to the lanes this run was authorized to write against.**  Every lane on this stack
   signs in as the same four fixture identities, and two lanes of this card can be in flight at once, so a
   recovery pass matched on the card-wide event prefix could cancel a place another run is holding — and a
   cancelled signup can never be re-created in its slot, so that write cannot be undone.
2. **A run that is refused or interrupted part-way through setup still tears down, still sweeps what it
   captured, and still writes its record.**
3. **The exit gate is the shared cleanup gate**: a ``failed`` row always costs the run, a ``blocked`` row
   costs it under ``SS_STRICT_CLEANUP=1`` (the one-step reversal Amendment C promises), and a canary whose
   removal was never affirmatively read back is a failure rather than a pass.
4. **A canary read that errors is never reported as removed.**
"""

from __future__ import annotations

import copy
import json
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from tests.e2e import show_sell_stage3_lane as lane
from tests.e2e.utils import show_sell_graphql as api
from tests.e2e.utils import show_sell_stage2_support as stage2

CURRENT = "w168lane-1225010101-aa11"
SIBLING = "w168lane-1225010102-bb22"
CANARY = "w168can-1225010101"
PRIOR = "w168lane-1225010000-cc33"
FIXTURE_PROFILE = "PROFILE#00"


def _operation(document: str) -> str:
    """The root field one support document calls — the name the fakes answer by.

    Document names are UpperCamel (``mutation Stage3LaneCreateUnit($input: …)``), so the first
    lowercase-initial name in the document is the field itself, and every support document names one.
    """
    if "__schema" in document:
        return "__schema"
    called = re.findall(r"\b([a-z][A-Za-z0-9]*)\(", document)
    if called:
        return called[0]
    blocks = [name for name in re.findall(r"\b([a-z][A-Za-z0-9]*)\s*\{", document) if name not in ("query", "mutation")]
    return blocks[0] if blocks else document.strip().split()[0]


class FakeApi:
    """``show_sell_graphql``'s two send functions, answered from a table keyed by root field."""

    def __init__(self, answers: Mapping[str, Any], refusals: Mapping[str, str] | None = None) -> None:
        self.answers = dict(answers)
        self.refusals = dict(refusals or {})
        self.calls: List[Dict[str, Any]] = []

    def _answer(self, operation: str, variables: Dict[str, Any]) -> Any:
        if operation in self.refusals:
            raise api.GraphQLError(self.refusals[operation], ["FORBIDDEN"], {"errors": [{"message": operation}]})
        assert operation in self.answers, f"no fake answer for {operation!r}"
        answer = self.answers[operation]
        return copy.deepcopy(answer(variables) if callable(answer) else answer)

    def _send(self, token: str, document: str, variables: Dict[str, Any] | None) -> Dict[str, Any]:
        operation = _operation(document)
        variables = dict(variables or {})
        self.calls.append({"token": token, "operation": operation, "variables": variables})
        return {operation: self._answer(operation, variables)}

    def gql(self, token: str, document: str, variables: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._send(token, document, variables)

    def gql_raw(self, token: str, document: str, variables: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._send(token, document, variables)

    def sent(self, operation: str) -> List[Dict[str, Any]]:
        return [call for call in self.calls if call["operation"] == operation]


def _profiles(count: int = 1) -> Dict[str, Any]:
    return {"profiles": [{"profileId": f"PROFILE#{index:02d}", "sellerName": f"S{index}"} for index in range(count)]}


def _commitment(event_id: str, slot_id: str, status: str = "ACTIVE") -> Dict[str, Any]:
    return {
        "showAndSellId": event_id,
        "slotId": slot_id,
        "profileId": FIXTURE_PROFILE,
        "status": status,
        "startAt": "2026-12-01T15:00:00+00:00",
        "endAt": "2026-12-10T16:30:00+00:00",
        "signupVersion": 3,
    }


def _event(event_id: str, lane_id: str, status: str = "SCHEDULED", slots: List[str] | None = None) -> Dict[str, Any]:
    return {
        "showAndSellId": event_id,
        "locationName": lane.event_location(lane_id),
        "status": status,
        "startAt": "2026-12-01T15:00:00+00:00",
        "endAt": "2026-12-01T19:00:00+00:00",
        "version": 2,
        "slots": [{"slotId": slot, "label": "Shift"} for slot in slots or []],
    }


def _board(status: str = "CANCELLED") -> Dict[str, Any]:
    return {"items": [{"slotId": "SLOT-1", "version": 2, "profileId": FIXTURE_PROFILE, "status": status}]}


def _signup_board() -> tuple[
    Callable[[Mapping[str, Any]], Dict[str, Any]], Callable[[Mapping[str, Any]], Dict[str, Any]]
]:
    """A signup board whose row is ``ACTIVE`` until the cancellation lands.

    The lane reads the row once for its version and again for the read-back, so a static answer would either
    hide the removal or hide the refusal: the row has to move when the write moves.
    """
    state = {"status": "ACTIVE"}

    def board(_variables: Mapping[str, Any]) -> Dict[str, Any]:
        return {"items": [{"slotId": "SLOT-1", "version": 2, "profileId": FIXTURE_PROFILE, "status": state["status"]}]}

    def cancel(variables: Mapping[str, Any]) -> Dict[str, Any]:
        state["status"] = "CANCELLED"
        return {"showAndSellId": variables["input"]["showAndSellId"], "slotId": "SLOT-1", "status": "CANCELLED"}

    return board, cancel


# ---------------------------------------------------------------------------
# 1. recovery is bounded to the lanes this run was told about
# ---------------------------------------------------------------------------


def test_two_lanes_of_this_card_on_one_scout_and_only_the_authorized_one_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card-wide prefix names both lanes; the exact-location gate must still cancel only one.

    This is the collision the review named: two WORK-168 lanes against the same fixture Scout.  The sibling's
    event is unmistakably this card's — same prefix, same naming template — and cancelling it would take away
    a place that cannot be given back.
    """
    commitments = [
        _commitment("EV-CURRENT", "SLOT-1"),
        _commitment("EV-SIBLING", "SLOT-1"),
        _commitment("EV-OUTSIDER", "SLOT-1"),
    ]
    events = {
        "EV-CURRENT": _event("EV-CURRENT", CURRENT, slots=["SLOT-1"]),
        "EV-SIBLING": _event("EV-SIBLING", SIBLING, slots=["SLOT-1"]),
        "EV-OUTSIDER": {
            "showAndSellId": "EV-OUTSIDER",
            "locationName": "Riley's community night",
            "status": "SCHEDULED",
            "version": 1,
            "slots": [{"slotId": "SLOT-1"}],
        },
    }

    def cancel(variables: Mapping[str, Any]) -> Dict[str, Any]:
        for row in commitments:
            if row["showAndSellId"] == variables["input"]["showAndSellId"]:
                row["status"] = "CANCELLED"
        return {"showAndSellId": variables["input"]["showAndSellId"], "status": "CANCELLED"}

    fake = FakeApi(
        {
            "listMyProfiles": _profiles(),
            "myScoutCommitments": lambda variables: {"items": list(commitments)},
            "showAndSell": lambda variables: events[str(variables["showAndSellId"])],
            "showAndSellSignups": _board(),
            "cancelShowAndSellSignup": cancel,
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    cleanup, steps, still_active = lane.recover_standing_commitments("tok-admin", "tok-scout", CURRENT)

    cancelled = [call["variables"]["input"]["showAndSellId"] for call in fake.sent("cancelShowAndSellSignup")]
    assert cancelled == ["EV-CURRENT"], "recovery wrote against an event this run was not authorized to cancel"
    assert steps == ["recover-commitment-1"]
    text = "\n".join(row["summary"] for row in cleanup)
    assert f"lane {CURRENT}'s event EV-CURRENT" in text
    assert f"lane {SIBLING}'s" not in text, "the sibling lane was named as a write, not as a row left standing"
    assert "EV-SIBLING" in text and "authorized to write against" in text
    assert "EV-OUTSIDER" in text
    assert len(still_active) == 2, "the sibling's and the outsider's places are still standing, and reported"
    assert not lane.stage3.cleanup_blocked(cleanup)


def test_the_canary_is_protected_from_recovery_even_when_its_lane_id_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canary is this run's lane and still must not be written against.

    Its rows are the proof the sweep left an independent lane alone, so a recovery pass that cancelled a
    canary place would destroy the evidence the record exists to report.
    """
    commitments = [_commitment("EV-CANARY", "SLOT-1")]
    fake = FakeApi(
        {
            "listMyProfiles": _profiles(),
            "myScoutCommitments": lambda variables: {"items": list(commitments)},
            "showAndSell": lambda variables: _event("EV-CANARY", CANARY, slots=["SLOT-1"]),
            "showAndSellSignups": _board(),
            "cancelShowAndSellSignup": {"status": "CANCELLED"},
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    cleanup, steps, _still = lane.recover_standing_commitments("tok-admin", "tok-scout", CURRENT, [CANARY], [CANARY])

    assert fake.sent("cancelShowAndSellSignup") == []
    assert steps == []
    assert any("EV-CANARY" in row["summary"] for row in cleanup)


def test_cancellable_locations_are_exact_per_lane_id_and_drop_the_protected_ones() -> None:
    """The gate is a set of exact locations, so no prefix or substring can widen it."""
    locations = lane.cancellable_locations(CURRENT, [PRIOR, SIBLING], [CANARY])
    assert locations == {
        lane.event_location(CURRENT): CURRENT,
        lane.event_location(PRIOR): PRIOR,
        lane.event_location(SIBLING): SIBLING,
    }
    assert lane.event_location(CANARY) not in locations
    assert "Stage 3 lane w168lane-1225010000-dd44" not in locations
    assert lane.cancellable_locations(CURRENT, [], []) == {lane.event_location(CURRENT): CURRENT}


def test_a_prior_lane_sweep_refuses_an_event_that_is_not_that_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Unit Campaign can hold a foreign event; naming the lane id does not authorize writes on it."""
    state: Dict[str, Dict[str, Any]] = {
        "EV-PRIOR": _event("EV-PRIOR", PRIOR, slots=["SLOT-1"]),
        "EV-FOREIGN": {
            "showAndSellId": "EV-FOREIGN",
            "locationName": "Someone else's booth",
            "status": "SCHEDULED",
            "version": 1,
            "slots": [{"slotId": "SLOT-9"}],
        },
        "EV-STARTED": _event("EV-STARTED", PRIOR, status="ACTIVE", slots=["SLOT-2"]),
    }

    def delete_slot(variables: Mapping[str, Any]) -> Dict[str, Any]:
        event = state[str(variables["input"]["showAndSellId"])]
        event["slots"] = [slot for slot in event["slots"] if slot["slotId"] != variables["input"]["slotId"]]
        return {"showAndSellId": event["showAndSellId"]}

    board, cancel = _signup_board()
    fake = FakeApi(
        {
            "listMyProfiles": _profiles(),
            "showAndSells": {"items": [dict(row) for row in state.values()]},
            "showAndSell": lambda variables: state[str(variables["showAndSellId"])],
            "showAndSellSignups": board,
            "cancelShowAndSellSignup": cancel,
            "deleteShowAndSellSlot": delete_slot,
            "cancelShowAndSell": {"status": "CANCELLED", "cancellationReason": "cleanup"},
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    cleanup, steps = lane._recover_standing_events("tok-admin", "tok-scout", PRIOR, ["UC-PRIOR"])

    assert {call["variables"]["input"]["showAndSellId"] for call in fake.sent("deleteShowAndSellSlot")} == {"EV-PRIOR"}
    assert {call["variables"]["input"]["showAndSellId"] for call in fake.sent("cancelShowAndSell")} == {"EV-PRIOR"}
    assert steps == ["cancel-signup-SLOT-1"], "the prior lane's own signup was not given back"
    text = "\n".join(row["summary"] for row in cleanup)
    assert "EV-FOREIGN" in text and "not lane" in text
    assert "EV-STARTED" in text and "cancellation is legal only before" in text
    assert len(lane.stage3.cleanup_blocked(cleanup)) == 2, "both refusals are reported, never passed over"


def test_a_prior_lane_sweep_never_asks_for_another_lanes_unit_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``showAndSells`` is only ever asked for the Unit Campaigns the named lane owns."""
    fake = FakeApi({"listMyProfiles": _profiles(), "showAndSells": {"items": []}})
    monkeypatch.setattr(api, "gql", fake.gql)

    cleanup, steps = lane._recover_standing_events("tok-admin", "tok-scout", PRIOR, ["UC-PRIOR"])

    assert [call["variables"]["unitCampaignId"] for call in fake.sent("showAndSells")] == ["UC-PRIOR"]
    assert (steps, cleanup) == ([], [])


# ---------------------------------------------------------------------------
# 2. a half-finished run still owes its teardown, its sweep and its record
# ---------------------------------------------------------------------------


def _setup_answers() -> Dict[str, Any]:
    """The setup calls one lane makes, in the order ``build_lane`` sends them."""
    return {
        "createUnit": {"unit": {"unitId": "UNIT-1", "unitNumber": 1225010101}},
        "createUnitCampaign": {"unitCampaignId": "UC-1", "unitId": "UNIT-1"},
        "unitCampaigns": {"items": [{"unitCampaignId": "UC-1", "joinCode": "ABCDEFGH"}]},
        "createCampaign": {"campaignId": "SC-1", "profileId": FIXTURE_PROFILE},
        "joinUnitCampaign": {"unitCampaignId": "UC-1", "campaignId": "SC-1", "status": "ACTIVE"},
        "unitCampaignRoster": {
            "items": [
                {
                    "campaignId": "SC-1",
                    "profileId": FIXTURE_PROFILE,
                    "status": "ACTIVE",
                    "version": 1,
                    "guardVersion": 1,
                }
            ]
        },
        "listMyProfiles": _profiles(),
    }


@pytest.mark.parametrize(
    ("refused", "id_tokens", "markers"),
    [
        ("createUnitCampaign", ["unit=UNIT-1"], ["createUnit-unit"]),
        ("createCampaign", ["unit=UNIT-1", "unit-campaign=UC-1"], ["createUnit-unit", "createUnitCampaign-campaign"]),
        (
            "joinUnitCampaign",
            ["unit=UNIT-1", "unit-campaign=UC-1", "campaign=SC-1"],
            [
                "createUnit-unit",
                "createUnitCampaign-campaign",
                "joinUnitCampaign-join",
                "removeUnitCampaignMembership-remove-join",
            ],
        ),
    ],
    ids=["refused-at-unit-campaign", "refused-at-scout-campaign", "refused-at-join"],
)
def test_a_refusal_during_setup_still_sweeps_every_id_captured_before_it(
    monkeypatch: pytest.MonkeyPatch, refused: str, id_tokens: List[str], markers: List[str]
) -> None:
    """Each id is recorded the moment it is answered, and the sweep is gated on those ids.

    The old shape gated the sweep on ``unitCampaignId``, so a run refused at the join left its Unit, its Unit
    Campaign and both setup markers standing with nothing in the record naming them.
    """
    fake = FakeApi(_setup_answers(), refusals={refused: f"{refused} refused by the fake"})
    monkeypatch.setattr(api, "gql", fake.gql)

    swept: List[List[str]] = []
    torn_down: List[Dict[str, Any]] = []

    def record_sweep(tokens: Any, census: Any) -> Any:
        swept.append(list(tokens))
        row = lane.stage3.cleanup_row("§3.7.7 lane sweep", "fake sweep", stage2.CLEANUP_OBSERVED)
        return row, {"tokens": list(tokens)}

    def record_teardown(admin: str, scout: str, lane_rows: Mapping[str, Any], written: Mapping[str, Any]) -> List[Any]:
        torn_down.append(dict(lane_rows))
        return []

    monkeypatch.setattr(lane, "sweep_row", record_sweep)
    monkeypatch.setattr(lane, "teardown", record_teardown)
    monkeypatch.setattr(lane, "_safe_reads", lambda admin, unit_campaign_id: {})

    captured: Dict[str, Any] = {}
    with pytest.raises(api.GraphQLError):
        lane.build_lane("tok-admin", "tok-scout", lane.lane_names(CURRENT, unit_number=1), "CAT-1", captured)

    record: Dict[str, Any] = {"canary": {}, "residueCensus": {}}
    cleanup: List[Dict[str, str]] = []
    lane.run_cleanup_steps("tok-admin", "tok-scout", captured, {}, {}, {}, [], record, cleanup)

    assert torn_down and torn_down[0]["dataId"] == CURRENT, "a half-built lane skipped its teardown"
    assert swept == [id_tokens + [f"idem=stage3-{CURRENT}-{marker}" for marker in markers]]
    assert "wrote no Stage 3 row" in "\n".join(row["summary"] for row in cleanup)


def test_a_join_failure_still_runs_the_real_teardown_on_the_rows_that_do_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rows a half-built lane holds go through the shipped paths; the join it never wrote is reported.

    ``build_lane`` records the Scout Campaign the moment ``createCampaign`` answers it, so a join that is
    refused leaves a real Campaign row that only ``deleteCampaign`` can take back.  ``removeUnitCampaignMembership``
    is still called — a lane that holds a Campaign may hold a join — and answers as nothing to remove rather
    than failing, because the roster read says the row is not there.
    """
    fake = FakeApi(
        {
            **_setup_answers(),
            "unitCampaignRoster": {"items": []},
            "deleteCampaign": {"campaignId": "SC-1"},
            "getCampaign": None,
        },
        refusals={"joinUnitCampaign": "join refused by the fake"},
    )
    monkeypatch.setattr(api, "gql", fake.gql)
    monkeypatch.setattr(api, "gql_raw", fake.gql_raw)

    captured: Dict[str, Any] = {}
    with pytest.raises(api.GraphQLError):
        lane.build_lane("tok-admin", "tok-scout", lane.lane_names(CURRENT, unit_number=1), "CAT-1", captured)
    assert captured.get("scoutCampaignId") == "SC-1"

    fake.calls.clear()
    rows = lane.teardown("tok-admin", "tok-scout", captured, {})

    assert fake.sent("deleteCampaign"), "the half-built lane's Scout Campaign was never taken back"
    assert fake.sent("unitCampaignRoster")
    assert all(row["result"] != stage2.CLEANUP_FAILED for row in rows), rows
    text = "\n".join(row["summary"] for row in rows)
    assert "nothing to remove" in text
    assert len(rows) == 2, "only the join and the Campaign are this lane's to take back"


def test_an_interrupted_run_still_sweeps_and_still_writes_its_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The teardown, the sweeps and the record all sit in a ``finally``.

    ``KeyboardInterrupt`` is deliberate: it walks past ``except Exception``, which is exactly how a run loses
    its cleanup when cleanup is a statement after the ``try`` rather than a ``finally``.
    """
    swept: List[List[str]] = []
    built: List[str] = []

    def record_sweep(tokens: Any, census: Any) -> Any:
        swept.append(list(tokens))
        row = lane.stage3.cleanup_row("§3.7.7 lane sweep", "fake sweep", stage2.CLEANUP_OBSERVED)
        return row, {"tokens": list(tokens)}

    def build_canary_then_break(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        progress: Dict[str, Any] = args[4]
        if not built:
            built.append("canary")
            progress.update({"dataId": CANARY, "unitId": "UNIT-C", "unitCampaignId": "UC-C", "scoutCampaignId": "SC-C"})
            return dict(progress)
        built.append("lane")
        raise KeyboardInterrupt

    fake = FakeApi(
        {
            "__schema": {
                "queryType": {"fields": [{"name": name} for name in lane.stage3.STAGE_THREE_READS]},
                "mutationType": {"fields": [{"name": name} for name in lane.stage3.STAGE_THREE_WRITES]},
            },
            "listManagedCatalogs": [
                {
                    "catalogType": "ADMIN_MANAGED",
                    "catalogId": "CAT-1",
                    "products": [{"productId": "P-1", "productName": name} for name in lane.PREFERRED_PRODUCTS],
                }
            ],
            "listMyProfiles": _profiles(),
            "myScoutCommitments": {"items": []},
            "myUnits": {"items": [{"unitId": "UNIT-C"}], "pageInfo": {"hasNextPage": False}},
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)
    monkeypatch.setattr(api, "gql_raw", fake.gql_raw)
    monkeypatch.setattr(api, "publish_base_url", lambda: None)
    monkeypatch.setattr(api, "base_url", lambda: "https://dev.kernelworx.test")
    monkeypatch.setattr(lane, "sign_in", lambda persona: f"tok-{persona}")
    monkeypatch.setattr(lane, "build_lane", build_canary_then_break)
    monkeypatch.setattr(lane, "canary_snapshot", lambda admin, canary: copy.deepcopy(CANARY_SNAPSHOT))
    monkeypatch.setattr(lane, "recover_standing_commitments", lambda *args: ([], [], []))
    monkeypatch.setattr(lane, "residue_census", lambda lane_ids, own_ids: ([], {}))
    monkeypatch.setattr(lane.stage3, "stage_three_residue_census", lambda *args, **kwargs: {})
    monkeypatch.setattr(lane, "teardown", lambda admin, scout, lane_rows, written: [])
    monkeypatch.setattr(lane, "sweep_row", record_sweep)
    monkeypatch.setattr(
        lane,
        "_gone",
        lambda admin, canary, answered_before=True: {
            "removed": True,
            "readError": "",
            "reads": {"unitCampaigns": "fake: no rows", "myUnits": "fake: no longer answers Unit UNIT-C"},
        },
    )

    with pytest.raises(KeyboardInterrupt):
        lane.run(tmp_path, CURRENT)

    assert built == ["canary", "lane"]
    assert swept == [
        ["unit=UNIT-C", "unit-campaign=UC-C", "campaign=SC-C"]
        + [
            f"idem=stage3-{CANARY}-{marker}"
            for marker in (
                "createUnit-unit",
                "createUnitCampaign-campaign",
                "joinUnitCampaign-join",
                "removeUnitCampaignMembership-remove-join",
            )
        ]
    ]
    record = json.loads((tmp_path / f"{CURRENT}.json").read_text(encoding="utf-8"))
    assert record["canary"]["removed"] is True
    assert record["canary"]["before"], "the before-snapshot never reached the record to be compared against"
    assert record["canary"]["identical"] is True
    assert record["canary"]["unitAnsweredBeforeSweep"] is True, "the control read never ran before the canary's sweep"
    assert record["canary"]["goneReads"]["myUnits"].startswith("fake")
    assert record["canarySweep"]["tokens"][0] == "unit=UNIT-C"
    assert any(row["acceptance"] == "§3.7.7 lane sweep" for row in record["cleanup"])
    assert record["error"].startswith("KeyboardInterrupt"), "an interrupted run must say so in its own record"
    assert all(row["result"] == stage2.CLEANUP_OBSERVED for row in record["cleanup"])


def test_a_run_that_never_reached_its_canary_snapshot_says_so_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The compare is taken late if it was never taken, and a compare that refuses is a failed run."""
    canary: Dict[str, Any] = {
        "dataId": CANARY,
        "unitId": "UNIT-C",
        "unitCampaignId": "UC-C",
        "scoutCampaignId": "SC-C",
    }

    def snapshot_refused(admin: str, target: Mapping[str, Any]) -> Dict[str, Any]:
        raise AssertionError("the canary snapshot answered no roster row")

    monkeypatch.setattr(lane, "teardown", lambda *args: [])
    monkeypatch.setattr(
        lane,
        "sweep_row",
        lambda tokens, census: (
            lane.stage3.cleanup_row("§3.7.7 lane sweep", "fake sweep", stage2.CLEANUP_OBSERVED),
            {"tokens": list(tokens)},
        ),
    )
    monkeypatch.setattr(lane, "_unit_answers", lambda admin, unit_id: True)
    monkeypatch.setattr(lane, "canary_snapshot", snapshot_refused)
    monkeypatch.setattr(
        lane, "_gone", lambda admin, target, answered_before=False: {"removed": True, "readError": "", "reads": {}}
    )

    record: Dict[str, Any] = {"canary": {"lane": canary}, "residueCensus": {}}
    cleanup: List[Dict[str, str]] = []
    lane.run_cleanup_steps("tok-admin", "tok-scout", {}, {}, canary, {}, [], record, cleanup)

    assert record["canary"]["snapshotTakenLate"] is True
    assert "answered no roster row" in record["canary"]["snapshotError"]
    assert record["canary"]["identical"] is False
    assert any(row["result"] == stage2.CLEANUP_FAILED for row in cleanup), "a canary read that refused is a failure"
    failures = lane.lane_failures({**record, "cleanup": cleanup})
    assert any("never snapshotted" in failure for failure in failures), failures
    assert any("cleanup step(s) not met" in failure for failure in failures), failures


# ---------------------------------------------------------------------------
# 5. the retained Show & Sell rows are counted where they actually live
# ---------------------------------------------------------------------------


def test_the_retained_show_and_sell_rows_are_counted_on_the_table_that_holds_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The aggregate is ``show_and_sells``, not ``unit-campaigns``.

    The checklist claimed the cancelled event and signup sat on ``kernelworx-unit-campaigns-ue1-dev``; the
    model puts both under a ``SHOW_AND_SELL#`` partition key on their own table, and the record has to name
    the table a reader would go and look at.
    """
    fake = FakeApi(
        {
            "showAndSell": lambda variables: _event("EV-1", CURRENT, status="CANCELLED"),
            "showAndSellSignups": {
                "items": [{"slotId": "SLOT-1", "profileId": FIXTURE_PROFILE, "status": "CANCELLED"}]
            },
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    residue = lane.show_and_sell_residue("tok-admin", {"dataId": CURRENT}, {"showAndSellId": "EV-1"})

    assert residue["table"] == "kernelworx-show-and-sells-ue1-dev" == lane.stage3.DEV_SHOW_AND_SELLS_TABLE
    assert residue["partitionKey"] == "SHOW_AND_SELL#EV-1"
    assert [row["sk"] for row in residue["eventRows"]] == ["METADATA"]
    assert residue["eventRows"][0]["status"] == "CANCELLED"
    assert [row["sk"] for row in residue["signupRows"]] == [f"SIGNUP#SLOT-1#{FIXTURE_PROFILE}"]
    assert residue["slotRows"] == []
    assert "2 row(s) under EV-1 answer this lane" in residue["note"]


def test_a_lane_that_wrote_no_event_counts_no_show_and_sell_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeApi({})
    monkeypatch.setattr(api, "gql", fake.gql)

    residue = lane.show_and_sell_residue("tok-admin", {"dataId": CANARY}, {})

    assert fake.calls == []
    assert residue["eventRows"] == [] and residue["signupRows"] == []
    assert "wrote no event" in residue["note"]


def test_the_post_sweep_read_reports_the_signup_projection_that_still_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After both sweeps the Scout's own projection is the read that proves the signup row is still there."""
    commitment = _commitment("EV-1", "SLOT-1", status="CANCELLED")
    fake = FakeApi({"listMyProfiles": _profiles(), "myScoutCommitments": {"items": [commitment]}})
    monkeypatch.setattr(api, "gql", fake.gql)

    rows, standing = lane.retained_commitment_rows("tok-scout", ["EV-1"])

    assert standing == 1
    assert "kernelworx-show-and-sells-ue1-dev SIGNUP#SLOT-1#" in rows[0]["summary"]
    assert "after the teardown and both sweeps ran" in rows[0]["summary"]

    untouched, count = lane.retained_commitment_rows("tok-scout", [])
    assert (untouched, count) == ([], 0)
    assert fake.calls  # the first read ran; the second names no event, so it reads nothing


# ---------------------------------------------------------------------------
# 3 and 4. the exit gate
# ---------------------------------------------------------------------------


CANARY_SNAPSHOT = {
    "unit": {"unitId": "UNIT-C", "displayName": "Stage 3 Lane w168can-1225010101"},
    "unitCampaigns": [{"unitCampaignId": "UC-C", "joinCode": "****************"}],
    "roster": [{"campaignId": "SC-C", "status": "ACTIVE"}],
}


def _record(rows: List[Dict[str, str]], **canary: Any) -> Dict[str, Any]:
    guard: Dict[str, Any] = {
        "lane": {"dataId": CANARY},
        "before": copy.deepcopy(CANARY_SNAPSHOT),
        "after": copy.deepcopy(CANARY_SNAPSHOT),
        "identical": True,
        "removed": True,
    }
    guard.update(canary)
    return {"cleanup": rows, "canary": guard}


def test_a_clean_record_passes_and_a_failed_step_always_costs_the_run() -> None:
    clean = [lane.stage3.cleanup_row("§3.7.7 cancel the lane's event", "answered CANCELLED", stage2.CLEANUP_OBSERVED)]
    assert lane.lane_failures(_record(clean)) == []

    failed = clean + [lane.stage3.cleanup_row("§3.7.7 delete the lane's slot", "still answered", stage2.CLEANUP_FAILED)]
    failures = lane.lane_failures(_record(failed))
    assert len(failures) == 1 and "cleanup step(s) not met" in failures[0]


def test_strict_cleanup_is_the_one_step_reversal_for_a_blocked_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SS_STRICT_CLEANUP=1`` has to reach the exit status, not only the printed summary."""
    rows = [
        lane.stage3.cleanup_row(
            "§3.7.7 enumerate the residue", "kernelworx-inventory-ue1-dev: blocked", stage2.CLEANUP_BLOCKED
        )
    ]
    assert lane.lane_failures(_record(rows)) == [], "a blocked step is reported, not failed, by default"
    monkeypatch.setattr(stage2, "STRICT_CLEANUP", True)
    failures = lane.lane_failures(_record(rows))
    assert len(failures) == 1 and "blocked" in failures[0]


def test_a_canary_that_was_not_read_back_as_gone_fails_the_run() -> None:
    assert lane.lane_failures(_record([], removed=False)) == [
        "the canary's removal was not affirmatively read back: the read after its own sweep still answered "
        "Unit Campaign rows for that Unit"
    ]


def test_a_canary_read_that_errors_is_a_failed_read_back_when_the_unit_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal from the Campaign read is not an absence while the Unit row is still answered."""
    fake = FakeApi(
        {},
        refusals={"unitCampaigns": "ThrottlingException: slow down"},
    )
    fake.answers["myUnits"] = {"items": [{"unitId": "UNIT-C"}], "pageInfo": {"hasNextPage": False}}
    monkeypatch.setattr(api, "gql", fake.gql)

    answer = lane._gone("tok-admin", {"unitId": "UNIT-C"}, answered_before=True)

    assert answer["removed"] is False
    assert "still answered by myUnits" in answer["readError"]
    assert "ThrottlingException" in answer["readError"]
    failures = lane.lane_failures(_record([], removed=False, goneReadError=answer["readError"]))
    assert len(failures) == 1 and "ThrottlingException" in failures[0]


def test_a_canary_read_that_errors_is_read_as_gone_only_against_the_answer_that_saw_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Unit not found`` is what a successful sweep leaves, and only the Unit list can prove it.

    The sweep deletes the Unit row, so the Campaign read refuses rather than answering nothing.  That is an
    absence because the same identity's Unit list named this Unit while the canary stood and no longer names
    it — which is also why the control is required: a list that never named the row proves nothing.
    """
    fake = FakeApi(
        {"unitCampaigns": {"items": []}, "myUnits": {"items": [], "pageInfo": {"hasNextPage": False}}},
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    answer = lane._gone("tok-admin", {"unitId": "UNIT-C"}, answered_before=True)
    assert answer == {
        "removed": True,
        "readError": "",
        "reads": {
            "unitCampaigns": "answers 0 Unit Campaign row(s) for Unit UNIT-C",
            "myUnits": "no longer answers Unit UNIT-C",
        },
    }

    uncontrolled = lane._gone("tok-admin", {"unitId": "UNIT-C"}, answered_before=False)
    assert uncontrolled["removed"] is False
    assert "never answered this Unit while the canary stood" in uncontrolled["readError"]

    refused = FakeApi({"unitCampaigns": {"items": []}}, refusals={"myUnits": "Internal Server Error"})
    monkeypatch.setattr(api, "gql", refused.gql)
    broken = lane._gone("tok-admin", {"unitId": "UNIT-C"}, answered_before=True)
    assert broken["removed"] is False
    assert "Unit read that would confirm" in broken["readError"]


def test_a_canary_whose_unit_still_answers_its_campaigns_is_never_read_as_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeApi({"unitCampaigns": {"items": [{"unitCampaignId": "UC-C"}]}})
    monkeypatch.setattr(api, "gql", fake.gql)

    answer = lane._gone("tok-admin", {"unitId": "UNIT-C"}, answered_before=True)

    assert answer["removed"] is False and answer["readError"] == "its Unit still answers its Unit Campaign rows"


def test_a_canary_with_no_before_snapshot_fails_the_run() -> None:
    """An absent before-read is a missing proof, not a canary that was left alone."""
    assert lane.lane_failures(_record([], before={}, identical=False)) == [
        "the canary was never snapshotted, so nothing proves this lane's sweep left it alone"
    ]
    assert lane.lane_failures(
        _record([], before={}, identical=False, snapshotError="the canary snapshot answered no roster row")
    ) == [
        "the canary was never snapshotted, so nothing proves this lane's sweep left it alone: "
        "the canary snapshot answered no roster row"
    ]


def test_the_canary_snapshot_masks_a_join_code_and_refuses_a_read_that_answered_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshot is written into the record, and an empty one compares equal to an empty one.

    ``unitCampaigns`` answers a live join code for a Campaign that is still open, so the code has to be
    masked on the way in rather than redacted afterwards.  And a snapshot with nothing in it would let the
    before/after compare pass on a lane that was never read, which is the one claim it exists to support.
    """
    live_code = secrets.token_hex(8)  # the stack's own shape: 16 hexadecimal characters
    fake = FakeApi(
        {
            "unit": {"unitId": "UNIT-C", "displayName": "Stage 3 Lane w168can-1225010101"},
            "unitCampaigns": {"items": [{"unitCampaignId": "UC-C", "joinCode": live_code}]},
            "unitCampaignRoster": {"items": [{"campaignId": "SC-C", "status": "ACTIVE"}]},
        }
    )
    monkeypatch.setattr(api, "gql", fake.gql)

    snapshot = lane.canary_snapshot("tok-admin", {"dataId": CANARY, "unitId": "UNIT-C", "unitCampaignId": "UC-C"})

    assert snapshot["unitCampaigns"][0]["joinCode"] == "*" * len(live_code)
    assert live_code not in json.dumps(snapshot)

    empty = FakeApi(
        {
            "unit": None,
            "unitCampaigns": {"items": []},
            "unitCampaignRoster": {"items": [{"campaignId": "SC-C", "status": "ACTIVE"}]},
        }
    )
    monkeypatch.setattr(api, "gql", empty.gql)

    with pytest.raises(AssertionError) as refusal:
        lane.canary_snapshot("tok-admin", {"dataId": CANARY, "unitId": "UNIT-C", "unitCampaignId": "UC-C"})

    assert "answered no unit/unitCampaigns row" in str(refusal.value)


def test_a_canary_that_changed_across_the_sweep_fails_the_run() -> None:
    assert lane.lane_failures(_record([], identical=False)) == ["the canary lane changed across this lane's sweep"]


def test_a_census_that_could_not_run_fails_the_run() -> None:
    record = _record([])
    record["censusError"] = "ClientError: dynamodb:Scan is not granted to this identity"
    assert lane.lane_failures(record) == [f"censusError: {record['censusError']}"]


def test_a_lane_that_captured_nothing_is_swept_as_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ids, no sweep: a token list built from nothing would claim rows that were never written."""
    swept: List[List[str]] = []
    monkeypatch.setattr(
        lane,
        "sweep_row",
        lambda tokens, census: (
            swept.append(list(tokens))
            or (lane.stage3.cleanup_row("§3.7.7 lane sweep", "fake", stage2.CLEANUP_OBSERVED), {})
        ),
    )

    lane.run_cleanup_steps("tok-admin", "tok-scout", {}, {}, {}, {}, [], {}, [])

    assert swept == []
