"""The Stage 3 scenario runners (§3.6.2), executed against scripted answers.

:mod:`tests.unit.test_show_sell_stage3_support` proves what the Stage 3 layer *states*: the clock, the
fixture tree, the refusal table, the ICS validator, the SDL contract, the cleanup vocabulary.  This module
proves the half that *does* something, and it proves it by running the runners — every named acceptance id
here is a call that was actually sent, an answer that was actually compared, and a row that was actually
read back:

* ``SS-SM-05/06/11`` — every §3.6.2 collision goes through :func:`run_conflict_lane` and the scripted
  transport, and a collision that is *not* refused comes back as a finding (:func:`conflict_lane_problems`).
* ``API-FIX-03`` — :func:`run_stale_version_lane` reads a version, advances the row with a legal write at
  that version, and submits the version the read preceded; :func:`run_removed_member_lane` removes through
  the product's own mutation with the versions the roster read answered.
* ``SS-SM-05 step 4`` / ``SLOT-02-02`` / ``VER-01`` — :func:`run_race_barrier` rendezvouses two threads on
  a :class:`threading.Barrier`, and the arrival indexes it reports are the evidence it engaged.
* ``API-FIX-01`` — FINALIZED and REOPENED go through :func:`apply_state_fixture`, a conditioned
  ``UpdateItem`` the read-back confirms; a grant the fixture identity lacks returns ``blocked`` naming the
  ``dynamodb:`` action, never a quiet pass.
* ``CAL-01``/``CAL-02`` — :func:`validate_invite_captures` runs the validator over the captured bytes of
  ``buildInvite`` and rebuilds the UID from the documented DTO, so a hand-written ``.ics`` fails.
* lane cleanup — :func:`run_stage_three_cleanup` deletes, reads back, and proves another lane's canary
  survived.

Nothing here reaches AWS or an endpoint: the transports answer from a script and the DynamoDB stand-in is a
dict with a version condition.  That is the point — the same runner code a live lane executes is what CI
runs, and a fixture that would be blocked on the live stack says so here, in the open, rather than quietly
disappearing from the tree.
"""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import pytest

from src.utils import show_and_sell_models
from src.utils.errors import AppError
from tests.e2e.utils import show_sell_stage2_support as stage2
from tests.e2e.utils import show_sell_stage3_scenario as scenario
from tests.e2e.utils import show_sell_stage3_support as stage3

#: A scenario setup time, so the clock under test never reads the writer's machine clock.
T0 = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)

#: RFC 5545's own line limit — the bound the validator enforces, not the emitter's fold budget.
RFC_MAX_LINE_OCTETS = 75


def _clock(lane_id: str = "L02") -> stage3.ScenarioClock:
    """A clock built the way FIX-AC-03 hands one over, deterministic so payloads are checkable."""
    return stage3.ScenarioClock(
        t0=T0,
        run_id=f"{int(T0.timestamp())}-ff00aa",
        scenario_id="SS-SM-05",
        lane_id=lane_id,
        attempt_id="a9",
    )


def _fixture(clock: stage3.ScenarioClock) -> dict[str, Any]:
    return stage3.stage_three_fixture(clock)


def _ids(fixture: Mapping[str, Any], **overrides: str) -> dict[str, str]:
    """Every ref in the tree bound to a shaped id, so nothing in a payload is a placeholder."""
    answers = {ref: f"ID#{ref}" for ref in scenario.fixture_refs(fixture)}
    answers["account.admin"] = "ACCOUNT#fixture-admin"
    answers["actorAccount"] = "ACCOUNT#fixture-admin"
    answers["scope"] = "UNITCAMP#fixture"
    answers.update(overrides)
    return scenario.collect_lane_ids(fixture, answers)


def _pair(refusal: str) -> dict[str, object]:
    return next(row for row in stage3.STAGE_THREE_CONFLICT_PAIRS if row["refusal"] == refusal)


def _entry(fixture: Mapping[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in fixture["removedMembers"] if row["profile"] == f"profile.{name}")


# ---------------------------------------------------------------------------
# The scripted transport
# ---------------------------------------------------------------------------


class ScriptedApi:
    """A transport that answers from a script and keeps what the lane actually sent.

    The recorded calls are the assertion surface: a runner that claims to have sent a collision has to show
    the field name and the payload, and a script that runs out of answers fails the test rather than
    answering ``None`` and letting a step look like a refusal it never received.
    """

    def __init__(self, answers: Sequence[Mapping[str, Any]] = ()) -> None:
        self._answers: list[Mapping[str, Any]] = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        if not self._answers:
            raise AssertionError(f"the script has no answer left for {field}")
        self.calls.append((field, dict(variables)))
        return copy.deepcopy(self._answers.pop(0))

    def sent(self, field: str) -> dict[str, Any]:
        """The ``input`` the lane sent for ``field``, naming the calls when it sent none."""
        for name, variables in self.calls:
            if name == field and isinstance(variables.get("input"), Mapping):
                return dict(variables["input"])
        raise AssertionError(f"the lane never sent {field}; it sent {[name for name, _ in self.calls]}")

    @property
    def fields(self) -> list[str]:
        return [name for name, _ in self.calls]


def _refusal_body(refusal: str) -> dict[str, Any]:
    """The answer the refusal table records for ``refusal``, in the decorated-Lambda error shape."""
    answer = stage3.stage_three_refusal(refusal)
    message = f"{answer['sentence']}refused by the scripted answer for {answer['subcode'] or answer['code']}"
    return {"errors": [{"message": message, "extensions": {"code": answer["code"], "errorCode": answer["code"]}}]}


def _success_body(field: str, payload: Any = True) -> dict[str, Any]:
    return {"data": {field: payload}}


def _roster_body(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"data": {"roster": {"items": [dict(row) for row in rows]}}}


# ---------------------------------------------------------------------------
# SS-SM-05 / SS-SM-06 / SS-SM-11: every named collision is a call and a comparison
# ---------------------------------------------------------------------------


def test_every_conflict_pair_is_a_call_the_lane_sent_and_a_refusal_it_compared() -> None:
    """The table is executable: 20 §3.6.2 collisions, 20 calls, 20 answers compared to the table."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    pairs = stage3.STAGE_THREE_CONFLICT_PAIRS
    api = ScriptedApi([_refusal_body(str(row["refusal"])) for row in pairs])
    verdicts = scenario.run_conflict_lane(api, clock, ids)
    assert len(pairs) == 20
    assert [verdict.refusal for verdict in verdicts] == [str(row["refusal"]) for row in pairs]
    assert [verdict.result for verdict in verdicts] == [scenario.RESULT_REFUSED] * len(pairs)
    assert scenario.conflict_lane_problems(verdicts) == []
    assert [verdict.field for verdict in verdicts] == [str(row["op"]) for row in pairs]
    assert api.fields == [verdict.field for verdict in verdicts], "a verdict with no call behind it is a claim"


def test_the_named_walkthrough_ids_are_carried_by_the_verdicts_they_evidence() -> None:
    """Each id this card is gated on appears on the verdict that runs its collision."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    wanted = {
        "concurrent-over-assignment": "SS-SM-05 step 4",
        "duplicate-signup": "SS-SM-06 step 3",
        "cancel-started-event": "SS-SM-11 step 5",
        "stale-event-version": "API-FIX-03",
    }
    api = ScriptedApi([_refusal_body(name) for name in wanted])
    verdicts = scenario.run_conflict_lane(api, clock, ids, pairs=[_pair(name) for name in wanted])
    by_name = {verdict.refusal: verdict for verdict in verdicts}
    assert scenario.conflict_lane_problems(verdicts) == []
    for refusal, acceptance in wanted.items():
        assert acceptance in by_name[refusal].acceptance, refusal


def test_a_collision_that_is_not_refused_is_a_finding_not_a_pass() -> None:
    """The check is not satisfied by the table: a write that lands fails every id that collision carries."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    payload = {"showAndSellId": ids["event.four-box.overlap"]}
    api = ScriptedApi([_success_body("assignShowAndSellInventory", payload)])
    verdicts = scenario.run_conflict_lane(api, clock, ids, pairs=[_pair("concurrent-over-assignment")])
    assert verdicts[0].result == scenario.RESULT_NOT_REFUSED
    problems = scenario.conflict_lane_problems(verdicts)
    assert any("SS-SM-05 step 4" in problem for problem in problems), problems
    assert any("ALLOC-02" in problem for problem in problems), problems
    assert any("expected CONFLICT" in problem for problem in problems), problems


def test_a_refusal_with_the_wrong_code_is_named_against_the_table() -> None:
    """A ``FORBIDDEN`` where the table promises ``CONFLICT`` is reported, not rounded to a refusal."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    body = {"errors": [{"message": "not your event", "extensions": {"code": "FORBIDDEN"}}]}
    verdicts = scenario.run_conflict_lane(ScriptedApi([body]), clock, ids, pairs=[_pair("capacity-full")])
    problems = scenario.conflict_lane_problems(verdicts)
    assert any("expected CONFLICT" in problem for problem in problems), problems
    assert any("This slot is full: " in problem for problem in problems), problems


def test_a_table_row_with_no_executable_call_is_named_rather_than_skipped() -> None:
    """A collision the runner cannot build is a hole in the lane, not a row nobody had to run."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    row = stage3.conflict_row("signupScoutForShowAndSellSlot", "idempotency-replayed")
    api = ScriptedApi()
    verdicts = scenario.run_conflict_lane(api, clock, ids, pairs=[row])
    assert verdicts[0].result == scenario.RESULT_NO_CALL
    assert any("builds no call" in problem for problem in scenario.conflict_lane_problems(verdicts))
    assert api.calls == []


def test_the_conflict_lane_sends_bound_ids_one_idempotency_key_per_step() -> None:
    """No payload carries a ``<placeholder>``, and no two collisions share a key."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    pairs = stage3.STAGE_THREE_CONFLICT_PAIRS
    api = ScriptedApi([_refusal_body(str(row["refusal"])) for row in pairs])
    scenario.run_conflict_lane(api, clock, ids)
    keys = [dict(variables)["input"]["idempotency"]["idempotencyKey"] for _field, variables in api.calls]
    assert len(keys) == len(pairs)
    assert len(set(keys)) == len(keys), "two collisions sharing an idempotency key is one collision"
    signup = api.sent("signupScoutForShowAndSellSlot")
    assert signup["showAndSellId"] == ids["event.future"]
    assert signup["slotId"] == ids["slot.first-sales"]
    assert signup["profileId"] == ids["profile.avery"]
    assert signup["campaignId"] == ids["campaign.avery"]
    assert "version" not in signup, "SignupScoutForShowAndSellSlotInput carries no version"
    assert "<" not in json.dumps([dict(variables) for _field, variables in api.calls])


# ---------------------------------------------------------------------------
# API-FIX-03: the stale-version fixture, built by reading and advancing — not by editing an expectation
# ---------------------------------------------------------------------------


def test_api_fix_03_submits_the_version_the_read_answered_after_the_row_moved_past_it() -> None:
    """Read 7, advance the row at 7, then submit 7: the stale fixture is built and the refusal measured."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    api = ScriptedApi(
        [
            {"data": {"showAndSell": {"showAndSellId": ids["event.future"], "version": 7}}},
            _success_body("upsertShowAndSellSlot", {"slotId": "SLOT#advanced"}),
            _refusal_body("stale-event-version"),
        ]
    )
    steps = scenario.run_stale_version_lane(api, clock, ids)
    assert [step.step for step in steps] == ["read-version", "advance-version", "submit-stale"]
    assert scenario.stale_version_problems(steps) == []
    assert steps[0].detail == "version 7"
    assert api.sent("upsertShowAndSellSlot")["version"] == {"expectedVersion": 7}, "the advance lands at 7"
    stale = api.sent("deleteShowAndSellSlot")
    assert stale["version"] == {"expectedVersion": 7}, "the submit carries the version the read preceded"
    assert stale["slotId"] == ids["slot.midday"]
    assert api.fields == ["showAndSell", "upsertShowAndSellSlot", "deleteShowAndSellSlot"]


def test_api_fix_03_a_read_that_answers_no_version_blocks_the_scenario_before_any_write() -> None:
    """API-FIX-01: a fixture that cannot be built blocks the lane, and no write is guessed."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    missing = {"data": {"showAndSell": None}, "errors": [{"message": "not found", "extensions": {"code": "NOT_FOUND"}}]}
    api = ScriptedApi([missing])
    steps = scenario.run_stale_version_lane(api, clock, ids)
    assert [step.result for step in steps] == [scenario.STEP_BLOCKED]
    assert scenario.stale_version_problems(steps)
    assert api.fields == ["showAndSell"], "the lane may not advance or submit a version it never read"


def test_api_fix_03_a_stale_submit_that_lands_fails_the_lane() -> None:
    """If the server took the stale version, the fixture found a bug — and says so."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    api = ScriptedApi(
        [
            {"data": {"showAndSell": {"showAndSellId": ids["event.future"], "version": 7}}},
            _success_body("upsertShowAndSellSlot", {"slotId": "SLOT#advanced"}),
            _success_body("deleteShowAndSellSlot", True),
        ]
    )
    steps = scenario.run_stale_version_lane(api, clock, ids)
    assert steps[-1].step == "submit-stale" and steps[-1].result == scenario.STEP_FAILED
    assert any("stale-event-version" in problem for problem in scenario.stale_version_problems(steps))


def test_api_fix_03_an_advancing_write_that_is_refused_is_named_not_retried() -> None:
    """The fixture cannot be built past a refused advance, and it does not quietly change the version."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    api = ScriptedApi(
        [
            {"data": {"showAndSell": {"showAndSellId": ids["event.future"], "version": 7}}},
            _refusal_body("stale-event-version"),
        ]
    )
    steps = scenario.run_stale_version_lane(api, clock, ids)
    assert [step.step for step in steps] == ["advance-version"]
    assert steps[0].result == scenario.STEP_FAILED
    assert api.fields == ["showAndSell", "upsertShowAndSellSlot"], "no stale submit after a refused advance"


# ---------------------------------------------------------------------------
# The removed-member fixture: the product's own mutation, with the versions the roster read answered
# ---------------------------------------------------------------------------


def test_the_removed_member_lane_removes_with_the_product_mutation_conditions_on_what_it_read() -> None:
    """SS-SM-06 step 7 / SIGN-M-01-03: roster read, removal, roster read, refused signup."""
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    entry = _entry(fixture, "devon")
    joined = [{"profileId": ids["profile.devon"], "status": "ACTIVE", "version": 4, "guardVersion": 2}]
    removed = [{"profileId": ids["profile.devon"], "status": "REMOVED", "version": 5, "guardVersion": 3}]
    api = ScriptedApi(
        [
            _roster_body(joined),
            _success_body("removeUnitCampaignMembership", {"status": "REMOVED"}),
            _roster_body(removed),
            _refusal_body("removed-member-signup"),
        ]
    )
    steps = scenario.run_removed_member_lane(api, clock, ids, entry)
    assert [step.step for step in steps] == ["roster-before", "remove", "roster-after", "signup-after"]
    assert scenario.removed_member_problems(steps) == []
    removal = api.sent("removeUnitCampaignMembership")
    assert removal["expectedMembershipVersion"] == 4, "the version came from the roster read, not a literal"
    assert removal["expectedGuardVersion"] == 2
    assert removal["campaignId"] == ids["campaign.devon"]
    assert api.fields.count("roster") == 2, "the removal must be bracketed by roster reads"
    assert api.sent("signupScoutForShowAndSellSlot")["profileId"] == ids["profile.devon"]


def test_the_removed_member_fixture_reaches_the_signup_only_after_the_roster_says_removed() -> None:
    """A roster that still answers ACTIVE after the removal stops the fixture at that step."""
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    entry = _entry(fixture, "devon")
    joined = [{"profileId": ids["profile.devon"], "status": "ACTIVE", "version": 4, "guardVersion": 2}]
    api = ScriptedApi(
        [
            _roster_body(joined),
            _success_body("removeUnitCampaignMembership", {"status": "ACTIVE"}),
            _roster_body(joined),
        ]
    )
    steps = scenario.run_removed_member_lane(api, clock, ids, entry)
    assert [step.step for step in steps] == ["roster-before", "remove", "roster-after"]
    assert steps[-1].result == scenario.STEP_FAILED
    assert api.fields == ["roster", "removeUnitCampaignMembership", "roster"]
    assert any("roster-after" in problem for problem in scenario.removed_member_problems(steps))


def test_the_unjoined_scout_is_not_found_and_the_roster_was_read_first() -> None:
    """SLOT-03 / SS-SM-06 step 7's Emery: absent from the roster, and the signup earns ``NOT_FOUND``."""
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    entry = _entry(fixture, "emery")
    api = ScriptedApi([_roster_body([]), _refusal_body("unjoined-scout-signup")])
    steps = scenario.run_removed_member_lane(api, clock, ids, entry)
    assert [step.step for step in steps] == ["roster-before", "signup-after"]
    assert scenario.removed_member_problems(steps) == []
    assert api.fields == ["roster", "signupScoutForShowAndSellSlot"]
    assert api.sent("signupScoutForShowAndSellSlot")["profileId"] == ids["profile.emery"]


def test_a_roster_that_answers_nothing_for_a_member_blocks_the_fixture() -> None:
    """No version to condition on means no removal: blocked, and nothing was written."""
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    entry = _entry(fixture, "devon")
    api = ScriptedApi([_roster_body([])])
    steps = scenario.run_removed_member_lane(api, clock, ids, entry)
    assert [step.result for step in steps] == [scenario.STEP_BLOCKED]
    assert api.fields == ["roster"]
    assert scenario.removed_member_problems(steps)


def test_a_signup_the_removed_member_is_allowed_fails_the_lane() -> None:
    """The step after the removal is the assertion: an accepted signup is a finding, not a pass."""
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    entry = _entry(fixture, "devon")
    joined = [{"profileId": ids["profile.devon"], "status": "ACTIVE", "version": 4, "guardVersion": 2}]
    removed = [{"profileId": ids["profile.devon"], "status": "REMOVED", "version": 5, "guardVersion": 3}]
    api = ScriptedApi(
        [
            _roster_body(joined),
            _success_body("removeUnitCampaignMembership", {"status": "REMOVED"}),
            _roster_body(removed),
            _success_body("signupScoutForShowAndSellSlot", {"slotId": ids["slot.first-sales"]}),
        ]
    )
    steps = scenario.run_removed_member_lane(api, clock, ids, entry)
    assert steps[-1].step == "signup-after" and steps[-1].result == scenario.STEP_FAILED
    assert any("removed-member-signup" in problem for problem in scenario.removed_member_problems(steps))


# ---------------------------------------------------------------------------
# Race barriers: a measured rendezvous, not a story about ordering
# ---------------------------------------------------------------------------


class LastPlaceServer:
    """A slot with one place left: the first write lands, every later one earns the recorded refusal.

    The race is decided by a lock, so which thread wins is genuinely unknown before the barrier opens —
    which is the property ``SS-SM-05 step 4`` and ``SLOT-02-02`` are gated on.
    """

    def __init__(self, refusal: str) -> None:
        self._refusal = refusal
        self._lock = threading.Lock()
        self._taken = False
        self.calls = 0

    def __call__(self, field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        del variables
        with self._lock:
            self.calls += 1
            if self._taken:
                return _refusal_body(self._refusal)
            self._taken = True
            return _success_body(field)


def test_the_capacity_race_lands_exactly_one_signup_and_shows_the_rendezvous() -> None:
    """SLOT-02-02: two threads meet on the barrier, one place, one refusal, arrival indexes as proof."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    server = LastPlaceServer("capacity-full")
    calls = scenario.RACE_BARRIER_CALLS["capacity"](clock, ids)
    result = scenario.run_race_barrier([server, server], calls, refusal="capacity-full")
    assert result["violations"] == []
    assert sorted(result["arrivals"]) == [0, 1], "the barrier never rendezvoused both threads"
    assert len(result["succeeded"]) == 1 and len(result["refused"]) == 1
    assert server.calls == 2, "a thread that never sent a write cannot lose a race"
    profiles = [str(call[1]["input"]["profileId"]) for call in calls]
    assert len(set(profiles)) == 2, "the capacity race has to be two different Scouts"


def test_the_allocation_race_refuses_the_loser_and_saves_nothing_partial() -> None:
    """SS-SM-05 step 4: both four-box writes pass validation, one write plan wins, the other is refused."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    server = LastPlaceServer("concurrent-over-assignment")
    calls = scenario.RACE_BARRIER_CALLS["allocation"](clock, ids)
    result = scenario.run_race_barrier([server, server], calls, refusal="concurrent-over-assignment")
    assert result["violations"] == []
    assert len(result["succeeded"]) == 1
    events = {str(call[1]["input"]["showAndSellId"]) for call in calls}
    assert events == {ids["event.four-box.morning"], ids["event.four-box.afternoon"]}
    assert result["answers"].count(None) == 0, "both threads answered; a silent thread is not a race"


def test_a_race_where_every_write_lands_is_a_violation() -> None:
    """Two successes means the server had no exclusion at all, and the barrier says so."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    calls = scenario.RACE_BARRIER_CALLS["version"](clock, ids)
    servers = [ScriptedApi([_success_body("updateShowAndSell", {"version": 2})]) for _call in calls]
    result = scenario.run_race_barrier(servers, calls, refusal="stale-event-version")
    assert any("exactly one write" in problem for problem in result["violations"]), result["violations"]
    assert len(result["succeeded"]) == 2


def test_a_race_thread_that_never_answers_is_named() -> None:
    """A transport that raises leaves a write with no answer, which is not a lost race."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    calls = scenario.RACE_BARRIER_CALLS["capacity"](clock, ids)

    def raise_transport(field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        raise RuntimeError(f"{field} never reached the endpoint")

    runners = [raise_transport, ScriptedApi([_refusal_body("capacity-full")])]
    result = scenario.run_race_barrier(runners, calls, refusal="capacity-full")
    assert any("never answered" in problem for problem in result["violations"]), result["violations"]


def test_a_barrier_needs_one_transport_per_write() -> None:
    """A race with a thread missing is a mistake in the lane, refused before any thread starts."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    calls = scenario.RACE_BARRIER_CALLS["capacity"](clock, ids)
    with pytest.raises(ValueError, match="one transport per write"):
        scenario.run_race_barrier([ScriptedApi()], calls, refusal="capacity-full")


# ---------------------------------------------------------------------------
# Lane cleanup: plan, delete, read back, and prove another lane's row survived
# ---------------------------------------------------------------------------


class AccessDeniedException(RuntimeError):
    """The shape a missing IAM grant arrives in, so ``blocked`` can name the action."""


class ConditionalCheckFailed(Exception):
    """The version condition did not hold."""


class ScriptedDynamo:
    """A DynamoDB stand-in with the three calls the lane makes, a version condition, and memory.

    Every call is recorded in order, which is how these tests check the rule a ``delete_item`` return value
    cannot give: each delete has to be followed by a ``get_item`` of the same key.  Seeded rows are
    ``{"table": ..., "key": {...}, "item": {...}}`` — the address the lane must use and the row it finds.
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]] = (),
        *,
        deny: str = "",
        left_behind: tuple[Mapping[str, Any], ...] = (),
        ignore_update: bool = False,
    ) -> None:
        self._rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for entry in rows:
            self._rows[self._address(entry)] = dict(entry.get("item") or {"entityType": "seeded"})
        self._deny = deny
        self._left_behind = {self._address(row) for row in left_behind}
        self._ignore_update = ignore_update
        self.deleted: list[tuple[str, str, str]] = []
        self.reads: list[tuple[str, str, str]] = []
        self.updated: list[dict[str, Any]] = []

    @staticmethod
    def _address(keyed: Mapping[str, Any]) -> tuple[str, str, str]:
        key = dict(keyed["key"])
        return (str(keyed["table"]), str(key["pk"]), str(key["sk"]))

    @staticmethod
    def _wire(key: Mapping[str, Any]) -> tuple[str, str]:
        return (str(key["pk"]["S"]), str(key["sk"]["S"]))

    def row_at(self, keyed: Mapping[str, Any]) -> dict[str, Any] | None:
        """The stored row at one address, or ``None`` when the table answers nothing."""
        return self._rows.get(self._address(keyed))

    def delete_item(self, **call: Any) -> None:
        address = (call["TableName"], *self._wire(call["Key"]))
        if self._deny == "DeleteItem":
            raise AccessDeniedException("User is not authorized to perform: action dynamodb:DeleteItem")
        self.deleted.append(address)
        if address not in self._left_behind:
            self._rows.pop(address, None)

    def get_item(self, **call: Any) -> dict[str, Any]:
        address = (call["TableName"], *self._wire(call["Key"]))
        if self._deny == "GetItem":
            raise AccessDeniedException("User is not authorized to perform: action dynamodb:GetItem")
        self.reads.append(address)
        found = self._rows.get(address)
        return {"Item": dict(found)} if found else {}

    def update_item(self, **call: Any) -> None:
        address = (call["TableName"], *self._wire(call["Key"]))
        if self._deny == "UpdateItem":
            raise AccessDeniedException("User is not authorized to perform: action dynamodb:UpdateItem")
        self.updated.append(dict(call))
        row = self._rows.get(address)
        if row is None:
            raise ConditionalCheckFailed("no row to condition on")
        names, values = call["ExpressionAttributeNames"], call["ExpressionAttributeValues"]
        condition, _, expected = str(call["ConditionExpression"]).partition(" = ")
        if row.get(names[condition]) != int(values[expected]["N"]):
            raise ConditionalCheckFailed(f"the row is not at version {values[expected]['N']}")
        if self._ignore_update:
            return
        for clause in str(call["UpdateExpression"]).removeprefix("SET ").split(", "):
            name, _, value = clause.partition(" = ")
            row[names[name]] = _plain(values[value])


def _plain(value: Any) -> Any:
    """One AttributeValue in the plain shape the model reads its rows in."""
    if isinstance(value, Mapping):
        if "NULL" in value:
            return None
        if "N" in value:
            return int(value["N"])
        if "S" in value:
            return str(value["S"])
    return value


def _plan(clock: stage3.ScenarioClock, fixture: Mapping[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    return stage3.stage_three_cleanup_plan(clock, fixture, **kwargs)


def _seeds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A stored row for every planned key, so the scripted table starts where the lane left it."""
    return [{"table": row["table"], "key": dict(row["key"]), "item": {"entityType": row["kind"]}} for row in rows]


def _canary() -> dict[str, Any]:
    return stage3.stage_three_cleanup_canary(stage3.lane_token(9001))


def test_the_cleanup_run_reads_back_every_row_it_deleted() -> None:
    """A delete that returned is not evidence: every planned key is deleted and then read again."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] != "sweep"]
    canary = _canary()
    client = ScriptedDynamo(_seeds([*plan, canary]))
    sweep = stage2.cleanup_row("§2.8.7", "typed-token sweep removed what the writes missed")
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=canary, sweep_row=sweep)
    assert stage2.cleanup_problems(rows) == []
    assert stage2.cleanup_failures(rows) == []
    assert len(rows) == len(plan) + 1
    assert client.deleted == [(row["table"], row["key"]["pk"], row["key"]["sk"]) for row in plan]
    for index, planned in enumerate(plan):
        assert client.reads[index] == client.deleted[index], f"no read-back after the {planned['kind']} delete"
    assert client.reads[-1] == (canary["table"], canary["key"]["pk"], canary["key"]["sk"])
    assert all(client.row_at(seed) is None for seed in _seeds(plan)), "every lane row is gone on read-back"


def test_a_delete_that_returned_without_removing_the_row_is_a_failed_row() -> None:
    """The read-back is what makes teardown trustworthy: a row that survives is reported, not counted."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "event"][:3]
    client = ScriptedDynamo(_seeds([*plan, _canary()]), left_behind=(plan[1],))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=_canary())
    failed = [row for row in rows if row["result"] == stage2.CLEANUP_FAILED]
    assert len(failed) == 1
    assert "still there after delete_item returned" in failed[0]["summary"]
    assert len(client.deleted) == len(plan), "the delete was sent; it is the read-back that found the row"
    assert client.row_at(plan[1]) is not None


def test_a_lane_never_deletes_a_row_another_lane_token_owns() -> None:
    """Naming a row is not owning it: the refusal happens before the delete, and the row is still there."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "signup"][:2]
    plan[1] = dict(plan[1], lane=stage3.lane_token(9002))
    client = ScriptedDynamo(_seeds([*plan, _canary()]))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=_canary())
    assert len(client.deleted) == 1
    assert client.row_at(plan[1]) is not None, "the other lane's row has to still be there"
    failures = stage2.cleanup_failures(rows)
    assert any("owned by lane" in failure for failure in failures), failures


def test_an_unbound_lane_blocks_its_deletes_instead_of_guessing_a_key() -> None:
    """Every key still holds a ``<placeholder>``, so nothing is deleted and the lane says blocked."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture) if row["kind"] != "sweep"]
    canary = _canary()
    client = ScriptedDynamo(_seeds([canary]))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=canary)
    assert client.deleted == []
    assert {row["result"] for row in rows if row["acceptance"] != canary["acceptance"]} == {stage2.CLEANUP_BLOCKED}
    assert any("never bound to an id" in row["summary"] for row in rows)


def test_a_denied_delete_reports_blocked_naming_the_action() -> None:
    """An IAM gap is an owner decision, and the row names the action instead of an empty table."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "slot"][:2]
    client = ScriptedDynamo(_seeds([*plan, _canary()]), deny="DeleteItem")
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=_canary())
    blocked = stage2.cleanup_blocked(rows)
    assert len(blocked) == 2
    assert all("dynamodb:DeleteItem" in line for line in blocked), blocked


def test_the_canary_has_to_be_another_lanes_row_and_still_present() -> None:
    """Both halves: a canary this lane owns proves nothing, and a canary that is gone is a teardown bug."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "marker"][:1]
    owned = stage3.stage_three_cleanup_canary(clock.token)
    client = ScriptedDynamo(_seeds(plan))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=owned)
    assert any("different lane token" in failure for failure in stage2.cleanup_failures(rows))
    bare = ScriptedDynamo(_seeds(plan))
    rows = scenario.run_stage_three_cleanup(bare, lane=clock.token, plan=plan, canary=_canary())
    assert any("reached outside its own rows" in failure for failure in stage2.cleanup_failures(rows))


def test_a_sweep_that_has_not_been_run_keeps_cleanup_blocked() -> None:
    """The typed-token sweep is part of cleanup: not run, and the lane is blocked, not clean."""
    clock = _clock()
    fixture = _fixture(clock)
    sweep_rows = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "sweep"]
    assert len(sweep_rows) == 1
    client = ScriptedDynamo(_seeds([_canary()]))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=sweep_rows, canary=_canary())
    assert [row["result"] for row in rows] == [stage2.CLEANUP_BLOCKED, stage2.CLEANUP_OBSERVED]
    assert "typed-token sweep has not been run" in rows[0]["summary"]
    assert client.deleted == []


# ---------------------------------------------------------------------------
# API-FIX-01: FINALIZED and REOPENED as an explicit, read-back fixture builder
# ---------------------------------------------------------------------------


def _stored_event(
    clock: stage3.ScenarioClock,
    ids: Mapping[str, str],
    event_ref: str,
    *,
    version: int,
    status: str = show_and_sell_models.STATUS_SCHEDULED,
    approved: str | None = None,
) -> dict[str, Any]:
    """The row the lane's own ``createShowAndSell`` wrote, addressable the way the table holds it.

    The row is built by the model — the same builder the create path uses — and a stored state is then
    applied as a pair, exactly the way the §3.4 writer does it: ``FINALIZED`` only ever arrives together
    with ``approvedFinalizationId``, and ``REOPENED`` only ever arrives with it cleared.  Building an
    illegal seed would test a row that cannot exist.
    """
    row = show_and_sell_models.build_show_and_sell_item(
        show_and_sell_id=ids[f"event.{event_ref}"],
        unit_id=ids["unit"],
        unit_campaign_id=ids["unit-campaign"],
        location_name=f"Fixture {event_ref} {clock.data_id}",
        start_at=clock.iso(days=-1),
        end_at=clock.iso(days=-1, hours=3),
        created_by_account_id=ids["account.admin"],
        now_iso=clock.iso(),
        version=version,
    )
    row[show_and_sell_models.STATUS_ATTRIBUTE] = status
    row[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] = approved
    assert show_and_sell_models.event_invariant_violations(row) == [], "the seed row is not a legal event row"
    return {"table": scenario.STATE_FIXTURE_TABLE, "key": {"pk": row["pk"], "sk": row["sk"]}, "item": row}


def test_api_fix_01_finalized_is_a_builder_fixture_the_read_back_confirms() -> None:
    """The FINALIZED fixture is a conditioned update of the created row, proven by reading it back."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    assert plan["state"] == show_and_sell_models.STATUS_FINALIZED
    assert plan["table"] == scenario.STATE_FIXTURE_TABLE == stage3.show_and_sells_table()
    assert plan["requiredActions"] == scenario.STATE_FIXTURE_REQUIRED_ACTIONS
    assert plan["changes"][show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE]
    assert plan["note"] == stage3.BUILDER_ONLY_STATE_FIXTURE_NOTE
    read_version = plan["conditionVersion"]
    seed = _stored_event(clock, ids, "finalized", version=read_version)
    client = ScriptedDynamo([seed])
    before: list[Mapping[str, Any]] = []
    verdict = scenario.apply_state_fixture(client, plan, on_read=before.append)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    assert "documented Stage 3 fixture builder" in verdict["summary"]
    assert before[0][show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_SCHEDULED
    assert client.updated[0]["ConditionExpression"] == "#version = :expected"
    assert client.updated[0]["ExpressionAttributeValues"][":expected"] == {"N": str(read_version)}
    after = client.row_at(seed)
    assert after is not None
    assert after[show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_FINALIZED
    assert show_and_sell_models.event_invariant_violations(after) == []


def test_api_fix_01_the_builder_touches_the_event_row_and_writes_no_finalization_row() -> None:
    """The fixture changes the row ``createShowAndSell`` wrote and nothing else: no ``FINALIZATION#`` row."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    event_key = (plan["table"], plan["key"]["pk"], plan["key"]["sk"])
    touched = set(client.reads) | {(call["TableName"], *ScriptedDynamo._wire(call["Key"])) for call in client.updated}
    assert touched == {event_key}, "the fixture may touch the event row it was given and nothing else"
    assert client.deleted == []
    assert set(plan["changes"]) == {
        show_and_sell_models.STATUS_ATTRIBUTE,
        show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE,
        show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE,
        show_and_sell_models.VERSION_ATTRIBUTE,
        show_and_sell_models.UPDATED_AT_ATTRIBUTE,
    }, "a state fixture that rewrites the interval or the identity is a different row, not a state"


def test_api_fix_01_reopened_clears_the_pointer_the_model_refuses() -> None:
    """§5.10 refuses a REOPENED row that still points at an approved finalization, so the builder clears it."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.reopen_event_fixture_writes(clock, ids)
    assert plan["state"] == show_and_sell_models.STATUS_REOPENED
    assert plan["changes"][show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] is None
    seed = _stored_event(
        clock,
        ids,
        "reopened",
        version=plan["conditionVersion"],
        status=show_and_sell_models.STATUS_FINALIZED,
        approved=f"FINAL#{clock.token}-finalized",
    )
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    after = client.row_at(seed)
    assert after is not None and show_and_sell_models.event_invariant_violations(after) == []
    uncleared = dict(after, status=show_and_sell_models.STATUS_REOPENED, approvedFinalizationId="FINAL#kept")
    problems = show_and_sell_models.event_invariant_violations(uncleared)
    assert any("approvedFinalizationId cleared" in problem for problem in problems), problems


def test_api_fix_01_a_denied_read_reports_blocked_naming_the_action() -> None:
    """``kernelworx-qa-ue1-dev`` cannot read that row: the fixture is blocked, and the grant is named."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    client = ScriptedDynamo([seed], deny="GetItem")
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_BLOCKED
    assert "dynamodb:GetItem" in verdict["summary"]
    assert client.updated == [], "a denied read stops the fixture before any write"


def test_api_fix_01_a_missing_row_or_a_stale_condition_is_a_failed_fixture() -> None:
    """No row to transition, and a version condition that did not hold, are both failures."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    assert "no event row to transition" in scenario.apply_state_fixture(ScriptedDynamo(), plan)["summary"]
    raced = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"] + 5)
    verdict = scenario.apply_state_fixture(ScriptedDynamo([raced]), plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert "ConditionalCheckFailed" in verdict["summary"]


def test_api_fix_01_a_read_back_that_still_answers_the_old_status_is_not_a_fixture() -> None:
    """An update that was accepted but did not land is caught by the read-back, not assumed."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    client = ScriptedDynamo([seed], ignore_update=True)
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert "read-back status" in verdict["summary"]


def test_the_state_builder_refuses_an_id_the_lane_never_minted() -> None:
    """The builder builds the row through the model, so an illegal id fails before any DynamoDB call."""
    clock = _clock()
    ids = _ids(_fixture(clock), **{"event.finalized": "SSE#"})
    with pytest.raises(AppError):
        scenario.finalize_event_fixture_writes(clock, ids)


# ---------------------------------------------------------------------------
# CAL-01 / CAL-02: the captures are the emitter's bytes, and the validator runs over them
# ---------------------------------------------------------------------------


def test_the_two_captures_are_one_signup_downloaded_twice_and_the_uid_survived() -> None:
    """CAL-01's stable UID and CAL-02's UTC shape, checked against the bytes the browser wrote."""
    report = scenario.validate_invite_captures()
    assert scenario.invite_capture_names() == stage3.ICS_CAPTURE_NAMES
    assert report["first"] == (), report["first"]
    assert report["repeat"] == (), report["repeat"]
    assert report["uid"] == report["expectedUid"]
    assert report["uidStable"] and report["uidMatchesDto"]
    assert report["dtstampsMatchClocks"]
    assert report["maxPhysicalOctets"] == stage3.ICS_FOLD_OCTETS + 1
    assert report["maxPhysicalOctets"] <= RFC_MAX_LINE_OCTETS


def test_a_capture_that_is_not_the_documented_pair_fails_the_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plausible ``.ics`` nobody downloaded is caught: the UID has to be the DTO's own identity."""
    first_name, repeat_name = scenario.invite_capture_names()
    first = scenario.read_invite_capture(first_name)
    repeat = scenario.read_invite_capture(repeat_name)
    tampered = repeat.replace("-PROFILE#avery-scout@", "-PROFILE#blake-scout@", 1)
    assert tampered != repeat, "the capture pair moved, so this tamper no longer names a UID segment"

    def scripted(name: str) -> str:
        return tampered if name == repeat_name else first

    monkeypatch.setattr(scenario, "read_invite_capture", scripted)
    report = scenario.validate_invite_captures()
    assert report["uidStable"] is False
    assert report["uidMatchesDto"] is False
    assert report["repeat"] != ()


def test_an_unbound_lane_names_the_refs_it_cannot_identify() -> None:
    """API-FIX-01's other half: a fixture the lane cannot name blocks it, and no key is guessed."""
    clock = _clock()
    fixture = _fixture(clock)
    refs = scenario.fixture_refs(fixture)
    assert scenario.unbound_refs(fixture, {}) == refs
    bound = _ids(fixture)
    assert scenario.unbound_refs(fixture, bound) == ()
    assert scenario.lane_id(bound, "unit") == bound["unit"]
    assert scenario.lane_id({}, "unit") == "<unit>"
    assert scenario.unbound_key_cells({"pk": "IDEM#<actorAccount>#upsertShowAndSellSlot", "sk": "ok"}) == ("pk",)
    assert scenario.wire_key({"pk": "SSE#1", "sk": "METADATA"}) == {"pk": {"S": "SSE#1"}, "sk": {"S": "METADATA"}}
