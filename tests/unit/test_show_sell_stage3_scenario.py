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

from scripts import qa_fixture
from src.utils import mutations, show_and_sell_models
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
    answers["unit-campaign"] = answers["unit-campaign"]
    for name in fixture["profiles"]:
        answers[f"account.{name}"] = f"ACCOUNT#{name}"
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


class OutcomeServer:
    """A stack that answers one thread: the write lands, or the recorded refusal does.

    :class:`LastPlaceServer` decides by arrival order; this one decides by which thread the lane named,
    because the winner of a race is not always the thread that arrived first and a lane that assumed which
    side won would clean the wrong Scout's marker.
    """

    def __init__(self, *, accepted: bool, refusal: str) -> None:
        self._accepted = accepted
        self._refusal = refusal
        self.calls = 0

    def __call__(self, field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        del variables
        self.calls += 1
        return _success_body(field) if self._accepted else _refusal_body(self._refusal)


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
    """A DynamoDB stand-in that speaks wire form, which is what a low-level client answers.

    Rows are stored as ``AttributeValue`` mappings, ``get_item`` answers ``{"Item": {...wire...}}``, and
    ``update_item`` receives wire ``ExpressionAttributeValues``.  That is deliberate: a fake holding plain
    Python values hides the encode/decode boundary the fixture has to get right, and a status comparison
    against ``{"S": "FINALIZED"}`` never matches — the bug the reviewer's probe found.  Every call is
    recorded in order, which is how these tests check the rule a ``delete_item`` return value cannot give:
    each delete has to be followed by a consistent ``get_item`` of the same key.  Seeded rows are
    ``{"table": ..., "key": {...}, "item": {...}}`` — the address the lane must use, and the row in the
    plain shape the model builds it in, which the fake then encodes the way the client would.
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
            item = dict(entry.get("item") or {"entityType": "seeded"})
            self._rows[self._address(entry)] = {name: _wire(value) for name, value in item.items()}
        self._deny = deny
        self._left_behind = {self._address(row) for row in left_behind}
        self._ignore_update = ignore_update
        self.deleted: list[tuple[str, str, str]] = []
        self.deleted_calls: list[dict[str, Any]] = []
        self.reads: list[tuple[str, str, str]] = []
        self.read_calls: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    @staticmethod
    def _address(keyed: Mapping[str, Any]) -> tuple[str, str, str]:
        key = dict(keyed["key"])
        return (str(keyed["table"]), str(key["pk"]), str(key["sk"]))

    @staticmethod
    def _wire(key: Mapping[str, Any]) -> tuple[str, str]:
        return (str(key["pk"]["S"]), str(key["sk"]["S"]))

    def row_at(self, keyed: Mapping[str, Any]) -> dict[str, Any] | None:
        """The stored row at one address, decoded to the plain shape the model works in."""
        stored = self._rows.get(self._address(keyed))
        return None if stored is None else {name: _plain(value) for name, value in stored.items()}

    def wire_at(self, keyed: Mapping[str, Any]) -> dict[str, Any] | None:
        """The stored row in the ``AttributeValue`` shape a low-level client answers with."""
        return self._rows.get(self._address(keyed))

    def delete_item(self, **call: Any) -> None:
        address = (call["TableName"], *self._wire(call["Key"]))
        if self._deny == "DeleteItem":
            raise AccessDeniedException("User is not authorized to perform: action dynamodb:DeleteItem")
        self.deleted.append(address)
        self.deleted_calls.append(dict(call))
        if address not in self._left_behind:
            self._rows.pop(address, None)

    def get_item(self, **call: Any) -> dict[str, Any]:
        address = (call["TableName"], *self._wire(call["Key"]))
        if self._deny == "GetItem":
            raise AccessDeniedException("User is not authorized to perform: action dynamodb:GetItem")
        self.reads.append(address)
        self.read_calls.append(dict(call))
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
        if row.get(names[condition]) != values[expected]:
            raise ConditionalCheckFailed("the row is not at the version the write conditioned on")
        if self._ignore_update:
            return
        for clause in str(call["UpdateExpression"]).removeprefix("SET ").split(", "):
            name, _, value = clause.partition(" = ")
            row[names[name]] = values[value]


def _plain(value: Any) -> Any:
    """One AttributeValue in the plain shape the model reads its rows in, by the lane's own decoder."""
    return scenario._python_value(value)


def _wire(value: Any) -> dict[str, Any]:
    """One Python value in the ``AttributeValue`` shape a low-level client sends and answers with.

    ``mutations.wire_value`` covers the scalars, and the event row also holds a list (``productIds``), so
    the list and map cases are encoded here rather than stringified — a row encoded wrongly is a row the
    table would never hold, and a fake holding it hides the bug it exists to catch.
    """
    if isinstance(value, (list, tuple)):
        return {"L": [_wire(item) for item in value]}
    if isinstance(value, Mapping):
        return {"M": {name: _wire(item) for name, item in value.items()}}
    return mutations.wire_value(value)


def _plan(clock: stage3.ScenarioClock, fixture: Mapping[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    return stage3.stage_three_cleanup_plan(clock, fixture, **kwargs)


def _seeds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A stored row for every planned key, so the scripted table starts where the lane left it."""
    return [{"table": row["table"], "key": dict(row["key"]), "item": {"entityType": row["kind"]}} for row in rows]


def _matching_ledger(
    clock: stage3.ScenarioClock, fixture: Mapping[str, Any], ids: Mapping[str, str]
) -> stage3.WriteLedger:
    """A ledger holding every planned Stage 3 write, recorded as its own actor, scope and key.

    The cleanup runner authorizes a planned marker only against the address a recorded write produced, so a
    test that wants a clean teardown has to record the writes the plan describes.  Recording from
    :func:`tests.e2e.utils.show_sell_stage3_support.stage_three_write_steps` — not by copying the plan's
    keys — keeps the two sides independent, which is the point: an address that only matches because both
    sides copied the same string proves nothing.
    """
    ledger = stage3.WriteLedger(clock.token)
    for step in stage3.stage_three_write_steps(fixture, clock.token):
        ledger.record(
            field=step["op"],
            actor=step["actor"],
            variables={
                "input": {
                    stage3.MARKER_SCOPE_ARGUMENT[step["op"]]: ids[step["scopeField"]],
                    "idempotencyKey": step["idempotencyKey"],
                }
            },
        )
    return ledger


def _census(**answers: str) -> dict[str, str]:
    """A residue census for the swept tables, keyed by the physical name the sweep line names."""
    return {
        table: answers.get(key, "") for key, tables in stage3.STAGE_THREE_RESIDUE_TABLES.items() for table in tables
    }


def _canary() -> dict[str, Any]:
    return stage3.stage_three_cleanup_canary(stage3.lane_token(9001))


def test_the_cleanup_run_reads_back_every_row_it_deleted() -> None:
    """A delete that returned is not evidence: every planned key is deleted and then read again."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] != "sweep"]
    canary = _canary()
    client = ScriptedDynamo(_seeds([*plan, canary]))
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=canary,
        ledger=_matching_ledger(clock, fixture, _ids(fixture)),
        ids=_ids(fixture),
        sweep_tokens=_sweep_tokens(clock, fixture),
        sweep_report=("deleted row  unit_campaign 11111111-1111-4111-8111-111111111111",),
        sweep_exit_code=0,
    )
    assert stage2.cleanup_problems(rows) == []
    assert stage2.cleanup_failures(rows) == []
    assert len(rows) == len(plan) + 2  # the canary step and the sweep step
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
    rows = scenario.run_stage_three_cleanup(
        client, lane=clock.token, plan=plan, canary=canary, ledger=stage3.WriteLedger(clock.token), ids={}
    )
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
    blocked = [line for line in stage2.cleanup_blocked(rows) if "DeleteItem" in line]
    assert len(blocked) == 2, stage2.cleanup_blocked(rows)
    assert all("dynamodb:DeleteItem" in line for line in blocked), blocked


def test_the_canary_has_to_be_another_lanes_row_and_still_present() -> None:
    """Both halves: a canary this lane owns proves nothing, and a canary that is gone is a teardown bug."""
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "marker"][:1]
    owned = stage3.stage_three_cleanup_canary(clock.token)
    client = ScriptedDynamo(_seeds(plan))
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=owned,
        ledger=_matching_ledger(clock, fixture, _ids(fixture)),
        ids=_ids(fixture),
    )
    assert any("different lane token" in failure for failure in stage2.cleanup_failures(rows))
    bare = ScriptedDynamo(_seeds(plan))
    rows = scenario.run_stage_three_cleanup(
        bare,
        lane=clock.token,
        plan=plan,
        canary=_canary(),
        ledger=_matching_ledger(clock, fixture, _ids(fixture)),
        ids=_ids(fixture),
    )
    assert any("reached outside its own rows" in failure for failure in stage2.cleanup_failures(rows))


def _uuid(name: str) -> str:
    """A shaped id for one ref: the sweeper compares a token's value to the shape that kind stores."""
    digit = f"{(abs(hash(name)) % 9) + 1}"
    return f"{digit * 8}-{digit * 4}-4{digit * 3}-8{digit * 3}-{digit * 12}"


def _sweep_ids(fixture: Mapping[str, Any]) -> dict[str, str]:
    """The ids a finished Stage 3 lane really holds: Unit, Unit Campaign, profile and Campaign ids are UUIDs."""
    ids = {
        "unit": _uuid("unit"),
        "unit-campaign": _uuid("unit-campaign"),
        "actorAccount": "ACCOUNT#qa-admin",
    }
    for name in fixture["profiles"]:
        ids[f"profile.{name}"] = _uuid(f"profile.{name}")
    for name in fixture["campaigns"]:
        ids[f"campaign.{name}"] = _uuid(f"campaign.{name}")
    for name in fixture["events"]:
        ids[f"event.{name}"] = f"SSE#{_uuid(name)}"
    return ids


def _sweep_tokens(clock: stage3.ScenarioClock, fixture: Mapping[str, Any]) -> tuple[str, ...]:
    keys = [step["idempotencyKey"] for step in stage3.stage_three_write_steps(fixture, clock.token)]
    return stage3.stage_three_lane_tokens(fixture, _sweep_ids(fixture), keys)


def test_the_lane_s_tokens_are_the_typed_tokens_the_sweeper_accepts() -> None:
    """Every token is a ``kind=value`` the real parser takes, built from the ids this lane was answered.

    The kinds are checked by ``scripts/qa_fixture.py``'s own parser, not by a copy of its rules: that
    script is what runs with ``--yes`` and deletes without a prompt, so a token it would refuse is a lane
    that reports a sweep it never performed.
    """
    clock = _clock()
    fixture = _fixture(clock)
    tokens = _sweep_tokens(clock, fixture)
    parsed, refused = qa_fixture.parse_lane_tokens(list(tokens))
    assert refused == [], refused
    assert sorted(f"{kind}={value}" for kind, values in parsed.items() for value in values) == sorted(tokens)
    kinds = {token.split("=", 1)[0] for token in tokens}
    assert {"unit", "unit-campaign", "profile", "campaign", "idem"} == kinds
    assert "order" not in kinds and "join-code" not in kinds, "this lane mints neither, so it names neither"
    assert "data-id" not in kinds, (
        "the Stage 3 DATA_ID starts with an epoch, which the sweeper's data-id rule refuses; the lane "
        "names the ids it was answered instead, and tests/unit/test_show_sell_stage3_support.py pins that"
    )
    marker_keys = [token.split("=", 1)[1] for token in tokens if token.startswith("idem=")]
    assert marker_keys == [step["idempotencyKey"] for step in stage3.stage_three_write_steps(fixture, clock.token)]
    assert len(set(marker_keys)) == len(marker_keys), "one key never covers two writes"


def test_an_unbound_lane_cannot_build_a_sweep_token_out_of_a_placeholder() -> None:
    """A ``kind=<placeholder>`` token is free text with a kind glued on, and the lane refuses to send one."""
    clock = _clock()
    fixture = _fixture(clock)
    with pytest.raises(ValueError) as error:
        stage3.stage_three_lane_tokens(fixture, {}, [])
    assert "no bound value" in str(error.value)


def test_a_sweep_that_has_not_been_run_keeps_cleanup_blocked() -> None:
    """The typed-token sweep is part of cleanup: not run, and the lane is blocked, not clean."""
    clock = _clock()
    fixture = _fixture(clock)
    sweep_rows = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "sweep"]
    assert len(sweep_rows) == 1
    client = ScriptedDynamo(_seeds([_canary()]))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=sweep_rows, canary=_canary())
    assert [row["result"] for row in rows] == [stage2.CLEANUP_OBSERVED, stage2.CLEANUP_BLOCKED]
    assert "no lane tokens" in rows[-1]["summary"]
    assert client.deleted == []


def test_the_plan_addresses_the_markers_production_writes_by_the_writer_s_own_function() -> None:
    """Cleanup's marker keys come from ``mutations.marker_keys``, computed here from the write's own arguments.

    The seed rows are built here, from the actor, operation, scope and key of each planned write, and are
    *not* copied from the plan.  A plan that hand-assembled ``IDEM#actor#op#scope`` — one generic actor,
    one generic scope, one base key per operation — would then address a marker that was never written,
    and the read-back would answer the absence it was looking for.
    """
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    table = stage3.show_and_sells_table()
    production: dict[tuple[str, str], str] = {}
    for step in stage3.stage_three_write_steps(fixture, clock.token):
        marker = mutations.marker_keys(
            table_key="show_and_sells",
            table_name=table,
            actor_id=ids[step["actor"]],
            operation=step["op"],
            scope=ids[step["scopeField"]],
            idempotency_key=step["idempotencyKey"],
        )
        production[(step["op"], step["step"])] = f"{marker.pk}|{marker.sk}"
    plan = [row for row in _plan(clock, fixture, ids=ids) if row["kind"] == "marker"]
    assert len(plan) == len(production)
    assert {f"{row['key']['pk']}|{row['key']['sk']}" for row in plan} == set(production.values())
    scopes = {row["operation"]: row["scopeField"] for row in plan}
    assert scopes["createShowAndSell"] == "unit-campaign", "a create has no event id to scope to yet"
    assert scopes["signupScoutForShowAndSellSlot"].startswith("event.")
    assert {row["actorField"] for row in plan if row["operation"] == "signupScoutForShowAndSellSlot"} == {
        f"account.{entry['profile']}" for entry in fixture["signups"]
    }, "a marker is addressed by the identity that signed the request, and a Scout signs its own signup"
    client = ScriptedDynamo(
        [
            {"table": table, "key": {"pk": pk, "sk": sk}, "item": {"entityType": "marker"}}
            for pk, sk in (address.split("|") for address in production.values())
        ]
        + [_canary()]
    )
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=_canary(),
        ledger=_matching_ledger(clock, fixture, _ids(fixture)),
        ids=ids,
        sweep_tokens=_sweep_tokens(clock, fixture),
        sweep_report=("deleted row  marker IDEM#x",),
        sweep_exit_code=0,
    )
    assert stage2.cleanup_problems(rows) == []
    assert {(call["Key"]["pk"]["S"], call["Key"]["sk"]["S"]) for call in client.deleted_calls} == {
        (pk, sk) for pk, sk in (address.split("|") for address in production.values())
    }, "the lane deletes exactly the markers the writes produced, and reads each one back"


def test_a_planned_marker_whose_key_was_never_recorded_blocks_and_is_left_alone() -> None:
    """A marker for a key the lane never sent is a row that does not exist, and its absence proves nothing.

    The ledger is the evidence of what the lane wrote.  A planned marker whose key is not in it blocks,
    naming the key, instead of deleting nothing and reporting the tidy table as cleanup — and the seeded row
    under that key stays exactly where it was, so a reader can see the lane never reached for it.
    """
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    plan = [row for row in _plan(clock, fixture, ids=ids) if row["kind"] == "marker"]
    assert plan
    foreign = stage3.idempotency_key_for(plan[0]["operation"], clock.token, "never-sent")
    plan[0] = dict(
        plan[0],
        idempotencyKey=foreign,
        key=dict(plan[0]["key"], sk=f"IDEM#{foreign}"),
    )
    ledger = _matching_ledger(clock, fixture, ids)
    assert foreign not in ledger.keys(), "the key this plan row names is one no write of this lane carried"
    client = ScriptedDynamo(_seeds([*plan, _canary()]))
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=_canary(),
        ledger=ledger,
        ids=ids,
        sweep_tokens=_sweep_tokens(clock, fixture),
        sweep_report=("deleted row  marker IDEM#x",),
        sweep_exit_code=0,
    )
    blocked = stage2.cleanup_blocked(rows)
    assert len(blocked) == 1, blocked
    assert "recorded no accepted write with this key" in blocked[0], blocked[0]
    assert (plan[0]["table"], plan[0]["key"]["pk"], plan[0]["key"]["sk"]) not in client.deleted
    assert client.row_at(_seeds([plan[0]])[0]) is not None, "the unauthorized row was never deleted"


def test_a_recorded_key_never_authorizes_a_marker_at_another_address() -> None:
    """Same idempotency key, different actor: the recorded write does not vouch for this planned row.

    The plan's address is derived from the actor, operation and scope it guessed; the ledger holds what the
    server actually accepted.  Here the two disagree — the lane recorded the write as the admin, while the
    plan names the Scout — and the marker that exists is the admin's, not the one the plan points at.  A
    key-only check would delete the Scout-addressed row, read back an absence, and call that cleanup.
    """
    clock = _clock()
    fixture = _fixture(clock)
    ids = _ids(fixture)
    planned = next(row for row in _plan(clock, fixture, ids=ids) if row["kind"] == "marker")
    other_actor = next(
        row["actorField"]
        for row in _plan(clock, fixture, ids=ids)
        if row["kind"] == "marker" and row["actorField"] != planned["actorField"]
    )
    plan = [planned]
    scope = planned["scopeField"]  # already an id: the plan was built with the lane's ids bound

    # The write the lane really sent: same key, same operation, same scope — a different identity.
    recorded_row = {
        "operation": planned["operation"],
        "actorField": other_actor,
        "scopeField": scope,
        "idempotencyKey": planned["idempotencyKey"],
    }
    ledger = stage3.WriteLedger(clock.token)
    ledger.record(
        field=planned["operation"],
        actor=other_actor,
        variables={
            "input": {
                stage3.MARKER_SCOPE_ARGUMENT[planned["operation"]]: scope,
                "idempotencyKey": planned["idempotencyKey"],
            }
        },
    )
    recorded = stage3.derived_marker_address(recorded_row, ids=ids)
    planned_address = stage3.plan_row_address(planned)
    assert recorded != planned_address, "the two addresses have to differ for the check to mean anything"
    assert recorded[2] == planned_address[2] and recorded[0] == planned_address[0], (
        "same table and same sort key: only the actor's partition key differs, so a key-only check would pass"
    )

    client = ScriptedDynamo(
        [
            {"table": recorded[0], "key": {"pk": recorded[1], "sk": recorded[2]}, "item": {"entityType": "marker"}},
            *_seeds(plan),
            _canary(),
        ]
    )
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=_canary(),
        ledger=ledger,
        ids=ids,
        sweep_tokens=_sweep_tokens(clock, fixture),
        sweep_report=("deleted row  marker IDEM#x",),
        sweep_exit_code=0,
    )
    blocked = stage2.cleanup_blocked(rows)
    assert len(blocked) == 1, blocked
    assert "not at" in blocked[0] and planned["idempotencyKey"] in blocked[0], blocked[0]
    assert client.deleted == [recorded], "only the marker the lane recorded is deleted, and it is read back"
    assert client.row_at(_seeds(plan)[0]) is not None, "the planned row the ledger does not vouch for is untouched"


def test_cleanup_owes_the_sweep_even_when_the_plan_omits_the_sweep_row() -> None:
    """Leaving the sweep out of the plan is not a way through the gate: the evidence is owed either way.

    The row is appended whether or not the plan asked for it, and when no report was taken the sanctioned
    sweeper is run here — the test's stub stands in for ``scripts/qa_fixture.py`` and shows the lane handed
    the same typed tokens it would have sent on ``dev``.
    """
    clock = _clock()
    fixture = _fixture(clock)
    plan = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] != "sweep"]
    assert plan and all(row["kind"] != "sweep" for row in plan)
    client = ScriptedDynamo(_seeds([*plan, _canary()]))
    rows = scenario.run_stage_three_cleanup(client, lane=clock.token, plan=plan, canary=_canary())
    assert rows[-1]["result"] == stage2.CLEANUP_BLOCKED
    assert "no lane tokens" in rows[-1]["summary"]

    handed: list[list[str]] = []

    def runner(tokens: Sequence[str]) -> tuple[int, list[str], list[str]]:
        handed.append(list(tokens))
        return 0, [], ["deleted row  marker IDEM#x"]

    tokens = _sweep_tokens(clock, fixture)
    rows = scenario.run_stage_three_cleanup(
        client,
        lane=clock.token,
        plan=plan,
        canary=_canary(),
        ledger=_matching_ledger(clock, fixture, _ids(fixture)),
        ids=_ids(fixture),
        sweep_tokens=tokens,
        sweep_runner=runner,
    )
    assert handed == [list(tokens)], "the lane runs the sweeper rather than describing one it meant to run"
    assert rows[-1]["result"] == stage2.CLEANUP_OBSERVED
    assert stage2.cleanup_problems(rows) == []
    assert len(rows) == len(plan) + 2


def test_blocked_residue_needs_a_measured_census_not_a_name_on_a_list() -> None:
    """Amendment B accepts blocked residue only where a product read **ran** and counted this lane's rows.

    Four shapes of the same ``BLOCKED`` line, and only one of them is accepted residue:

    * a table no Stage 3 product read enumerates at all;
    * an enumerable table with no census entry, because the lane never took one;
    * an enumerable table whose census entry is empty, because the read was refused or answered ``NOT_FOUND``
      after the Campaign row went away — a read that did not run proves nothing, and reporting its silence
      as an absence is the false clean this gate exists to prevent;
    * an enumerable table whose entry is prose rather than a read answer.

    Nothing in the lane grants a blocked table by name: there is no static proof map to be on.
    """
    clock = _clock()
    fixture = _fixture(clock)
    sweep_rows = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "sweep"]
    tokens = _sweep_tokens(clock, fixture)
    client = ScriptedDynamo(_seeds([_canary()]))

    line = "BLOCKED kernelworx-inventory-ue1-dev: dynamodb:Scan is not granted to this identity"

    def sweep(report: Sequence[str], code: int, census: Mapping[str, str]) -> dict[str, str]:
        return scenario.run_stage_three_cleanup(
            client,
            lane=clock.token,
            plan=sweep_rows,
            canary=_canary(),
            sweep_tokens=tokens,
            sweep_report=report,
            sweep_exit_code=code,
            residue_census=census,
        )[-1]

    counted = sweep((line,), 1, _census(**{"inventory": "inventoryMovements for UC#1 answered 7 row(s)"}))
    assert counted["result"] == stage2.CLEANUP_OBSERVED, "a census that counted the rows is what Amendment B asks for"
    assert (
        "kernelworx-inventory-ue1-dev (dynamodb:Scan) by inventoryMovements for UC#1 answered 7 row(s)"
        in counted["summary"]
    )

    no_census = sweep((line,), 1, {})
    assert no_census["result"] == stage2.CLEANUP_BLOCKED
    assert "carries no answer for it" in no_census["summary"]

    failed_read = sweep((line,), 1, _census(**{"inventory": ""}))
    assert failed_read["result"] == stage2.CLEANUP_BLOCKED
    assert "no product read taken before the teardown proved" in failed_read["summary"]

    prose = sweep((line,), 1, _census(**{"inventory": "the movements rows are still there, trust me"}))
    assert prose["result"] == stage2.CLEANUP_BLOCKED
    assert "not a read answer" in prose["summary"]
    assert not stage3.is_census_statement("the movements rows are still there, trust me")

    unreadable_by_this_lane = sweep(
        ("BLOCKED kernelworx-units-ue1-dev: dynamodb:Scan is not granted to this identity",), 1, _census()
    )
    assert unreadable_by_this_lane["result"] == stage2.CLEANUP_BLOCKED
    assert "no product read enumerates this table" in unreadable_by_this_lane["summary"]


def test_a_report_naming_every_denied_swept_table_is_proven_table_by_table() -> None:
    """The sweeper scans three lane tables and all three deny ``Scan``: a real report names all of them.

    A census that answers only some of them is not a clean sweep — each blocked table stands or falls on its
    **own** measured answer, in its own words, and the record says which ones failed.  The three names here
    are the sweeper's own (``LANE_TABLES`` in ``scripts/qa_fixture.py``), because a census keyed on a table
    it never prints would leave every real report line unprovable.
    """
    clock = _clock()
    fixture = _fixture(clock)
    sweep_rows = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "sweep"]
    tokens = _sweep_tokens(clock, fixture)
    client = ScriptedDynamo(_seeds([_canary()]))
    report = tuple(
        f"BLOCKED {table}: dynamodb:Scan is not granted to this identity"
        for tables in stage3.STAGE_THREE_RESIDUE_TABLES.values()
        for table in tables
    )
    assert len(report) == 3, report

    def sweep(census: Mapping[str, str]) -> dict[str, str]:
        return scenario.run_stage_three_cleanup(
            client,
            lane=clock.token,
            plan=sweep_rows,
            canary=_canary(),
            sweep_tokens=tokens,
            sweep_report=report,
            sweep_exit_code=1,
            residue_census=census,
        )[-1]

    measured = _census(
        **{
            "inventory": "inventoryMovements for UC#1 answered 7 row(s)",
            "orders": "unitScoutCampaignOrders for UC#1/SC#1 answered 2 row(s)",
            "order-fulfillments": stage3.NO_ORDER_NOTE,
        }
    )
    clean = sweep(measured)
    assert clean["result"] == stage2.CLEANUP_OBSERVED
    for tables in stage3.STAGE_THREE_RESIDUE_TABLES.values():
        assert tables[0] in clean["summary"], tables
    assert "residue no product read proves" not in clean["summary"]

    partial = dict(measured)
    del partial["kernelworx-order-fulfillments-ue1-dev"]
    incomplete = sweep(partial)
    assert incomplete["result"] == stage2.CLEANUP_BLOCKED
    assert "kernelworx-order-fulfillments-ue1-dev" in incomplete["summary"]
    assert "residue no product read proves" in incomplete["summary"]
    assert "kernelworx-orders-ue1-dev (dynamodb:Scan) by unitScoutCampaignOrders" in incomplete["summary"], (
        "the tables that were measured are still counted, and named as such"
    )


def test_the_ledger_records_the_write_the_lane_actually_sent_and_not_the_refusal() -> None:
    """``API-FIX-03``'s advancing slot write is a real accepted mutation the fixture tree never planned.

    The stale fixture needs a legal write at the version the read answered; that write produced a marker,
    and the submit that was refused did not.  Recording at the transport path is what tells the two apart.
    """
    clock = _clock()
    ids = _ids(_fixture(clock))
    ledger = stage3.WriteLedger(clock.token)
    api = ScriptedApi(
        [
            {"data": {"showAndSell": {"showAndSellId": ids["event.future"], "version": 7}}},
            _success_body("upsertShowAndSellSlot", {"slotId": "SLOT#advanced"}),
            _refusal_body("stale-event-version"),
        ]
    )
    steps = scenario.run_stale_version_lane(
        scenario.recording_transport(api, ledger, actor="account.admin"), clock, ids
    )
    assert scenario.stale_version_problems(steps) == []
    assert [(row["operation"], row["idempotencyKey"], row["actor"]) for row in ledger.records] == [
        (
            "upsertShowAndSellSlot",
            stage3.idempotency_key_for("upsertShowAndSellSlot", clock.token, "advance-version"),
            "account.admin",
        )
    ], "the accepted write is recorded, the refused submit is not"
    row = ledger.marker_rows(ids)[0]
    assert row["kind"] == "marker" and row["table"] == stage3.show_and_sells_table()
    assert (
        row["key"]["sk"]
        == f"IDEM#{stage3.idempotency_key_for('upsertShowAndSellSlot', clock.token, 'advance-version')}"
    )
    assert ledger.keys() == (row["idempotencyKey"],)


def test_the_ledger_cleans_the_winner_of_each_race_whichever_side_won() -> None:
    """A race winner's marker is a real row whichever thread won, and cleanup has to address it.

    Both directions are run, because the lane cannot know in advance which Scout lands: each side is
    recorded with its own account id and its own ``race-*`` key, and the marker deleted is the one the
    winner's write produced — computed here from ``mutations.marker_keys`` rather than copied from a plan.
    """
    clock = _clock()
    ids = _ids(_fixture(clock))
    calls = scenario.RACE_BARRIER_CALLS["capacity"](clock, ids)
    profiles = ["avery", "blake"]
    for winner in (0, 1):
        ledgers = [stage3.WriteLedger(clock.token) for _ in calls]
        transports = [
            scenario.recording_transport(
                OutcomeServer(accepted=index == winner, refusal="capacity-full"),
                ledgers[index],
                actor=f"account.{profiles[index]}",
            )
            for index in range(len(calls))
        ]
        result = scenario.run_race_barrier(transports, calls, refusal="capacity-full")
        assert result["violations"] == []
        assert sum(len(ledger.records) for ledger in ledgers) == 1, "only the write that landed has a marker"
        won = ledgers[winner].records[0]
        assert won["actor"] == f"account.{profiles[winner]}"
        assert won["operation"] == "signupScoutForShowAndSellSlot"
        assert won["scope"] == ids["event.future"]
        loser = [ledger for ledger in ledgers if ledger.records == []]
        assert len(loser) == 1, "the losing thread recorded nothing"

        marker = mutations.marker_keys(
            table_key="show_and_sells",
            table_name=stage3.show_and_sells_table(),
            actor_id=ids[f"account.{profiles[winner]}"],
            operation="signupScoutForShowAndSellSlot",
            scope=ids["event.future"],
            idempotency_key=won["idempotencyKey"],
        )
        client = ScriptedDynamo(
            [
                {
                    "table": marker.table_name,
                    "key": {"pk": marker.pk, "sk": marker.sk},
                    "item": {"entityType": "marker"},
                },
                _canary(),
            ]
        )
        rows = scenario.run_stage_three_cleanup(
            client,
            lane=clock.token,
            plan=[],
            canary=_canary(),
            ledger=ledgers[winner],
            ids=ids,
            sweep_tokens=_sweep_tokens(clock, _fixture(clock)),
            sweep_report=("deleted row  marker IDEM#x",),
            sweep_exit_code=0,
        )
        assert stage2.cleanup_problems(rows) == []
        assert client.deleted == [(marker.table_name, marker.pk, marker.sk)], "the winner's marker, and only it"
        assert len(rows) == 3, "the recorded marker, the canary, and the sweep"
        assert rows[0]["summary"].startswith("marker ")
        assert "%23" in marker.pk, "the actor segment is escaped the way marker_partition_key escapes it"


def test_the_sweep_verdict_comes_from_the_report_classes_not_from_the_plan() -> None:
    """The sweeper's own classes decide the row: a residue fails, an unnamed table blocks, and only a clean re-scan observes."""
    clock = _clock()
    fixture = _fixture(clock)
    sweep_rows = [row for row in _plan(clock, fixture, ids=_ids(fixture)) if row["kind"] == "sweep"]
    tokens = _sweep_tokens(clock, fixture)
    client = ScriptedDynamo(_seeds([_canary()]))

    census = _census(**{"inventory": "inventoryPositions for UC#1 answered 2 row(s)"})

    def sweep(report: Sequence[str], code: int) -> dict[str, str]:
        return scenario.run_stage_three_cleanup(
            client,
            lane=clock.token,
            plan=sweep_rows,
            canary=_canary(),
            sweep_tokens=tokens,
            sweep_report=report,
            sweep_exit_code=code,
            residue_census=census,
        )[-1]

    clean = sweep(("deleted row  event  SSE#x", "kept  membership  SSE#y (another tenant)"), 0)
    assert clean["result"] == stage2.CLEANUP_OBSERVED
    assert "deleted=1" in clean["summary"] and "kept=1" in clean["summary"]
    assert " ".join(tokens) in clean["summary"]
    residue = sweep(("LEFT event SSE#x",), 1)
    assert residue["result"] == stage2.CLEANUP_FAILED
    assert "left=1" in residue["summary"]
    unreadable = sweep(("BLOCKED kernelworx-inventory-ue1-dev: dynamodb:Scan is not granted to this identity",), 1)
    assert unreadable["result"] == stage2.CLEANUP_OBSERVED, "Amendment B accepts residue a read counted"
    assert "counted by a product read taken before the teardown: kernelworx-inventory-ue1-dev" in unreadable["summary"]
    assert "inventoryPositions for UC#1 answered 2 row(s)" in unreadable["summary"]
    unexplained = sweep(("some line this parser does not know",), 1)
    assert unexplained["result"] == stage2.CLEANUP_FAILED, "a non-zero exit no class explains is not a clean sweep"


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
    latest: str | None = None,
) -> dict[str, Any]:
    """The row the lane's own ``createShowAndSell`` wrote, addressable the way the table holds it.

    The row is built by the model — the same builder the create path uses — and a stored state is then
    applied as the pair the §5 writer applies it in: ``FINALIZED`` only ever arrives together with
    ``approvedFinalizationId`` and a ``latestFinalizationId`` pointing at it, and ``REOPENED`` only ever
    arrives with the approved pointer cleared and the latest pointer still standing.  Seeding a row the
    product could not produce would test a shape that cannot exist.
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
    row[show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE] = latest
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
    assert (
        plan["changes"][show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE]
        == plan["changes"][show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE]
    ), "a first finalization sets both pointers, which is what §5.2.1 writes"
    assert plan["note"] == stage3.BUILDER_ONLY_STATE_FIXTURE_NOTE
    read_version = plan["conditionVersion"]
    seed = _stored_event(clock, ids, "finalized", version=read_version)
    client = ScriptedDynamo([seed])
    before: list[Mapping[str, Any]] = []
    verdict = scenario.apply_state_fixture(client, plan, on_read=before.append)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    assert "documented Stage 3 fixture builder" in verdict["summary"]
    assert f"version {read_version} -> {read_version + 1}" in verdict["summary"]
    assert before[0][show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_SCHEDULED
    assert client.updated[0]["ConditionExpression"] == "#version = :expected"
    assert client.updated[0]["ExpressionAttributeValues"][":expected"] == {"N": str(read_version)}
    assert all(call.get("ConsistentRead") is True for call in client.read_calls), client.read_calls
    assert len(client.read_calls) == 2, "the fixture reads before it writes and again to prove the write landed"
    after = client.row_at(seed)
    assert after is not None
    assert after[show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_FINALIZED
    assert show_and_sell_models.event_invariant_violations(after) == []


def test_api_fix_01_the_read_back_judges_the_wire_form_a_low_level_client_answers() -> None:
    """The fixture compares decoded values, not the ``AttributeValue`` container they arrive in.

    A real ``get_item`` answers ``{"S": "FINALIZED"}``.  A fixture that compared that to the state string
    fails *after* the write landed, which is the worst possible place to discover it: the row is FINALIZED
    on the stack and the lane reports the fixture as failed.
    """
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    stored = client.wire_at(seed)
    assert stored is not None
    assert stored[show_and_sell_models.STATUS_ATTRIBUTE] == {"S": show_and_sell_models.STATUS_FINALIZED}
    assert stored[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] == {
        "S": plan["changes"][show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE]
    }


def test_api_fix_01_a_read_back_that_still_answers_the_old_status_names_the_decoded_value() -> None:
    """An update that was accepted but did not land is caught by the read-back, and reported readably."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    client = ScriptedDynamo([seed], ignore_update=True)
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert f"read-back status is {show_and_sell_models.STATUS_SCHEDULED!r}" in verdict["summary"]
    assert "{'S':" not in verdict["summary"], "the report quotes the value the table holds, not its container"


def test_api_fix_01_conditions_on_the_version_the_read_answered_not_the_plan_s_guess() -> None:
    """The condition is the before-image's version, so a row that moved is refused rather than overwritten."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    assert plan["conditionVersion"] == 1
    seed = _stored_event(clock, ids, "finalized", version=12)
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    assert client.updated[0]["ExpressionAttributeValues"][":expected"] == {"N": "12"}
    assert "version 12 -> 13" in verdict["summary"]
    assert client.row_at(seed)[show_and_sell_models.VERSION_ATTRIBUTE] == 13


class RacingDynamo(ScriptedDynamo):
    """A table that moves the row between the read and the write — the race the version condition is for."""

    def __init__(self, rows: Iterable[Mapping[str, Any]], *, bumped_version: int) -> None:
        super().__init__(rows)
        self._bump = bumped_version
        self._bumped = False

    def get_item(self, **call: Any) -> dict[str, Any]:
        answer = super().get_item(**call)
        if answer.get("Item") is not None and not self._bumped:
            self._bumped = True
            address = (call["TableName"], *self._wire(call["Key"]))
            self._rows[address][show_and_sell_models.VERSION_ATTRIBUTE] = mutations.wire_value(self._bump)
        return answer


def test_api_fix_01_the_fixture_writes_the_read_version_plus_one_never_the_version_it_guessed() -> None:
    """A fixture that moves a version backwards would break the optimistic locking it is meant to prove.

    The plan is built before the row is read, so its own idea of the version (here, 2) is only a guess.
    Both halves of the write come from the read: the condition is version 12, and the value written is 13.
    """
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    assert plan["conditionVersion"] == 1 and plan["changes"][show_and_sell_models.VERSION_ATTRIBUTE] == 2
    seed = _stored_event(clock, ids, "finalized", version=12)
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    update = client.updated[0]
    assert update["ConditionExpression"] == "#version = :expected"
    assert update["ExpressionAttributeValues"][":expected"] == {"N": "12"}
    assert update["ExpressionAttributeValues"][f":{show_and_sell_models.VERSION_ATTRIBUTE}"] == {"N": "13"}, (
        "the SET carries the version derived from the before-image, not the plan's precomputed one"
    )
    after = client.row_at(seed)
    assert after[show_and_sell_models.VERSION_ATTRIBUTE] == 13
    assert after[show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_FINALIZED


def test_api_fix_01_a_row_that_moved_under_the_fixture_is_a_failed_fixture() -> None:
    """The row advances after the read: the write is refused by the condition, and the lane says failed."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    bumped = plan["conditionVersion"] + 4
    client = RacingDynamo([seed], bumped_version=bumped)
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert "ConditionalCheckFailed" in verdict["summary"]
    assert client.updated[0]["ExpressionAttributeValues"][":expected"] == {"N": str(plan["conditionVersion"])}, (
        "the fixture conditions on the version its own read answered, and the table refuses the stale write"
    )
    assert client.row_at(seed)[show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_SCHEDULED
    assert client.row_at(seed)[show_and_sell_models.VERSION_ATTRIBUTE] == bumped


def test_api_fix_01_a_row_with_no_version_refuses_to_write_blind() -> None:
    """A row the read answers without a version cannot be conditioned on, and that is a failure."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    seed = _stored_event(clock, ids, "finalized", version=plan["conditionVersion"])
    seed["item"].pop(show_and_sell_models.VERSION_ATTRIBUTE)
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert "no version to condition on" in verdict["summary"]
    assert client.updated == []


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


def test_api_fix_01_reopened_clears_the_approved_pointer_and_keeps_the_history_pointer() -> None:
    """§5.3.1 reopens by clearing ``approvedFinalizationId`` **while retaining** ``latestFinalizationId``.

    Both halves are asserted on exact values: the approved pointer is gone, and the latest pointer is
    still the one the row arrived with.  A fixture that cleared it would hand a REOPENED event no
    finalization history, which is a row the product cannot produce and which every later reopening or
    re-finalization scenario would then read as if it were real.
    """
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.reopen_event_fixture_writes(clock, ids)
    assert plan["state"] == show_and_sell_models.STATUS_REOPENED
    assert plan["changes"][show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] is None
    assert show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE not in plan["changes"], (
        "clearing the latest pointer is not part of reopening: the update must say nothing about it"
    )
    approved = f"FINAL#{clock.token}-first"
    latest = f"FINAL#{clock.token}-first"
    seed = _stored_event(
        clock,
        ids,
        "reopened",
        version=plan["conditionVersion"],
        status=show_and_sell_models.STATUS_FINALIZED,
        approved=approved,
        latest=latest,
    )
    update_expression = scenario._update_expression(plan["changes"])
    assert f"#{show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE}" not in update_expression
    client = ScriptedDynamo([seed])
    verdict = scenario.apply_state_fixture(client, plan)
    assert verdict["result"] == stage2.CLEANUP_OBSERVED
    after = client.row_at(seed)
    assert after is not None
    assert after[show_and_sell_models.STATUS_ATTRIBUTE] == show_and_sell_models.STATUS_REOPENED
    assert after[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] is None
    assert after[show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE] == latest
    assert show_and_sell_models.event_invariant_violations(after) == []
    uncleared = dict(after, approvedFinalizationId="FINAL#kept")
    problems = show_and_sell_models.event_invariant_violations(uncleared)
    assert any("approvedFinalizationId cleared" in problem for problem in problems), problems
    no_history = dict(after, latestFinalizationId=None)
    assert no_history[show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE] is None, (
        "a REOPENED row with no history pointer is legal to store, which is why the fixture has to be "
        "asserted against the value it arrived with rather than against legality alone"
    )


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


def test_api_fix_01_a_missing_row_is_a_failed_fixture() -> None:
    """Nothing at that key means the lane's own create never landed, and the fixture says so."""
    clock = _clock()
    ids = _ids(_fixture(clock))
    plan = scenario.finalize_event_fixture_writes(clock, ids)
    verdict = scenario.apply_state_fixture(ScriptedDynamo(), plan)
    assert verdict["result"] == stage2.CLEANUP_FAILED
    assert "no event row to transition" in verdict["summary"]


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
