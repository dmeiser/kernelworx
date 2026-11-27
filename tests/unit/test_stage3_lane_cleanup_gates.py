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
from tests.e2e.utils import show_sell_stage3_support as stage3

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
        lambda admin, canary, answered_before=True, control_error="": {
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
        lane,
        "_gone",
        lambda admin, target, answered_before=False, control_error="": {
            "removed": True,
            "readError": "",
            "reads": {},
        },
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


def _sweep_capture() -> tuple[List[List[str]], Callable[[Any, Any], Any]]:
    """A ``sweep_row`` stand-in that records the token list each sweep was handed."""
    swept: List[List[str]] = []

    def record_sweep(tokens: Any, census: Any) -> Any:
        swept.append(list(tokens))
        return (
            lane.stage3.cleanup_row("§3.7.7 lane sweep", "fake sweep", stage2.CLEANUP_OBSERVED),
            {"tokens": list(tokens)},
        )

    return swept, record_sweep


def _whole_lane(data_id: str, letter: str) -> Dict[str, Any]:
    """A lane dict with every id recorded, named by one letter so the expected tokens read plainly."""
    return {
        "dataId": data_id,
        "unitId": f"UNIT-{letter}",
        "unitCampaignId": f"UC-{letter}",
        "scoutCampaignId": f"SC-{letter}",
        "profileId": FIXTURE_PROFILE,
    }


@pytest.mark.parametrize("stage", ["before", "after"])
def test_a_canary_snapshot_the_transport_refuses_still_leaves_both_sweeps_run(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """An evidence read that fails is a failed proof; it never cancels the passes that take rows back.

    ``GraphQLError`` is a ``RuntimeError``, and a shared stack throttles as a matter of course, so a snapshot
    that refuses is an ordinary event in a lane that mutates that stack.  The first shape of this code caught
    only ``AssertionError``, so one throttled read left both the lane's and the canary's rows unswept and a
    record whose only mention of them was a traceback.
    """

    def snapshot_refused(admin: str, target: Mapping[str, Any]) -> Dict[str, Any]:
        raise api.GraphQLError("ThrottlingException: slow down", ["INTERNAL"], {"errors": [{"message": "slow"}]})

    swept, record_sweep = _sweep_capture()
    monkeypatch.setattr(lane, "canary_snapshot", snapshot_refused)
    monkeypatch.setattr(lane, "sweep_row", record_sweep)
    monkeypatch.setattr(lane, "teardown", lambda admin, scout, lane_rows, written: [])
    monkeypatch.setattr(lane, "_unit_answers", lambda admin, unit_id: False)
    monkeypatch.setattr(lane, "_safe_reads", lambda admin, unit_campaign_id: {})

    canary: Dict[str, Any] = {
        "dataId": CANARY,
        "unitId": "UNIT-C",
        "unitCampaignId": "UC-C",
        "scoutCampaignId": "SC-C",
        "profileId": FIXTURE_PROFILE,
    }
    record: Dict[str, Any] = {"canary": {"lane": canary}, "residueCensus": {}, "canaryResidueCensus": {}}
    cleanup: List[Dict[str, str]] = []
    lane.run_cleanup_steps(
        "tok-admin",
        "tok-scout",
        _whole_lane(CURRENT, "L"),
        {},
        canary,
        copy.deepcopy(CANARY_SNAPSHOT) if stage == "after" else {},
        [],
        record,
        cleanup,
    )

    assert "GraphQLError" in record["canary"]["snapshotError"], record["canary"]["snapshotError"]
    if stage == "after":
        assert record["canary"]["snapshotError"].startswith("the after-sweep read refused:")
        assert record["canary"]["before"] == CANARY_SNAPSHOT, "a snapshot this run did take was dropped"
    else:
        assert record["canary"]["before"] == {}, "a snapshot this run could not take was invented"
    assert record["canary"]["identical"] is False, "a compare with one side missing is not a passing compare"
    assert any(row["result"] == stage2.CLEANUP_FAILED for row in cleanup), cleanup
    expected = [
        f"{kind}={value}" for kind, value in (("unit", "UNIT-L"), ("unit-campaign", "UC-L"), ("campaign", "SC-L"))
    ] + [
        f"idem=stage3-{CURRENT}-{marker}"
        for marker in (
            "createUnit-unit",
            "createUnitCampaign-campaign",
            "joinUnitCampaign-join",
            "removeUnitCampaignMembership-remove-join",
        )
    ]
    canary_expected = [
        f"{kind}={value}" for kind, value in (("unit", "UNIT-C"), ("unit-campaign", "UC-C"), ("campaign", "SC-C"))
    ] + [
        f"idem=stage3-{CANARY}-{marker}"
        for marker in (
            "createUnit-unit",
            "createUnitCampaign-campaign",
            "joinUnitCampaign-join",
            "removeUnitCampaignMembership-remove-join",
        )
    ]
    assert swept == [expected, canary_expected], "a refused evidence read cancelled the sweep it should not touch"
    missing_side = "never snapshotted" if stage == "before" else "never re-read after this lane's sweep"
    failures = lane.lane_failures(record)
    assert any(missing_side in failure and "ThrottlingException" in failure for failure in failures), failures


def test_a_canary_refused_at_its_unit_campaign_is_swept_and_never_snapshotted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half a canary is cleanup work, never a compare — and the compare says which it was.

    ``createUnitCampaign`` is the second setup write, so a canary refused there holds a real Unit row and its
    ``createUnit`` marker, both of which only the sweeper takes back.  ``canary_snapshot`` reads a whole lane's
    Unit Campaign and roster rows, so attempting it on this canary raised ``KeyError`` inside the evidence read
    and, on the strength of that, left the canary's Unit standing in the shared stack.
    """
    fake = FakeApi(_setup_answers(), refusals={"createUnitCampaign": "createUnitCampaign refused by the fake"})
    monkeypatch.setattr(api, "gql", fake.gql)
    monkeypatch.setattr(api, "gql_raw", fake.gql_raw)

    snapshotted: List[str] = []

    def snapshot(admin: str, target: Mapping[str, Any]) -> Dict[str, Any]:
        snapshotted.append(str(target.get("dataId")))
        return copy.deepcopy(CANARY_SNAPSHOT)

    swept, record_sweep = _sweep_capture()
    monkeypatch.setattr(lane, "canary_snapshot", snapshot)
    monkeypatch.setattr(lane, "sweep_row", record_sweep)
    monkeypatch.setattr(lane, "teardown", lambda admin, scout, lane_rows, written: [])
    monkeypatch.setattr(lane, "_safe_reads", lambda admin, unit_campaign_id: {})

    canary: Dict[str, Any] = {}
    with pytest.raises(api.GraphQLError):
        lane.build_lane("tok-admin", "tok-scout", lane.lane_names(CANARY, unit_number=2), "CAT-1", canary)
    assert canary.get("unitId") and not canary.get("unitCampaignId"), canary

    record: Dict[str, Any] = {"canary": {"lane": canary}, "residueCensus": {}, "canaryResidueCensus": {}}
    cleanup: List[Dict[str, str]] = []
    lane.run_cleanup_steps("tok-admin", "tok-scout", {}, {}, canary, {}, [], record, cleanup)

    assert snapshotted == [], "a canary with no Unit Campaign was read as though it were a whole lane"
    assert "stopped before it held a whole lane" in record["canary"]["snapshotError"]
    assert any(
        row["acceptance"] == "§3.7.7 snapshot the canary before any teardown"
        and row["result"] == stage2.CLEANUP_BLOCKED
        for row in cleanup
    ), cleanup
    assert record["canarySweep"]["tokens"] == [
        "unit=UNIT-1",
        f"idem=stage3-{CANARY}-createUnit-unit",
    ], "the only rows this canary ever wrote never reached the sweeper"
    assert swept == [record["canarySweep"]["tokens"]]


def test_a_control_read_that_fails_leaves_the_canary_unproven_and_still_sweeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The before-control is a read too, and its failure is named rather than confused with absence.

    A ``myUnits`` list that never answered this Unit proves nothing when it goes on not naming it; a list this
    run was throttled for proves nothing either, and the record has to tell those two silences apart.  Neither
    one is a reason to skip the canary's sweep.
    """
    calls = {"count": 0}

    def flaky_units(admin: str, unit_id: str) -> bool:
        calls["count"] += 1
        if calls["count"] == 1:
            raise api.GraphQLError("ThrottlingException: slow down", ["INTERNAL"], {"errors": [{"message": "slow"}]})
        return False

    swept, record_sweep = _sweep_capture()
    monkeypatch.setattr(lane, "canary_snapshot", lambda admin, target: copy.deepcopy(CANARY_SNAPSHOT))
    monkeypatch.setattr(lane, "sweep_row", record_sweep)
    monkeypatch.setattr(lane, "teardown", lambda admin, scout, lane_rows, written: [])
    monkeypatch.setattr(lane, "_unit_answers", flaky_units)
    monkeypatch.setattr(lane, "_safe_reads", lambda admin, unit_campaign_id: {})

    canary: Dict[str, Any] = {
        "dataId": CANARY,
        "unitId": "UNIT-C",
        "unitCampaignId": "UC-C",
        "scoutCampaignId": "SC-C",
        "profileId": FIXTURE_PROFILE,
    }
    record: Dict[str, Any] = {"canary": {"lane": canary}, "residueCensus": {}, "canaryResidueCensus": {}}
    cleanup: List[Dict[str, str]] = []
    lane.run_cleanup_steps(
        "tok-admin",
        "tok-scout",
        _whole_lane(CURRENT, "L"),
        {},
        canary,
        copy.deepcopy(CANARY_SNAPSHOT),
        [],
        record,
        cleanup,
    )

    assert record["canary"]["controlReadError"].startswith("GraphQLError: ThrottlingException")
    assert record["canary"]["unitAnsweredBeforeSweep"] is False
    assert record["canary"]["removed"] is False
    assert "control read that would have named this Unit failed" in record["canary"]["goneReadError"]
    assert swept and swept[-1][0] == "unit=UNIT-C", "the canary's sweep was skipped after a read failed"
    assert any(row["result"] == stage2.CLEANUP_FAILED for row in cleanup), cleanup
    assert any("not affirmatively read back" in failure for failure in lane.lane_failures(record))


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


def test_the_command_exits_130_for_an_interrupted_run_and_never_reports_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``run`` re-raises the interrupt; the entry point is what turns it into a failed exit.

    The lane used to wrap ``main()`` in ``contextlib.suppress(KeyboardInterrupt)``, so a run cut short skipped
    ``lane_failures`` entirely and left with exit status 0 — the one verdict this runner must never print for
    work it did not finish.
    """

    def interrupted(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise KeyboardInterrupt

    monkeypatch.setattr(lane, "run", interrupted)
    assert lane.cli(["--out", str(tmp_path)]) == 130


def test_the_command_still_prints_the_verdict_of_a_finished_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A completed run is still judged by the shared gate, failure and all."""
    failing = {
        "dataId": CURRENT,
        "canary": {},
        "cleanup": [lane.stage3.cleanup_row("§3.7.7 lane sweep", "sweep left rows", stage2.CLEANUP_FAILED)],
    }
    passing = {
        "dataId": CURRENT,
        "canary": {},
        "cleanup": [lane.stage3.cleanup_row("§3.7.7 lane sweep", "sweep took everything", stage2.CLEANUP_OBSERVED)],
    }
    monkeypatch.setattr(lane, "run", lambda *args, **kwargs: dict(failing))
    assert lane.cli(["--out", str(tmp_path)]) == 1
    monkeypatch.setattr(lane, "run", lambda *args, **kwargs: dict(passing))
    assert lane.cli(["--out", str(tmp_path)]) == 0


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


# ---------------------------------------------------------------------------
# 6. the read-only membership-guard disposition
# ---------------------------------------------------------------------------


CARD_GUARD = "ad3b956d-0000-4000-8000-000000000001"
FOREIGN_GUARD = "ad3b956d-0000-4000-8000-000000000002"
LIVE_GUARD = "ad3b956d-0000-4000-8000-000000000003"
TENANT_GUARD = "ad3b956d-0000-4000-8000-000000000004"
STALE_GUARD = "ad3b956d-0000-4000-8000-000000000099"
LIVE_SCOUT_GUARD = "ad3b956d-0000-4000-8000-000000000005"
UNPROVEN_GUARD = "ad3b956d-0000-4000-8000-000000000006"
ORPHAN_GUARD = "ad3b956d-0000-4000-8000-000000000007"
DENIED_GUARD = "ad3b956d-0000-4000-8000-000000000008"
STALE_PROJECTION_GUARD = "ad3b956d-0000-4000-8000-000000000009"
DENIED_PROFILE_GUARD = "ad3b956d-0000-4000-8000-000000000010"
UNIT_CAMPAIGN_TABLE = "kernelworx-unit-campaigns-ue1-dev"
CAMPAIGNS_TABLE = "kernelworx-campaigns-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-ue1-dev"
CARD_PROFILE = "00000000-0000-4000-8000-0000000000a1"
FOREIGN_PROFILE = "00000000-0000-4000-8000-0000000000a2"
LIVE_PROFILE = "00000000-0000-4000-8000-0000000000a3"
TENANT_PROFILE = "00000000-0000-4000-8000-0000000000a4"
LIVE_SCOUT_PROFILE = "00000000-0000-4000-8000-0000000000a5"
UNPROVEN_PROFILE = "00000000-0000-4000-8000-0000000000a6"
ORPHAN_PROFILE = "00000000-0000-4000-8000-0000000000a7"
STALE_PROJECTION_PROFILE = "00000000-0000-4000-8000-0000000000a8"
DENIED_PROFILE_ID = "00000000-0000-4000-8000-0000000000a9"
FIXTURE_SUB = "54780458-c0d1-70c7-99be-e78715e5198d"
POOL_ONLY_SUB = "66666666-6666-4666-8666-666666666666"
DEAD_UNIT_CAMPAIGN = "00000000-0000-4000-8000-uc0000000001"
LIVE_UNIT_CAMPAIGN = "00000000-0000-4000-8000-uc0000000003"
FIXTURE_MAIL = "qa-show-sell-scout@dev.kernelworx.app"
ADMIN_MAIL = "qa-show-sell-admin@dev.kernelworx.app"
POOL_ONLY_MAIL = "someone-else@kernelworx.app"

#: What botocore raises for this stack's QA identity on a table its policy does not open.  The lane turns that
#: into "this action is not granted on this table"; a test that raised something shorter would not prove the
#: record can tell "no rows" apart from "no permission".
DENIED_GET_ITEM = (
    "An error occurred (AccessDeniedException) when calling the GetItem operation: User: "
    "arn:aws:iam::750620721302:user/kernelworx-qa-ue1-dev is not authorized to perform: dynamodb:GetItem "
    f"on resource: arn:aws:dynamodb:us-east-1:750620721302:table/{CAMPAIGNS_TABLE} because no identity-based "
    "policy allows the dynamodb:GetItem action"
)
NAMED_ACCEPTANCE = "§3.7.7 verify by key that every membership guard this card named is gone"

#: What botocore answers when this identity reaches for the ``profileId-index`` projection at all.  Kept apart
#: from "the projection answers no row": one is a refusal this pass cannot answer, the other is a read that
#: says the Profile is gone, and both mean no owner is proven — neither may become an attribution.
DENIED_PROFILE_QUERY = (
    "An error occurred (AccessDeniedException) when calling the Query operation: User: "
    "arn:aws:iam::750620721302:user/kernelworx-qa-ue1-dev is not authorized to perform: dynamodb:Query "
    f"on resource: arn:aws:dynamodb:us-east-1:750620721302:table/{PROFILES_TABLE}/index/profileId-index "
    "because no identity-based policy allows the dynamodb:Query action"
)


def _raw(row: Mapping[str, str]) -> Dict[str, Dict[str, str]]:
    """One row in the AttributeValue spelling the raw DynamoDB client answers with."""
    return {name: {"S": value} for name, value in row.items()}


class FakeDdb:
    """The read shapes the guard pass is allowed to make, and nothing else.

    Every write verb raises, because the whole point of this pass is that it can only report: what a sweep
    token deletes is scoped by an id the guard row itself does not carry.  The fake also records every read
    with its key values and its ``ConsistentRead`` flag, so a test can say "this pass asked for exactly these
    keys, consistently" instead of trusting the summary the pass printed about itself.

    ``projections`` are rows the ``profileId-index`` answers and the base table does not — the stale projection
    a profile transfer or delete leaves behind — which is how a test can make the pass choose between an index
    entry and the consistent read that would confirm it.  ``denied_profiles`` names the profile ids whose index
    read this identity is refused.
    """

    def __init__(
        self,
        partitions: Dict[str, List[Dict[str, str]]],
        profiles: List[Dict[str, str]],
        scout_campaigns: Mapping[str, Dict[str, str]],
        denied_campaigns: List[str],
        denied_guards: List[str],
        projections: List[Dict[str, str]] | None = None,
        denied_profiles: List[str] | None = None,
    ) -> None:
        self.partitions = partitions
        self.profiles = profiles
        self.projections = list(projections or [])
        self.denied_profile_ids = list(denied_profiles or [])
        self.scout_campaigns = dict(scout_campaigns)
        self.denied_campaigns = list(denied_campaigns)
        self.denied_guard_keys = [f"SCOUT_CAMPAIGN#CAMPAIGN#{guard}" for guard in denied_guards]
        self.reads: List[tuple[str, str, tuple[str, ...], Any]] = []
        self.scans: List[str] = []

    def get_item(
        self, *, TableName: str, Key: Mapping[str, Any], ConsistentRead: Any = False, **_: Any
    ) -> Dict[str, Any]:
        self.reads.append(
            (
                "get_item",
                TableName,
                tuple(sorted(f"{name}={value['S']}" for name, value in Key.items())),
                ConsistentRead,
            )
        )
        if TableName == UNIT_CAMPAIGN_TABLE:
            pk, sk = Key["pk"]["S"], Key["sk"]["S"]
            if pk in self.denied_guard_keys:
                raise RuntimeError(DENIED_GET_ITEM)
            row = next((item for item in self.partitions.get(pk, []) if item.get("sk") == sk), None)
            return {"Item": _raw(row)} if row else {}
        if TableName == CAMPAIGNS_TABLE:
            campaign_id = Key["campaignId"]["S"]
            if campaign_id in self.denied_campaigns:
                raise RuntimeError(DENIED_GET_ITEM)
            item = self.scout_campaigns.get(campaign_id)
            return {"Item": _raw(item)} if item else {}
        if TableName == PROFILES_TABLE:
            row = next(
                (
                    item
                    for item in self.profiles
                    if item.get("profileId") == Key["profileId"]["S"]
                    and item.get("ownerAccountId") == Key["ownerAccountId"]["S"]
                ),
                None,
            )
            return {"Item": _raw(row)} if row else {}
        raise AssertionError(f"the guard pass read a table it should not: {TableName}")

    def query(
        self,
        *,
        TableName: str,
        IndexName: str = "",
        KeyConditionExpression: str = "",
        ExpressionAttributeValues: Mapping[str, Any],
        **_: Any,
    ) -> Dict[str, Any]:
        profile_id = str(ExpressionAttributeValues[":profile_id"]["S"])
        self.reads.append(("query", TableName, (f"index={IndexName}", f"profileId={profile_id}"), None))
        assert TableName == PROFILES_TABLE, "the guard pass queried a table it should not"
        assert IndexName == "profileId-index", "a profile id is only reachable through the product's own index"
        assert KeyConditionExpression == "profileId = :profile_id"
        if profile_id in self.denied_profile_ids:
            raise RuntimeError(DENIED_PROFILE_QUERY)
        rows = [row for row in [*self.profiles, *self.projections] if row.get("profileId") == profile_id]
        return {"Items": [_raw(row) for row in rows]}

    def scan(self, *, TableName: str, **_: Any) -> Dict[str, Any]:
        self.scans.append(TableName)
        assert TableName == UNIT_CAMPAIGN_TABLE, "the guard census reads the table that holds the guards"
        rows = [row for part in self.partitions.values() for row in part if row.get("sk") == lane.GUARD_SORT_KEY]
        return {"Items": [_raw(row) for row in rows]}

    def put_item(self, **_: Any) -> Any:
        raise AssertionError("the guard pass wrote a row")

    def update_item(self, **_: Any) -> Any:
        raise AssertionError("the guard pass wrote a row")

    def delete_item(self, **_: Any) -> Any:
        raise AssertionError("the guard pass deleted a row")

    def transact_write_items(self, **_: Any) -> Any:
        raise AssertionError("the guard pass wrote a row")

    def batch_write_item(self, **_: Any) -> Any:
        raise AssertionError("the guard pass wrote a row")

    def guard_reads(self, table: str = UNIT_CAMPAIGN_TABLE) -> List[tuple[str, str, tuple[str, ...], Any]]:
        """Every consistent key read this fake answered on one table."""
        return [read for read in self.reads if read[0] == "get_item" and read[1] == table]


class FakeTool:
    """The slice of ``scripts/qa_fixture.py`` the guard pass reads: its table map, its decoders, its allowlist.

    ``pool_users`` answers more identities than ``emails()`` does — the dev pool holds 26 users against the four
    the fixture script owns — because a pass that took the pool as its idea of "fixture data" would treat an
    ordinary account's Scout as a lane row.
    """

    SWEEP_TABLES = {
        "accounts": ("kernelworx-accounts-ue1-dev", ("accountId",), "accountId"),
        "units": ("kernelworx-units-ue1-dev", ("pk", "sk"), "createdByAccountId"),
        "unit-campaigns": (UNIT_CAMPAIGN_TABLE, ("pk", "sk"), "createdByAccountId"),
    }

    def __init__(self, ddb: FakeDdb, pool: Mapping[str, str], allowlist: Mapping[str, str]) -> None:
        self._ddb = ddb
        self.pool = pool
        self.allowlist = allowlist

    def ddb(self) -> FakeDdb:
        return self._ddb

    def cip(self) -> str:
        return "fake-pool-client"

    def emails(self) -> Dict[str, str]:
        return dict(self.allowlist)

    def pool_users(self, _client: Any) -> Dict[str, Dict[str, Any]]:
        return {mail: {"Attributes": [{"Name": "sub", "Value": sub}]} for sub, mail in self.pool.items()}

    @staticmethod
    def _strings(item: Mapping[str, Any]) -> Dict[str, str]:
        return {name: next(iter(value.values())) for name, value in item.items() if isinstance(value, Mapping)}

    @staticmethod
    def _attrs(user: Mapping[str, Any]) -> Dict[str, str]:
        return {attr["Name"]: attr["Value"] for attr in user.get("Attributes", [])}


def _guard(campaign: str, profile: str, unit_campaign: str = "") -> Dict[str, str]:
    """One guard row in the shape the table really stores: prefixed ids, and no ``activeUnitCampaignId`` at all
    once a join was released, rather than an empty one."""
    row = {
        "pk": f"SCOUT_CAMPAIGN#CAMPAIGN#{campaign}",
        "sk": lane.GUARD_SORT_KEY,
        "campaignId": f"CAMPAIGN#{campaign}",
        "profileId": f"PROFILE#{profile}",
        "membershipVersion": "1",
        "updatedAt": "2026-11-20T23:04:50.026150+00:00",
    }
    if unit_campaign:
        row["activeUnitCampaignId"] = unit_campaign
        row["unitId"] = "00000000-0000-4000-8000-unit000001"
    return row


def _profile_row(profile: str, seller: str, owner: str) -> Dict[str, str]:
    return {"profileId": f"PROFILE#{profile}", "sellerName": seller, "ownerAccountId": f"ACCOUNT#{owner}"}


def _guard_world(
    monkeypatch: pytest.MonkeyPatch, *, card_residue: bool = False, denied_guards: List[str] | None = None
) -> FakeDdb:
    """Guards on one Unit Campaign table, the Profiles that say who made each, and the Scout Campaigns that stand.

    Each guard fails a different half of the disposition, and none of them can be removed by this pass:

    * ``CARD_GUARD`` — fixture-owned, this card's label, dead at both ends: this card's own residue, so naming
      it fails the run rather than taking the row (present only when ``card_residue`` asks for it);
    * ``FOREIGN_GUARD`` — fixture-owned, but the Profile names another card's run;
    * ``LIVE_GUARD`` — declares an ACTIVE join whose Unit Campaign still answers its metadata row;
    * ``TENANT_GUARD`` — carries this card's label in its seller name and an account that is on the pool but
      **not** on the fixture allowlist, which is the case a name match alone gets wrong;
    * ``ORPHAN_GUARD`` — no Profile row answers it, so its owner cannot be proved at all;
    * ``STALE_PROJECTION_GUARD`` — the index still projects a Profile row naming an off-allowlist account and
      carrying this card's label, while the base-table key that row names answers nothing, so the projection is
      evidence of nothing;
    * ``DENIED_PROFILE_GUARD`` — the index read for its Profile is refused to this identity outright;
    * ``LIVE_SCOUT_GUARD`` — its Scout Campaign still answers the base-row read the product makes;
    * ``UNPROVEN_GUARD`` — that same read is refused to this identity, so nothing here can call it dead;
    * ``DENIED_GUARD`` — the read of the guard key itself is refused.

    ``ORPHAN_GUARD``'s Profile row is deliberately absent from ``profiles``, ``STALE_PROJECTION_GUARD``'s is in
    the index only, and ``CARD_GUARD``'s partition is empty in the passing world, so the suite's default is a
    pass with one residue finding: the Campaigns read.
    """
    partitions: Dict[str, List[Dict[str, str]]] = {
        f"SCOUT_CAMPAIGN#CAMPAIGN#{CARD_GUARD}": [_guard(CARD_GUARD, CARD_PROFILE, DEAD_UNIT_CAMPAIGN)]
        if card_residue
        else [],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{FOREIGN_GUARD}": [_guard(FOREIGN_GUARD, FOREIGN_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{LIVE_GUARD}": [_guard(LIVE_GUARD, LIVE_PROFILE, LIVE_UNIT_CAMPAIGN)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{TENANT_GUARD}": [_guard(TENANT_GUARD, TENANT_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{ORPHAN_GUARD}": [_guard(ORPHAN_GUARD, ORPHAN_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{STALE_PROJECTION_GUARD}": [_guard(STALE_PROJECTION_GUARD, STALE_PROJECTION_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{DENIED_PROFILE_GUARD}": [_guard(DENIED_PROFILE_GUARD, DENIED_PROFILE_ID)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{LIVE_SCOUT_GUARD}": [_guard(LIVE_SCOUT_GUARD, LIVE_SCOUT_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{UNPROVEN_GUARD}": [_guard(UNPROVEN_GUARD, UNPROVEN_PROFILE)],
        f"SCOUT_CAMPAIGN#CAMPAIGN#{DENIED_GUARD}": [_guard(DENIED_GUARD, CARD_PROFILE)],
        f"UNIT_CAMPAIGN#{DEAD_UNIT_CAMPAIGN}": [
            {"pk": f"UNIT_CAMPAIGN#{DEAD_UNIT_CAMPAIGN}", "sk": "MEMBERSHIP#PROFILE#x", "removedAt": "2026-11-20"}
        ],
        f"UNIT_CAMPAIGN#{LIVE_UNIT_CAMPAIGN}": [
            {
                "pk": f"UNIT_CAMPAIGN#{LIVE_UNIT_CAMPAIGN}",
                "sk": lane.METADATA_SORT_KEY,
                "campaignName": "QA167 Running Booth",
            }
        ],
    }
    profiles = [
        _profile_row(CARD_PROFILE, "Avery w168qa", FIXTURE_SUB),
        _profile_row(FOREIGN_PROFILE, "Avery Stage2 stage2-1118011", FIXTURE_SUB),
        _profile_row(LIVE_PROFILE, "Blake w168qa", FIXTURE_SUB),
        _profile_row(TENANT_PROFILE, "Charlie w168qa", POOL_ONLY_SUB),
        _profile_row(LIVE_SCOUT_PROFILE, "Avery w168lane", FIXTURE_SUB),
        _profile_row(UNPROVEN_PROFILE, "Avery w168can", FIXTURE_SUB),
    ]
    ddb = FakeDdb(
        partitions,
        profiles,
        {
            f"CAMPAIGN#{LIVE_SCOUT_GUARD}": {
                "profileId": f"PROFILE#{LIVE_SCOUT_PROFILE}",
                "campaignId": f"CAMPAIGN#{LIVE_SCOUT_GUARD}",
            }
        },
        [f"CAMPAIGN#{UNPROVEN_GUARD}"],
        list(denied_guards or []),
        [_profile_row(STALE_PROJECTION_PROFILE, "Charlie w168qa", POOL_ONLY_SUB)],
        [f"PROFILE#{DENIED_PROFILE_ID}"],
    )
    monkeypatch.setattr(
        lane,
        "_fixture_tool",
        lambda: FakeTool(
            ddb,
            {FIXTURE_SUB: FIXTURE_MAIL, POOL_ONLY_SUB: POOL_ONLY_MAIL},
            {"scout": FIXTURE_MAIL, "admin": ADMIN_MAIL},
        ),
    )

    def no_sweep(tokens: List[str]) -> Any:
        raise AssertionError(f"the guard pass reached the sweeper with {tokens}")

    monkeypatch.setattr(stage2, "fixture_sweep", no_sweep)
    return ddb


def _entry(detail: Mapping[str, Any], campaign: str) -> Dict[str, Any]:
    return next(row for row in detail["keys"] if row["campaignId"] == campaign)


def _named_row(rows: List[Dict[str, str]], campaign: str) -> Dict[str, str]:
    return next(row for row in rows if row["acceptance"] == NAMED_ACCEPTANCE and campaign in row["summary"])


def test_the_named_guard_keys_are_verified_absent_by_a_consistent_read_of_each_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keys this card owes are answered by a read of the key, not by a sweep line that once named one."""
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([CARD_GUARD, STALE_GUARD])

    assert detail["table"] == UNIT_CAMPAIGN_TABLE
    assert detail["campaignsTable"] == CAMPAIGNS_TABLE
    assert detail["profilesTable"] == PROFILES_TABLE
    assert detail["namedKeys"] == sorted([CARD_GUARD, STALE_GUARD])
    assert detail["namedAbsent"] == sorted([CARD_GUARD, STALE_GUARD])
    assert detail["guards"] == 11 and detail["guardRows"] == 9, detail["guards"]
    for key in (CARD_GUARD, STALE_GUARD):
        assert _entry(detail, key)["state"] == lane.GUARD_ABSENT, _entry(detail, key)
        row = _named_row(rows, key)
        assert row["result"] == stage2.CLEANUP_OBSERVED and "answers no item" in row["summary"], row
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) == []

    guard_reads = [read for read in ddb.guard_reads() if lane.GUARD_SORT_KEY in " ".join(read[2])]
    assert len(guard_reads) == 11, "a guard key was read more than once, or not at all"
    assert all(read[3] is True for read in guard_reads), "a guard key was read without a consistent read"
    parts = {part for read in guard_reads for part in read[2]}
    assert f"pk=SCOUT_CAMPAIGN#CAMPAIGN#{STALE_GUARD}" in parts and f"sk={lane.GUARD_SORT_KEY}" in parts


def test_the_guard_pass_never_reaches_the_sweeper_and_never_writes_a_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """No delete, no sweep token, no write verb: this pass can only say what the table answers.

    The sweeper's ``campaign=`` token deletes scoped rows on several tables on the strength of the id alone, and
    a guard row carries no lane id, so the mutation had to come out — and this gate is what keeps it out.
    """
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([CARD_GUARD])

    assert {read[0] for read in ddb.reads} == {"get_item", "query"}
    assert ddb.scans == [UNIT_CAMPAIGN_TABLE]
    assert "tokens" not in detail and "sweep" not in detail and "disposed" not in detail
    assert not any("deleted row" in row["summary"] for row in rows), rows


def test_the_fixture_allowlist_is_the_sweeper_s_own_set_and_not_every_user_on_the_pool() -> None:
    """Every ordinary dev account is on the pool; only the addresses the fixture script owns are fixture data."""

    class PoolTool(FakeTool):
        def pool_users(self, _client: Any) -> Dict[str, Dict[str, Any]]:
            everyone = {f"sub-{index}": f"tenant-{index}@kernelworx.app" for index in range(22)}
            everyone.update(dict(self.pool))
            return {mail: {"Attributes": [{"Name": "sub", "Value": sub}]} for sub, mail in everyone.items()}

    tool = PoolTool(
        FakeDdb({}, [], {}, [], []),
        {FIXTURE_SUB: FIXTURE_MAIL, POOL_ONLY_SUB: POOL_ONLY_MAIL},
        {"scout": FIXTURE_MAIL, "admin": ADMIN_MAIL},
    )
    identities = lane._fixture_allowlist(tool)

    assert len(tool.pool_users(tool.cip())) == 24, "the pool no longer outnumbers the allowlist this test proves"
    assert identities == {FIXTURE_SUB: FIXTURE_MAIL}
    assert POOL_ONLY_SUB not in identities, "a pool account outside the fixture allowlist read as fixture data"
    assert set(tool.emails().values()) == {FIXTURE_MAIL, ADMIN_MAIL} and ADMIN_MAIL not in identities.values()


def test_a_pool_account_outside_the_fixture_allowlist_is_never_this_card_s_residue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seller name matches this card's label and the account is on the pool, and that is still not enough.

    This is the case the ownership gate exists for: every lane on this stack signs in as the same four fixture
    addresses, so a substring in a name says nothing about whose row it is until the allowlist agrees.
    """
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([TENANT_GUARD])

    entry = _entry(detail, TENANT_GUARD)
    assert entry["state"] == lane.GUARD_OTHER_TENANT, entry
    assert entry["sellerName"] == "Charlie w168qa" and entry["claimLabel"] == "w168qa"
    assert entry["ownerInFixtureAllowlist"] is False and entry["ownerAddress"] == ""
    assert entry["profileConfirmed"] is True, "other-tenant is only ever a confirmed owner off the allowlist"
    assert detail["fixtureAllowlist"] == [FIXTURE_MAIL]
    row = _named_row(rows, TENANT_GUARD)
    assert row["result"] == stage2.CLEANUP_OBSERVED, "an owner outside the allowlist is proven not this card's"
    assert "fixture allowlist" in entry["reason"] or "could not be read" in entry["reason"], entry["reason"]
    assert all(read[0] in {"get_item", "query"} for read in ddb.reads)


def test_a_live_join_s_guard_is_reported_as_live_and_never_counted_as_residue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Taking the guard of a standing join would leave an ACTIVE roster row with nothing enforcing it."""
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([LIVE_GUARD])

    entry = _entry(detail, LIVE_GUARD)
    assert entry["state"] == lane.GUARD_LIVE_JOIN, entry
    assert entry["activeUnitCampaignId"] == LIVE_UNIT_CAMPAIGN and entry["activeJoinStands"] is True
    assert "QA167 Running Booth" in entry["reason"]
    assert LIVE_GUARD not in detail["byState"].get(lane.GUARD_CARD_RESIDUE, [])
    assert _named_row(rows, LIVE_GUARD)["result"] == stage2.CLEANUP_OBSERVED
    assert any(f"pk=UNIT_CAMPAIGN#{LIVE_UNIT_CAMPAIGN}" in part for read in ddb.guard_reads() for part in read[2])


def test_a_guard_whose_scout_campaign_stands_on_the_product_s_own_read_is_not_residue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Scout Campaign is read where the product reads it: its base row, by the pair the guard itself names.

    The earlier revision looked for a ``METADATA`` row beside the guard on the Unit Campaign table, where no
    Scout Campaign ever has one — measured on ``dev``, 0 of 53 partitions hold one — so that test was true of
    every guard on the table and pruned nothing.
    """
    ddb = _guard_world(monkeypatch)
    _rows, detail = lane.verify_guard_residue([LIVE_SCOUT_GUARD])

    entry = _entry(detail, LIVE_SCOUT_GUARD)
    assert entry["state"] == lane.GUARD_LIVE_SCOUT_CAMPAIGN, entry
    assert entry["scoutCampaignStands"] is True and entry["scoutCampaignError"] == ""
    campaigns_reads = [read for read in ddb.reads if read[1] == CAMPAIGNS_TABLE]
    assert campaigns_reads and all(read[3] is True for read in campaigns_reads)
    assert (f"campaignId=CAMPAIGN#{LIVE_SCOUT_GUARD}", f"profileId=PROFILE#{LIVE_SCOUT_PROFILE}") in {
        read[2] for read in campaigns_reads
    }, campaigns_reads


def test_a_scout_campaign_read_that_is_denied_is_reported_unproven_and_never_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read this identity is not allowed to make is a finding, not an empty result.

    ``kernelworx-qa-ue1-dev`` is granted no read on the Campaigns table at all, so no credential this pass holds
    can prove a standing guard's Campaign is gone — which is a second reason it removes nothing.
    """
    _ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([UNPROVEN_GUARD])

    entry = _entry(detail, UNPROVEN_GUARD)
    assert entry["state"] == lane.GUARD_UNPROVEN, entry
    assert entry["sellerName"] == "Avery w168can" and entry["ownerInFixtureAllowlist"] is True
    assert UNPROVEN_GUARD in detail["byState"][lane.GUARD_UNPROVEN]
    blocked = [row for row in rows if row["acceptance"].endswith("the way the product reads it")]
    assert blocked and blocked[0]["result"] == stage2.CLEANUP_BLOCKED, blocked
    assert (
        f"{CAMPAIGNS_TABLE}: GetItem is not granted to this identity (dynamodb:GetItem denied)" in blocked[0]["summary"]
    )
    assert _named_row(rows, UNPROVEN_GUARD)["result"] == stage2.CLEANUP_FAILED, "an unprovable named key must fail"
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) != []


def test_the_denied_campaigns_read_is_a_blocked_step_under_strict_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SS_STRICT_CLEANUP=1`` reaches this step too, so Amendment C's one-step reversal holds of it."""
    _ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue()
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) == []
    monkeypatch.setattr(stage2, "STRICT_CLEANUP", True)
    failures = lane.lane_failures({"cleanup": rows, "guardResidue": detail})
    assert len(failures) == 1 and "not met" in failures[0], failures


def test_this_card_s_own_surviving_residue_fails_the_named_key_instead_of_deleting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provable residue still standing is reported as a failure, with the sanctioned path named.

    The pass says how the row should be taken — by the sweeper, with its Campaign id named — and does not take it
    itself, because the row a token would delete is not provably this run's.
    """
    ddb = _guard_world(monkeypatch, card_residue=True)
    rows, detail = lane.verify_guard_residue([CARD_GUARD])

    entry = _entry(detail, CARD_GUARD)
    assert entry["state"] == lane.GUARD_CARD_RESIDUE, entry
    assert entry["claimLabel"] == "w168qa" and entry["ownerAddress"] == FIXTURE_MAIL
    row = _named_row(rows, CARD_GUARD)
    assert row["result"] == stage2.CLEANUP_FAILED, row
    assert "scripts/qa_fixture.py sweep with campaign=" in row["summary"]
    assert ddb.partitions[f"SCOUT_CAMPAIGN#CAMPAIGN#{CARD_GUARD}"] != [], "the pass removed the row it must report"
    assert all(read[0] in {"get_item", "query"} for read in ddb.reads)
    assert any("cleanup step(s) not met" in failure for failure in lane.lane_failures({"cleanup": rows}))


def test_a_guard_key_whose_read_is_refused_is_a_failure_and_not_an_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No permission and no row are different answers, and only one of them can pass a named key."""
    _ddb = _guard_world(monkeypatch, denied_guards=[DENIED_GUARD])
    rows, detail = lane.verify_guard_residue([DENIED_GUARD])

    entry = _entry(detail, DENIED_GUARD)
    assert entry["state"] == lane.GUARD_UNREADABLE, entry
    assert entry["guardPresent"] is False and entry["guardError"]
    assert DENIED_GUARD not in detail["verifiedAbsent"]
    assert _named_row(rows, DENIED_GUARD)["result"] == stage2.CLEANUP_FAILED


def test_a_guard_with_no_profile_row_cannot_be_attributed_to_this_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An owner that cannot be read is not a fixture identity, and it is not somebody else's either."""
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([ORPHAN_GUARD])

    entry = _entry(detail, ORPHAN_GUARD)
    assert entry["state"] == lane.GUARD_OWNER_UNPROVEN, entry
    assert entry["profileLocated"] == 0 and entry["profileConfirmed"] is False
    assert entry["ownerInFixtureAllowlist"] is False and entry["ownerAddress"] == ""
    assert "no base-table row answers" in entry["reason"] and "no proven owner" in entry["reason"], entry["reason"]
    assert f"profileId=PROFILE#{ORPHAN_PROFILE}" in {part for read in ddb.reads for part in read[2]}
    assert _named_row(rows, ORPHAN_GUARD)["result"] == stage2.CLEANUP_FAILED, (
        f"a named key with no verified owner has no disposition that can pass: {entry}"
    )
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) != []


def test_a_stale_index_projection_names_no_owner_and_fails_the_named_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The index projecting a row the base table no longer answers is evidence of nothing.

    This is the case the product refuses to act on at ``public_orders_offer._consistent_profile``: a
    ``profileId-index`` entry can outlive the row, and after a transfer it can even name the previous owner.
    Here the projection carries this card's label and an account off the fixture allowlist, so an owner taken
    from it would read as a proven foreign tenant and let a named key pass on an entry that proves nothing.
    """
    ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([STALE_PROJECTION_GUARD])

    entry = _entry(detail, STALE_PROJECTION_GUARD)
    assert entry["state"] == lane.GUARD_OWNER_UNPROVEN, entry
    assert entry["profileLocated"] == 1 and entry["profileConfirmed"] is False
    assert entry["sellerName"] == "" and entry["claimLabel"] == "", "a stale projection named this row"
    assert entry["ownerInFixtureAllowlist"] is False and entry["ownerAddress"] == ""
    assert "stale projection" in entry["reason"], entry["reason"]
    assert STALE_PROJECTION_GUARD in detail["byState"][lane.GUARD_OWNER_UNPROVEN]
    profiles_reads = [read for read in ddb.reads if read[0] == "get_item" and read[1] == PROFILES_TABLE]
    assert (f"ownerAccountId=ACCOUNT#{POOL_ONLY_SUB}", f"profileId=PROFILE#{STALE_PROJECTION_PROFILE}") in {
        read[2] for read in profiles_reads
    }, "the pass never asked the base table whether the projected key answers a row"
    assert all(read[3] is True for read in profiles_reads)
    assert _named_row(rows, STALE_PROJECTION_GUARD)["result"] == stage2.CLEANUP_FAILED
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) != []


def test_a_profile_read_that_is_denied_earns_no_attribution_and_fails_the_named_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused ownership read is a finding about the credentials, never a verdict about the row."""
    _ddb = _guard_world(monkeypatch)
    rows, detail = lane.verify_guard_residue([DENIED_PROFILE_GUARD])

    entry = _entry(detail, DENIED_PROFILE_GUARD)
    assert entry["state"] == lane.GUARD_OWNER_UNPROVEN, entry
    assert f"{PROFILES_TABLE}: Query is not granted to this identity (dynamodb:Query denied)" in entry["profileError"]
    assert entry["profileLocated"] == 0 and entry["profileConfirmed"] is False
    assert entry["sellerName"] == "" and entry["ownerAddress"] == ""
    assert entry["reason"].startswith(f"the Profile {DENIED_PROFILE_ID} could not be read"), entry["reason"]
    assert DENIED_PROFILE_GUARD in detail["byState"][lane.GUARD_OWNER_UNPROVEN]
    assert DENIED_PROFILE_GUARD not in detail["byState"].get(lane.GUARD_OTHER_TENANT, [])
    assert _named_row(rows, DENIED_PROFILE_GUARD)["result"] == stage2.CLEANUP_FAILED
    assert lane.lane_failures({"cleanup": rows, "guardResidue": detail}) != []


def test_a_guard_key_with_no_disposition_fails_the_record() -> None:
    """Half a census is worse than none: every key the pass counted has to carry a disposition."""
    failures = lane.lane_failures(
        {"cleanup": [], "guardResidue": {"guards": 4, "keys": [{"campaignId": CARD_GUARD, "state": lane.GUARD_ABSENT}]}}
    )
    assert any("carry a disposition" in failure for failure in failures), failures


def test_a_named_key_the_record_never_reads_fails_the_record() -> None:
    """A key named on the command line cannot be dropped from the record without saying so."""
    failures = lane.lane_failures(
        {
            "cleanup": [],
            "guardResidue": {
                "guards": 1,
                "keys": [{"campaignId": CARD_GUARD, "state": lane.GUARD_ABSENT}],
                "namedKeys": [CARD_GUARD, STALE_GUARD],
            },
        }
    )
    assert any(STALE_GUARD in failure for failure in failures), failures


def test_the_guard_pass_still_writes_its_record_when_a_read_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pass that died part-way still leaves a record that says it died, and the exit gate reads that."""

    def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the profiles table refused: AccessDeniedException")

    monkeypatch.setattr(lane, "verify_guard_residue", refused)
    record = lane.verify_guards(tmp_path)

    assert record["mode"] == "guard-verify" and record["error"].startswith("AssertionError")
    written = json.loads((tmp_path / f"{record['dataId']}.json").read_text(encoding="utf-8"))
    assert written["error"] == record["error"]
    assert written["cleanup"][0]["result"] == stage2.CLEANUP_FAILED
    assert lane.lane_failures(written)


def test_a_written_guard_record_carries_every_key_state_and_the_census_names_what_stands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The record on disk is the deliverable, and it has to keep residue and verified absence apart.

    "8 keys were examined" and "1 key is verified absent" are different claims: a summary that counted the rows
    still standing as if they had been dealt with would read as a clean table.
    """
    _guard_world(monkeypatch)
    first = lane.verify_guards(tmp_path, [STALE_GUARD])
    written = json.loads((tmp_path / f"{first['dataId']}.json").read_text(encoding="utf-8"))

    assert written["mode"] == "guard-verify"
    assert written.get("error") is None, written["error"]
    residue = written["guardResidue"]
    assert residue["guards"] == 10 and residue["guardRows"] == 9
    assert len(residue["keys"]) == residue["guards"]
    assert residue["namedKeys"] == [STALE_GUARD] and residue["namedAbsent"] == [STALE_GUARD]
    assert residue["verifiedAbsent"] == [STALE_GUARD]
    assert residue["byState"][lane.GUARD_LIVE_JOIN] == [LIVE_GUARD]
    assert residue["byState"][lane.GUARD_OTHER_TENANT] == [TENANT_GUARD]
    assert residue["byState"][lane.GUARD_UNPROVEN] == [UNPROVEN_GUARD]
    assert residue["byState"][lane.GUARD_OWNER_UNPROVEN] == sorted(
        [ORPHAN_GUARD, STALE_PROJECTION_GUARD, DENIED_PROFILE_GUARD]
    )
    census = next(row["summary"] for row in written["cleanup"] if "answers 9 MEMBERSHIP_GUARD row(s)" in row["summary"])
    assert "10 key(s) examined" in census and "1 answer no row at all" in census, census
    assert "whose owner no base-table read confirms, 1 nobody here can prove dead" in census, census
    assert "this card's own residue" in census, census
    assert written["cleanup"][0]["result"] == stage2.CLEANUP_OBSERVED
    assert lane.lane_failures(written) == []


def test_a_key_named_again_after_it_is_gone_is_still_verified_by_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Re-running the pass over a key that is already gone says so by read, and reaches nothing."""
    _guard_world(monkeypatch)
    again = lane.verify_guards(tmp_path, [CARD_GUARD])
    second = json.loads((tmp_path / f"{again['dataId']}.json").read_text(encoding="utf-8"))

    assert second["guardResidue"]["namedAbsent"] == [CARD_GUARD]
    assert _entry(second["guardResidue"], CARD_GUARD)["state"] == lane.GUARD_ABSENT
    assert second["guardResidue"]["guardRows"] == 9
    assert lane.lane_failures(second) == []


def test_the_lane_census_transport_resolves_from_the_one_merged_document_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lane's own census transport is pinned to the support module's merged map, by identity and use.

    ``showAndSells`` joins the swept tables with the Stage 4 sweep rules and no Stage 2 document mints
    it, so a transport resolving names from ``stage2.STAGE_TWO_DOCUMENTS`` raises ``KeyError`` into the
    probe's exception guard and answers ``""`` for that table — the regression the round-1 review
    caught shipping unpinned. This drives ``lane.census_transport`` itself, not a copy of its lookup:
    every read name in :data:`STAGE_THREE_RESIDUE_READS` must send its Stage 2 or Stage 3 query text
    through the lane's real transport, which is the line that broke pre-fix.
    """
    assert lane.CENSUS_DOCUMENTS is stage3.STAGE_THREE_CENSUS_DOCUMENTS, (
        "the lane resolves census names from the support module's single merged map"
    )
    assert "showAndSells" not in stage2.STAGE_TWO_DOCUMENTS and "showAndSells" in stage3.STAGE_THREE_DOCUMENTS, (
        "the very name that broke pre-fix still comes only from the Stage 3 half"
    )

    sent: list[str] = []

    def fake_gql_raw(_admin: str, query: str, _variables: Mapping[str, Any]) -> Mapping[str, Any]:
        sent.append(query)
        return {"data": {}}

    monkeypatch.setattr(lane.api, "gql_raw", fake_gql_raw)
    transport = lane.census_transport("admin-token")
    for reads in stage3.STAGE_THREE_RESIDUE_READS.values():
        for document in reads:
            transport(document, {})
            query = sent[-1]
            assert query == lane.CENSUS_DOCUMENTS[document], f"the transport sent something other than {document}"
            assert document in query, f"{document} is not selected by its own query text"
    assert stage3.STAGE_THREE_DOCUMENTS["showAndSells"] in sent, "the Stage 3 half never reached the wire"
