"""The executable half of the Stage 3 §3.6.2 fixture layer.

:mod:`tests.e2e.utils.show_sell_stage3_support` states what the Stage 3 lane asserts: the refusal
table, the documents, the clock, the fixture tree, the ICS validator, the cleanup vocabulary.  This
module is what a lane *does* with them, so that a named acceptance id is an executed write and a
compared answer rather than a string looked up in a table:

* :func:`run_conflict_lane` performs every §3.6.2 collision through the same GraphQL transport the
  live lane uses (:func:`tests.e2e.utils.show_sell_graphql.gql_raw`) and compares the answer to the
  row of the refusal table it belongs to.  A collision that is not refused is a finding, not a pass.
* :func:`run_stale_version_lane` is ``API-FIX-03``'s "read and advance versions … create stale-version
  fixtures without waiting": read the row's version, advance it with a legal write, then submit the
  version that read preceded it and expect the recorded refusal.
* :func:`run_removed_member_lane` removes a Scout with the product's own ``removeUnitCampaignMembership``
  and asserts the signup that follows it is refused, with the roster read between each step.
* :func:`run_race_barrier` rendezvouses two threads on a :class:`threading.Barrier` before either
  write is sent, so "the loser is refused" is a measured result rather than a claim about ordering, and
  it reports which arrival index each thread got as the proof the rendezvous happened.
* :func:`finalize_event_fixture_writes` and :func:`reopen_event_fixture_writes` are the
  ``API-FIX-01`` answer for the two states this SDL has no mutation for.  They render the transition as
  a conditioned ``UpdateItem`` on the row the public ``createShowAndSell`` already wrote, validate the
  resulting row with :func:`src.utils.show_and_sell_models.event_invariant_violations` before sending
  it, and :func:`apply_state_fixture` read-backs it.  When the QA identity
  ``kernelworx-qa-ue1-dev`` cannot read or write that row, the verdict is ``blocked`` and names the
  ``dynamodb:`` action it is denied — the same shape ``scripts/qa_fixture.py`` reports for an unreadable
  table, and the reason §3.6.2 is reported blocked rather than quietly passed.
* :func:`run_stage_three_cleanup` plans, deletes, and reads back.  A ``delete_item`` that returned
  without an error is not evidence: the row must be gone on a fresh ``get_item``, a row another lane
  token owns must never be deleted, and the other lane's canary row must still be present afterwards.
* :func:`validate_invite_captures` runs the ICS validator over the captured bytes of
  ``buildInvite`` — two builds of one signup — so CAL-01's "same UID on every download" and CAL-02's
  UTC/``Z`` shape are checked against what the browser emits.

The captures are the browser's own output, not a hand-written stand-in.  To re-cut them after changing
the emitter, bundle the frontend module and build one invite per download:

.. code-block:: text

    node_modules/.bin/esbuild frontend/src/lib/showSell.ts --bundle --format=esm \
        --outfile=/tmp/showSell.mjs
    node -e "import('/tmp/showSell.mjs').then(async (m) => { ... buildInvite(dto, date) ... })"

and write the returned strings to ``tests/e2e/fixtures/show_sell_stage3_invite_build.ics`` and
``…_build_repeat.ics`` unchanged, with the same signup DTO and two different ``generatedAt`` clocks.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from src.utils import show_and_sell_models, unit_campaign_models
from tests.e2e.utils import show_sell_graphql
from tests.e2e.utils import show_sell_stage2_support as stage_two
from tests.e2e.utils import show_sell_stage3_support as stage_three

__all__ = [
    "CONFLICT_CALLS",
    "RACE_BARRIER_CALLS",
    "STATE_FIXTURE_REQUIRED_ACTIONS",
    "StateFixtureDenied",
    "apply_state_fixture",
    "collect_lane_ids",
    "conflict_lane_problems",
    "finalize_event_fixture_writes",
    "invite_capture_names",
    "read_invite_capture",
    "reopen_event_fixture_writes",
    "run_conflict_lane",
    "run_removed_member_lane",
    "run_race_barrier",
    "run_stale_version_lane",
    "run_stage_three_cleanup",
    "unbound_key_cells",
    "unbound_refs",
    "validate_invite_captures",
    "wire_key",
]

# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------
#
# One call signature, so the same lane code runs against the deployed stack and
# against the scripted transport ``tests/unit`` uses.  ``field`` is the document
# name (the key of :data:`stage_three.STAGE_THREE_DOCUMENTS` or
# :data:`stage_two.STAGE_TWO_SUPPORT_DOCUMENTS`), ``variables`` are its GraphQL
# variables, and the answer is the whole response body — errors included —
# because on this surface the error *is* the finding.

#: ``(field, variables) -> the whole GraphQL response body``.
Transport = Callable[[str, Mapping[str, Any]], dict[str, Any]]


def graphql_transport(token: str) -> Transport:
    """The live transport for one signed-in identity: send the module's document, return the body.

    A persona-specific transport rather than a persona argument, because the Stage 3 assertions are
    about *who* is asking: Riley's denial and Morgan's denial are separate lanes, and a race barrier
    needs two identities that both reached the same barrier.
    """

    def call(field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        document = stage_three.STAGE_THREE_DOCUMENTS.get(field) or stage_two.STAGE_TWO_SUPPORT_DOCUMENTS[field]
        return show_sell_graphql.gql_raw(token, document, dict(variables))

    return call


def recording_transport(transport: Transport, ledger: stage_three.WriteLedger, *, actor: str) -> Transport:
    """Wrap one identity's transport so every accepted mutation lands in the lane's write ledger.

    The record is made **after** the answer, and only for an answer that carried data: a refused write
    writes no idempotency marker, so a lane that cleaned for it would read back a true absence from a row
    that never existed.  The actor is named where the transport is built, because that is where the lane
    knows which identity's token is inside it — a Scout's signup marker belongs to the Scout's account, and
    inferring it from a fixture tree is not evidence.
    """

    def call(field: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        body = transport(field, variables)
        if field in stage_three.MARKER_SCOPE_ARGUMENT and succeeded(body, field):
            ledger.record(field=field, actor=actor, variables=variables)
        return body

    return call


def data_of(body: Mapping[str, Any], field: str) -> Any:
    """The ``data`` answer for ``field``, or ``None`` when the body answered none."""
    return (body.get("data") or {}).get(field)


def succeeded(body: Mapping[str, Any], field: str) -> bool:
    """Whether the answer is a data answer: no ``errors``, and a non-null payload for the field.

    ``deleteShowAndSellSlot`` answers a Boolean, so a ``False`` answer is a data answer; only a missing
    key or ``None`` counts as no answer.
    """
    if body.get("errors"):
        return False
    data = body.get("data")
    return isinstance(data, Mapping) and field in data and data[field] is not None


# ---------------------------------------------------------------------------
# Binding the fixture's refs to the ids the server minted
# ---------------------------------------------------------------------------


def lane_id(ids: Mapping[str, str], ref: str) -> str:
    """The bound id for one fixture ref, or its placeholder when the lane has no answer for it."""
    return ids.get(ref, f"<{ref}>")


def collect_lane_ids(fixture: Mapping[str, Any], answers: Mapping[str, str]) -> dict[str, str]:
    """Merge the ids the lane was answered into one ref → id map.

    ``createUnit``/``createUnitCampaign``/``createShowAndSell``/``upsertShowAndSellSlot``/``listMyProfiles``
    mint ids the caller never names, so the live lane collects them here and every write below reads
    them from one place.  A ref with no answer stays unbound and visible: :func:`unbound_refs` reports
    it, and a fixture the lane cannot name blocks the scenario instead of silently sending a placeholder.
    """
    ids = dict(answers)
    for ref in fixture_refs(fixture):
        ids.setdefault(ref, ids.get(ref, ""))
    return {ref: value for ref, value in ids.items() if value}


def fixture_refs(fixture: Mapping[str, Any]) -> tuple[str, ...]:
    """Every ``ref`` the fixture tree names, in a stable order.

    The refs come back exactly as the payloads and the cleanup plan look them up — ``event.future``,
    ``slot.midday``, ``profile.avery``, ``campaign.avery``, ``product.p01`` — because that is the key
    :func:`collect_lane_ids` binds and :func:`lane_id` reads.  A stripped ref would be a ref the lane
    could bind and still send a ``<placeholder>`` for.
    """
    refs: list[str] = ["unit", "unit-campaign"]
    refs += [f"event.{name}" for name in sorted(fixture["events"])]
    refs += [f"slot.{name}" for name in sorted(fixture["slots"])]
    refs += [entry["ref"] for entry in fixture["profiles"].values()]
    refs += [entry["ref"] for entry in fixture["campaigns"].values()]
    refs += [entry["ref"] for entry in fixture["products"].values()]
    refs += [slot["ref"] for slot in fixture["bigSlots"]]
    return tuple(dict.fromkeys(refs))


def unbound_refs(fixture: Mapping[str, Any], ids: Mapping[str, str]) -> tuple[str, ...]:
    """The refs the tree needs that the lane has no id for — the blocked half of ``API-FIX-01``."""
    return tuple(ref for ref in fixture_refs(fixture) if not ids.get(ref))


def unbound_key_cells(key: Mapping[str, str]) -> tuple[str, ...]:
    """The key cells that still hold a ``<placeholder>``, so no delete is ever sent against one."""
    return tuple(name for name, value in key.items() if stage_three.UNBOUND_KEY_MARKER in str(value))


# ---------------------------------------------------------------------------
# SS-SM-05/06/11: the collisions, and the lane that runs them
# ---------------------------------------------------------------------------
#
# Each row of ``STAGE_THREE_CONFLICT_PAIRS`` is the *second* call of a collision.
# ``CONFLICT_CALLS`` is the executable half: it builds that call's payload from
# the fixture tree and the bound ids, with a fresh idempotency key per step, so
# the answer the lane compares against the table is an answer the server gave.

_LaneCall = tuple[str, dict[str, Any]]


def _signup(
    clock: stage_three.ScenarioClock, ids: Mapping[str, str], event: str, slot: str, profile: str, step: str
) -> _LaneCall:
    return (
        "signupScoutForShowAndSellSlot",
        {
            "input": stage_three.signup_input(
                lane_id(ids, f"event.{event}"),
                lane_id(ids, f"slot.{slot}"),
                lane_id(ids, f"campaign.{profile}"),
                lane_id(ids, f"profile.{profile}"),
                idempotency_key=stage_three.idempotency_key_for("signupScoutForShowAndSellSlot", clock.token, step),
            )
        },
    )


def _slot_upsert(
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    event: str,
    *,
    day_offset: int,
    capacity: int,
    step: str,
    slot_id: str | None = None,
    version: int | None = None,
) -> _LaneCall:
    """A colliding slot write.

    ``version`` is the event version to condition on.  A fixture that is about to move the row past a
    version it just read has to name *that* version, or the advancing write is refused for the wrong
    reason and the lane never builds the stale fixture it set out to build.
    """
    start_at, end_at = clock.unit_window(day_offset, "09:00", "10:00")
    return (
        "upsertShowAndSellSlot",
        {
            "input": stage_three.upsert_slot_input(
                lane_id(ids, f"event.{event}"),
                version if version is not None else int(ids.get(f"version.{event}", "1")),
                start_at,
                end_at,
                capacity,
                slot_id=lane_id(ids, f"slot.{slot_id}") if slot_id else None,
                label=f"Collision {step}",
                idempotency_key=stage_three.idempotency_key_for("upsertShowAndSellSlot", clock.token, step),
            )
        },
    )


def _confirm(
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    event: str,
    rows: Sequence[tuple[str, str, int]],
    step: str,
) -> _LaneCall:
    return (
        "confirmShowAndSellWork",
        {
            "input": stage_three.confirm_work_input(
                lane_id(ids, f"event.{event}"),
                int(ids.get(f"version.{event}", "1")),
                rows,
                idempotency_key=stage_three.idempotency_key_for("confirmShowAndSellWork", clock.token, step),
            )
        },
    )


#: refusal → the colliding call.  Every row of the conflict table has one, so a
#: lane cannot report a collision it never sent.
CONFLICT_CALLS: Mapping[str, Callable[[stage_three.ScenarioClock, Mapping[str, str]], _LaneCall]] = {
    "duplicate-signup": lambda clock, ids: _signup(clock, ids, "future", "first-sales", "avery", "duplicate"),
    "capacity-full": lambda clock, ids: _signup(clock, ids, "future", "first-sales", "blake", "capacity"),
    "cross-campaign-overlap": lambda clock, ids: _signup(clock, ids, "future", "full-booth", "avery", "overlap"),
    "signup-window-closed": lambda clock, ids: _signup(clock, ids, "ended", "morning", "avery", "window"),
    "removed-member-signup": lambda clock, ids: _signup(clock, ids, "future", "first-sales", "devon", "removed"),
    "unjoined-scout-signup": lambda clock, ids: _signup(clock, ids, "future", "first-sales", "emery", "unjoined"),
    "cross-campaign-roster": lambda clock, ids: (
        "signupScoutForShowAndSellSlot",
        {
            "input": stage_three.signup_input(
                lane_id(ids, "event.future"),
                lane_id(ids, "slot.first-sales"),
                lane_id(ids, "campaign.blake"),
                lane_id(ids, "profile.avery"),
                idempotency_key=stage_three.idempotency_key_for(
                    "signupScoutForShowAndSellSlot", clock.token, "roster-campaign"
                ),
            )
        },
    ),
    "stale-event-version": lambda clock, ids: (
        "cancelShowAndSellSignup",
        {
            "input": stage_three.cancel_signup_input(
                lane_id(ids, "event.future"),
                lane_id(ids, "slot.first-sales"),
                lane_id(ids, "profile.avery"),
                1,
                idempotency_key=stage_three.idempotency_key_for("cancelShowAndSellSignup", clock.token, "stale"),
            )
        },
    ),
    "slot-limit": lambda clock, ids: _slot_upsert(clock, ids, "big", day_offset=9, capacity=1, step="limit-21"),
    "capacity-range": lambda clock, ids: _slot_upsert(
        clock, ids, "future", day_offset=7, capacity=0, step="capacity-0"
    ),
    "slot-board-closed": lambda clock, ids: _slot_upsert(
        clock, ids, "ended", day_offset=-1, capacity=1, step="closed-board"
    ),
    "slot-holds-scouts": lambda clock, ids: (
        "deleteShowAndSellSlot",
        {
            "input": stage_three.delete_slot_input(
                lane_id(ids, "event.future"),
                lane_id(ids, "slot.first-sales"),
                int(ids.get("version.future", "1")),
                idempotency_key=stage_three.idempotency_key_for("deleteShowAndSellSlot", clock.token, "held"),
            )
        },
    ),
    "work-over-duration": lambda clock, ids: _confirm(
        clock,
        ids,
        "four-box.morning",
        [(lane_id(ids, "slot.morning"), lane_id(ids, "profile.avery"), 190)],
        "over-duration",
    ),
    "work-batch-cap": lambda clock, ids: _confirm(
        clock,
        ids,
        "confirm",
        [
            (lane_id(ids, "slot.confirm-row"), lane_id(ids, f"profile.{name}") or f"profile-{index}", 10)
            for index, name in enumerate(("avery", "blake", "charlie", "devon"))
        ]
        + [
            (lane_id(ids, "slot.confirm-row"), f"PROFILE#synthetic-{index}", 10)
            for index in range(stage_three.MAX_WORK_LINES + 1 - 4)
        ],
        "batch-cap",
    ),
    "work-row-duplicated": lambda clock, ids: _confirm(
        clock,
        ids,
        "four-box.morning",
        [
            (lane_id(ids, "slot.morning"), lane_id(ids, "profile.avery"), 90),
            (lane_id(ids, "slot.morning"), lane_id(ids, "profile.avery"), 60),
        ],
        "duplicate-row",
    ),
    "work-window-closed": lambda clock, ids: _confirm(
        clock, ids, "future", [(lane_id(ids, "slot.first-sales"), lane_id(ids, "profile.avery"), 30)], "window"
    ),
    "edit-state-refusal": lambda clock, ids: (
        "updateShowAndSell",
        {
            "input": stage_three.update_event_input(
                lane_id(ids, "event.finalized"),
                int(ids.get("version.finalized", "1")),
                location_name="Renamed after finalizing",
                idempotency_key=stage_three.idempotency_key_for("updateShowAndSell", clock.token, "state"),
            )
        },
    ),
    "cancel-started-event": lambda clock, ids: (
        "cancelShowAndSell",
        {
            "input": stage_three.cancel_event_input(
                lane_id(ids, "event.started"),
                int(ids.get("version.started", "1")),
                "Too late to cancel",
                idempotency_key=stage_three.idempotency_key_for("cancelShowAndSell", clock.token, "started"),
            )
        },
    ),
    "concurrent-over-assignment": lambda clock, ids: (
        "assignShowAndSellInventory",
        {
            "input": stage_three.assign_inventory_input(
                lane_id(ids, "event.four-box.overlap"),
                [(lane_id(ids, "product.p01"), stage_three.FOUR_BOX_QUANTITY - 1)],
                int(ids.get("version.four-box.overlap", "1")),
                idempotency_key=stage_three.idempotency_key_for("assignShowAndSellInventory", clock.token, "overlap"),
            )
        },
    ),
    "assignment-empty-items": lambda clock, ids: (
        "assignShowAndSellInventory",
        {
            "input": stage_three.assign_inventory_input(
                lane_id(ids, "event.four-box.morning"),
                [],
                int(ids.get("version.four-box.morning", "1")),
                idempotency_key=stage_three.idempotency_key_for("assignShowAndSellInventory", clock.token, "empty"),
            )
        },
    ),
}

#: The two writes of each named race barrier, as the same ``(transport, field, variables)`` triples
#: :func:`run_race_barrier` sends.  They are built from the fixture tree so the barrier races real
#: payloads, not stand-ins.
RACE_BARRIER_CALLS: Mapping[str, Callable[[stage_three.ScenarioClock, Mapping[str, str]], list[_LaneCall]]] = {
    "allocation": lambda clock, ids: [
        (
            "assignShowAndSellInventory",
            {
                "input": stage_three.assign_inventory_input(
                    lane_id(ids, "event.four-box.morning"),
                    [(lane_id(ids, "product.p01"), stage_three.FOUR_BOX_QUANTITY)],
                    int(ids.get("version.four-box.morning", "1")),
                    idempotency_key=stage_three.idempotency_key_for(
                        "assignShowAndSellInventory", clock.token, "race-morning"
                    ),
                )
            },
        ),
        (
            "assignShowAndSellInventory",
            {
                "input": stage_three.assign_inventory_input(
                    lane_id(ids, "event.four-box.afternoon"),
                    [(lane_id(ids, "product.p01"), stage_three.FOUR_BOX_QUANTITY)],
                    int(ids.get("version.four-box.afternoon", "1")),
                    idempotency_key=stage_three.idempotency_key_for(
                        "assignShowAndSellInventory", clock.token, "race-afternoon"
                    ),
                )
            },
        ),
    ],
    "capacity": lambda clock, ids: [
        _signup(clock, ids, "future", "first-sales", "avery", "race-a"),
        _signup(clock, ids, "future", "first-sales", "blake", "race-b"),
    ],
    "version": lambda clock, ids: [
        (
            "updateShowAndSell",
            {
                "input": stage_three.update_event_input(
                    lane_id(ids, "event.future"),
                    int(ids.get("version.future", "1")),
                    location_name="First writer",
                    idempotency_key=stage_three.idempotency_key_for("updateShowAndSell", clock.token, "race-a"),
                )
            },
        ),
        (
            "updateShowAndSell",
            {
                "input": stage_three.update_event_input(
                    lane_id(ids, "event.future"),
                    int(ids.get("version.future", "1")),
                    location_name="Second writer",
                    idempotency_key=stage_three.idempotency_key_for("updateShowAndSell", clock.token, "race-b"),
                )
            },
        ),
    ],
}


class ConflictVerdict(NamedTuple):
    """One collision: what was sent, what the server answered, and whether it is the recorded refusal."""

    refusal: str
    acceptance: tuple[str, ...]
    field: str
    observed: tuple[Mapping[str, str], ...]
    result: str
    problems: tuple[str, ...]


RESULT_REFUSED = "refused-as-recorded"
RESULT_NOT_REFUSED = "not-refused"
RESULT_NO_CALL = "no-call"


def run_conflict_lane(
    transport: Transport,
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    pairs: Iterable[Mapping[str, object]] | None = None,
) -> list[ConflictVerdict]:
    """Run every §3.6.2 collision and compare each answer to the refusal table.

    Args:
        transport: the transport of the identity the walkthrough says is asking.
        clock: the scenario clock, for the ids and idempotency keys.
        ids: bound fixture ids.
        pairs: the conflict rows to run; defaults to :data:`stage_three.STAGE_THREE_CONFLICT_PAIRS`.

    Returns:
        One :class:`ConflictVerdict` per pair, in table order.  ``result`` is
        :data:`RESULT_REFUSED` only when the answer carries the table's code *and* its sentence;
        anything else — a success, a different code, an empty error list — is :data:`RESULT_NOT_REFUSED`
        with the difference named.
    """
    rows = list(pairs if pairs is not None else stage_three.STAGE_THREE_CONFLICT_PAIRS)
    verdicts: list[ConflictVerdict] = []
    for row in rows:
        refusal = str(row["refusal"])
        acceptance = tuple(stage_three.STAGE_THREE_REFUSALS[refusal])
        build = CONFLICT_CALLS.get(refusal)
        if build is None:
            verdicts.append(
                ConflictVerdict(
                    refusal=refusal,
                    acceptance=acceptance,
                    field="",
                    observed=(),
                    result=RESULT_NO_CALL,
                    problems=(
                        f"{refusal}: the §3.6.2 table names this collision and CONFLICT_CALLS builds no call for it",
                    ),
                )
            )
            continue
        field, variables = build(clock, ids)
        body = transport(field, variables)
        observed = tuple(show_sell_graphql.error_summaries(body))
        problems = tuple(stage_three.refusal_violations(refusal, observed))
        verdicts.append(
            ConflictVerdict(
                refusal=refusal,
                acceptance=acceptance,
                field=field,
                observed=observed,
                result=RESULT_NOT_REFUSED if problems else RESULT_REFUSED,
                problems=problems,
            )
        )
    return verdicts


def conflict_lane_problems(verdicts: Sequence[ConflictVerdict]) -> list[str]:
    """Every §3.6.2 collision whose answer is not the refusal the table records.

    This is the assertion the named ids need: SS-SM-05, SS-SM-06 and SS-SM-11 are only evidenced when
    each of their collisions was actually sent and actually refused with the recorded code and sentence.
    """
    problems: list[str] = []
    for verdict in verdicts:
        if verdict.result != RESULT_REFUSED:
            problems.append(f"{', '.join(verdict.acceptance)}: {verdict.refusal} ({verdict.field}) {verdict.result}")
            problems.extend(verdict.problems)
    return problems


# ---------------------------------------------------------------------------
# API-FIX-03: stale versions, and the removed member
# ---------------------------------------------------------------------------


class StepVerdict(NamedTuple):
    """One step of a fixture: the call it made, the answer it got, and whether it counts."""

    step: str
    field: str
    result: str
    detail: str


STEP_PASSED = "passed"
STEP_FAILED = "failed"
STEP_BLOCKED = "blocked"


def _blocked(step: str, field: str, detail: str) -> StepVerdict:
    return StepVerdict(step=step, field=field, result=STEP_BLOCKED, detail=detail)


def _failed(step: str, field: str, detail: str) -> StepVerdict:
    return StepVerdict(step=step, field=field, result=STEP_FAILED, detail=detail)


def _passed(step: str, field: str, detail: str) -> StepVerdict:
    return StepVerdict(step=step, field=field, result=STEP_PASSED, detail=detail)


def run_stale_version_lane(
    transport: Transport, clock: stage_three.ScenarioClock, ids: Mapping[str, str]
) -> list[StepVerdict]:
    """``API-FIX-03``: read the event's version, advance it, then submit the version that was read.

    Three calls, no waiting and no edited expectations:

    1. ``showAndSell`` reads the row and the version it answers is the version the lane believes;
    2. a legal ``upsertShowAndSellSlot`` carrying that version advances the row;
    3. ``deleteShowAndSellSlot`` carrying the *original* version must earn the recorded
       ``stale-event-version`` refusal.

    A read that answers no version is ``blocked`` — without it the fixture cannot be built, and
    ``API-FIX-01`` says that blocks the scenario rather than excusing it.
    """
    event_ref = "future"
    read_field = "showAndSell"
    read = transport(read_field, {"showAndSellId": lane_id(ids, f"event.{event_ref}")})
    answered = data_of(read, read_field)
    if not isinstance(answered, Mapping) or answered.get("version") is None:
        summary = show_sell_graphql.error_summaries(read)
        return [_blocked("read-version", read_field, f"the read answered no version: {summary or answered!r}")]
    read_version = int(answered["version"])

    advance_field, advance_variables = _slot_upsert(
        clock, ids, event_ref, day_offset=7, capacity=1, step="advance-version", version=read_version
    )
    advanced = transport(advance_field, advance_variables)
    if not succeeded(advanced, advance_field):
        summary = show_sell_graphql.error_summaries(advanced)
        return [
            _failed(
                "advance-version",
                advance_field,
                f"the advancing write did not land at version {read_version}: {summary}",
            )
        ]

    submit_field = "deleteShowAndSellSlot"
    submit = transport(
        submit_field,
        {
            "input": stage_three.delete_slot_input(
                lane_id(ids, f"event.{event_ref}"),
                lane_id(ids, "slot.midday"),
                read_version,
                idempotency_key=stage_three.idempotency_key_for("deleteShowAndSellSlot", clock.token, "stale-submit"),
            )
        },
    )
    observed = tuple(show_sell_graphql.error_summaries(submit))
    problems = stage_three.refusal_violations("stale-event-version", observed)
    if problems:
        return [
            _passed("read-version", read_field, f"version {read_version}"),
            _passed("advance-version", advance_field, f"advanced past version {read_version}"),
            _failed("submit-stale", submit_field, "; ".join(problems)),
        ]
    return [
        _passed("read-version", read_field, f"version {read_version}"),
        _passed("advance-version", advance_field, f"advanced past version {read_version}"),
        _passed("submit-stale", submit_field, f"version {read_version} refused as the table records"),
    ]


def stale_version_problems(steps: Sequence[StepVerdict]) -> list[str]:
    """The steps of the stale-version fixture that did not do what ``API-FIX-03`` requires."""
    return [
        f"{step.step} ({step.field}): {step.result} — {step.detail}" for step in steps if step.result != STEP_PASSED
    ]


def run_removed_member_lane(
    transport: Transport, clock: stage_three.ScenarioClock, ids: Mapping[str, str], entry: Mapping[str, Any]
) -> list[StepVerdict]:
    """The removed-member fixture, executed: roster read, removal, roster read, refused signup.

    The removal is the product's own ``removeUnitCampaignMembership`` (§3.4.2 keeps the row as removal
    audit), and both versions it conditions on come from the roster read that precedes it — no
    expected input is edited, which is what ``API-FIX-03`` forbids.  The step after it is the
    assertion: a signup for a REMOVED Scout is refused with the recorded sentence, and a signup for a
    Scout who was never on the roster is ``NOT_FOUND``.
    """
    steps: list[StepVerdict] = []
    profile_ref = str(entry["profile"]).removeprefix("profile.")
    campaign_ref = str(entry["campaign"]).removeprefix("campaign.")
    roster_field = "roster"
    variables = {"unitCampaignId": lane_id(ids, "unit-campaign")}

    before = transport(roster_field, variables)
    row = _roster_row(before, lane_id(ids, f"profile.{profile_ref}"))
    expected_first = _step_expectation(entry, 0)
    if (expected_first.get("expect") or {}).get("absent"):
        if row is not None:
            steps.append(_failed("roster-before", roster_field, f"{profile_ref} is already on the roster: {row}"))
            return steps
        steps.append(
            _passed("roster-before", roster_field, f"{profile_ref} is not on the roster, as the fixture plans")
        )
    else:
        if row is None:
            steps.append(_blocked("roster-before", roster_field, f"the roster answered no row for {profile_ref}"))
            return steps
        steps.append(_passed("roster-before", roster_field, f"{profile_ref} is {row.get('status')}"))

    if str(_step_expectation(entry, 1).get("write") or "") == "removeUnitCampaignMembership":
        if row is None or row.get("version") is None or row.get("guardVersion") is None:
            steps.append(
                _blocked("remove", "removeUnitCampaignMembership", "the roster row carries no version to condition on")
            )
            return steps
        remove_field, remove_variables = _removal_call(
            clock, ids, campaign_ref, int(row["version"]), int(row["guardVersion"])
        )
        removed = transport(remove_field, remove_variables)
        if not succeeded(removed, remove_field):
            steps.append(
                _failed(
                    "remove",
                    remove_field,
                    f"the removal was refused: {show_sell_graphql.error_summaries(removed)}",
                )
            )
            return steps
        steps.append(_passed("remove", remove_field, f"{profile_ref} removed at version {row['version']}"))

        after = transport(roster_field, variables)
        row_after = _roster_row(after, lane_id(ids, f"profile.{profile_ref}"))
        want = str(_status_of(entry, 2) or unit_campaign_models.MEMBERSHIP_STATUS_REMOVED)
        if row_after is None or str(row_after.get("status")) != want:
            steps.append(
                _failed("roster-after", roster_field, f"the roster answers {row_after!r}, expected status {want!r}")
            )
            return steps
        steps.append(_passed("roster-after", roster_field, f"{profile_ref} is {row_after['status']}"))

    refusal_step = _refusal_of(entry)
    if refusal_step is None:
        return steps
    field, variables = (
        CONFLICT_CALLS[refusal_step](clock, ids)
        if refusal_step != "removed-member-signup"
        else _signup(clock, ids, "future", "first-sales", profile_ref, f"removed-{profile_ref}")
    )
    answer = transport(field, variables)
    observed = tuple(show_sell_graphql.error_summaries(answer))
    problems = stage_three.refusal_violations(refusal_step, observed)
    if problems:
        steps.append(_failed("signup-after", field, "; ".join(problems)))
    else:
        steps.append(_passed("signup-after", field, f"refused as the table records ({refusal_step})"))
    return steps


def removed_member_problems(steps: Sequence[StepVerdict]) -> list[str]:
    """The steps of a removed-member fixture that did not run as planned."""
    return [
        f"{step.step} ({step.field}): {step.result} — {step.detail}" for step in steps if step.result != STEP_PASSED
    ]


def _roster_row(body: Mapping[str, Any], profile_id: str) -> Mapping[str, Any] | None:
    """The roster row for one profile, from the ``unitCampaignRoster`` answer."""
    items = ((data_of(body, "roster") or {}).get("items")) or []
    for item in items:
        if isinstance(item, Mapping) and str(item.get("profileId")) == profile_id:
            return item
    return None


def _step_expectation(entry: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    steps = entry.get("steps") or []
    return steps[index] if index < len(steps) else {}


def _status_of(entry: Mapping[str, Any], index: int) -> str | None:
    return (_step_expectation(entry, index) or {}).get("expect", {}).get("status")


def _refusal_of(entry: Mapping[str, Any]) -> str | None:
    for step in entry.get("steps") or []:
        if step.get("refusal"):
            return str(step["refusal"])
    return None


def _removal_call(
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    campaign_ref: str,
    membership_version: int,
    guard_version: int,
) -> _LaneCall:
    return (
        "removeUnitCampaignMembership",
        {
            "input": stage_two.remove_membership_input(
                lane_id(ids, "unit-campaign"),
                lane_id(ids, f"campaign.{campaign_ref}"),
                membership_version,
                guard_version,
                idempotency_key=stage_three.idempotency_key_for(
                    "removeUnitCampaignMembership", clock.token, campaign_ref
                ),
            )
        },
    )


# ---------------------------------------------------------------------------
# Race barriers — a two-thread rendezvous, not a claim about ordering
# ---------------------------------------------------------------------------

_BARRIER_TIMEOUT_SECONDS = 30.0


def run_race_barrier(
    transports: Sequence[Transport],
    calls: Sequence[_LaneCall],
    *,
    refusal: str,
) -> dict[str, Any]:
    """Send the colliding writes from separate threads that meet on a barrier before any of them starts.

    Without the rendezvous, "exactly one wins" is a story about ordering: sequential writes always
    produce that outcome, so the assertion proves nothing.  :class:`threading.Barrier` makes every
    thread arrive before any write is sent, and the arrival index each thread is handed back is the
    evidence the barrier actually engaged.

    Returns:
        ``{"arrivals": [...], "answers": [...], "succeeded": [...], "refused": [...], "violations": [...]}``.
        A clean barrier has exactly one success and every other thread answering the recorded refusal.
    """
    if len(transports) != len(calls):
        raise ValueError("a race barrier needs one transport per write")
    barrier = threading.Barrier(len(calls))
    answers: list[dict[str, Any] | None] = [None] * len(calls)
    arrivals: list[int | None] = [None] * len(calls)
    errors: list[str] = [""] * len(calls)

    def runner(index: int, transport: Transport, field: str, variables: Mapping[str, Any]) -> None:
        try:
            arrivals[index] = barrier.wait(timeout=_BARRIER_TIMEOUT_SECONDS)
            answers[index] = transport(field, variables)
        except threading.BrokenBarrierError:
            errors[index] = "the barrier broke: another thread never arrived"
        except Exception as exc:  # noqa: BLE001 - a transport that raises is part of the verdict
            errors[index] = f"{type(exc).__name__}: {exc}"

    threads = [
        threading.Thread(target=runner, args=(index, transport, field, variables), daemon=True)
        for index, (transport, (field, variables)) in enumerate(zip(transports, calls, strict=True))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_BARRIER_TIMEOUT_SECONDS * 2)

    succeeded_fields = [
        str(call[0]) for index, call in enumerate(calls) if answers[index] and succeeded(answers[index], call[0])
    ]
    refused = []
    violations: list[str] = []
    for index, (field, _variables) in enumerate(calls):
        if answers[index] is None:
            violations.append(f"write {index} ({field}) never answered: {errors[index] or 'no response'}")
            continue
        observed = show_sell_graphql.error_summaries(answers[index])
        if observed:
            problems = stage_three.refusal_violations(refusal, observed)
            refused.append(field)
            if problems:
                violations.extend(f"write {index} ({field}): {problem}" for problem in problems)
    if len(succeeded_fields) != 1:
        violations.append(
            f"the barrier expected exactly one write to land and {len(succeeded_fields)} did: {succeeded_fields}"
        )
    return {
        "arrivals": arrivals,
        "answers": answers,
        "succeeded": succeeded_fields,
        "refused": refused,
        "refusal": refusal,
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# API-FIX-01's fixture builder: FINALIZED and REOPENED
# ---------------------------------------------------------------------------
#
# The transition is the only thing the builder writes.  The row itself comes
# from the public ``createShowAndSell``, the interval and identity attributes are
# never touched, and the resulting item is validated by the model's own
# :func:`src.utils.show_and_sell_models.event_invariant_violations` before a
# byte of it is sent — so the builder cannot produce a state the server would
# refuse to read.

#: The actions the builder needs on the aggregate table.  ``docs/QA_FIXTURE_RUNBOOK.md``
#: records that ``kernelworx-qa-ue1-dev`` is denied ``dynamodb:Scan`` on ``show-and-sells``, so
#: these are *measured* at run time by the read-back, never assumed.
STATE_FIXTURE_REQUIRED_ACTIONS: tuple[str, ...] = ("dynamodb:GetItem", "dynamodb:UpdateItem")

#: The table the builder writes, resolved the same way the application resolves it.
STATE_FIXTURE_TABLE = stage_three.show_and_sells_table()

#: Raised when the identity behind a DynamoDB client cannot perform the action; the caller turns it
#: into the ``blocked`` verdict that names the grant.
_DENIED_MARKERS = ("AccessDeniedException", "AccessDenied", "UnauthorizedAccessException")


class StateFixtureDenied(RuntimeError):
    """The fixture identity is denied an action the builder needs.

    Carries the action name so the evidence record says which grant is missing, the way
    ``scripts/qa_fixture.py`` prints ``BLOCKED <table>: <action> is not granted to this identity``.
    """

    def __init__(self, action: str, detail: str) -> None:
        """Remember the denied action and the service's own words."""
        super().__init__(f"{action} is not granted to {stage_three.QA_FIXTURE_IDENTITY}: {detail}")
        self.action = action
        self.detail = detail


def wire_key(key: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """A key pair in DynamoDB wire form — every Stage 3 key attribute is a string."""
    return {name: {"S": str(value)} for name, value in key.items()}


def is_access_denied(error: BaseException) -> bool:
    """Whether a DynamoDB failure is the identity being denied, rather than a fault or a condition."""
    text = f"{type(error).__name__} {error}"
    return any(marker in text for marker in _DENIED_MARKERS)


def _state_item(
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    event_ref: str,
    *,
    status: str,
    finalization_id: str | None,
    version: int,
) -> dict[str, Any]:
    """The attribute changes one state transition writes, validated by model §5.10 before it is sent.

    ``build_show_and_sell_item`` refuses a row that breaks a §5.10 invariant, so the builder builds the
    row the create path would have written, applies the transition on top of it, and re-checks the
    result.  A ``FINALIZED`` row without ``approvedFinalizationId``, or a ``REOPENED`` row that still
    points at one, never reaches the client.

    The two pointers are **not** written as a pair.  §5.3.1 reopens by clearing ``approvedFinalizationId``
    *while retaining* ``latestFinalizationId`` — the history pointer is what §5.1.4's finalization history
    and a re-finalization's supersede chain read — so the REOPENED update says nothing about the latest
    pointer and the row keeps whatever it already holds.  A fixture that cleared it would leave a REOPENED
    event with no history to reopen against, which is a different row than the product can produce.
    """
    base = show_and_sell_models.build_show_and_sell_item(
        show_and_sell_id=lane_id(ids, f"event.{event_ref}"),
        unit_id=lane_id(ids, "unit"),
        unit_campaign_id=lane_id(ids, "unit-campaign"),
        location_name=f"Fixture {event_ref} {clock.data_id}",
        start_at=clock.iso(days=-1),
        end_at=clock.iso(days=-1, hours=3),
        created_by_account_id=lane_id(ids, "account.admin"),
        now_iso=clock.iso(),
        status=show_and_sell_models.STATUS_SCHEDULED,
        version=version,
    )
    changes: dict[str, Any] = {
        show_and_sell_models.STATUS_ATTRIBUTE: status,
        show_and_sell_models.VERSION_ATTRIBUTE: version,
        show_and_sell_models.UPDATED_AT_ATTRIBUTE: clock.iso(),
    }
    base[show_and_sell_models.STATUS_ATTRIBUTE] = status
    if finalization_id is not None:
        changes[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] = finalization_id
        changes[show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE] = finalization_id
        base[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] = finalization_id
        base[show_and_sell_models.LATEST_FINALIZATION_ID_ATTRIBUTE] = finalization_id
    else:
        changes[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] = None
        base[show_and_sell_models.APPROVED_FINALIZATION_ID_ATTRIBUTE] = None
    violations = show_and_sell_models.event_invariant_violations(base)
    if violations:
        raise AssertionError(f"the {status} fixture would write an invalid event row: {'; '.join(violations)}")
    return changes


def _state_fixture_plan(
    clock: stage_three.ScenarioClock,
    ids: Mapping[str, str],
    event_ref: str,
    *,
    state: str,
    finalization_id: str | None,
) -> dict[str, Any]:
    """The write plan one fixture state needs, with its attestation.

    ``conditionVersion`` and the version in ``changes`` are what the lane expects the row to be at, taken
    from the ids it holds.  They are provisional: :func:`apply_state_fixture` re-reads the row and derives
    both the condition **and** the version it writes from that read, because a row the lane has not read
    may have moved.
    """
    version = int(ids.get(f"version.{event_ref}", "1")) + 1
    key = show_and_sell_models.event_metadata_key(lane_id(ids, f"event.{event_ref}"))
    return {
        "state": state,
        "table": STATE_FIXTURE_TABLE,
        "key": key,
        "changes": _state_item(clock, ids, event_ref, status=state, finalization_id=finalization_id, version=version),
        "conditionVersion": version - 1,
        "requiredActions": STATE_FIXTURE_REQUIRED_ACTIONS,
        "attestation": (
            f"{state} was produced by the documented Stage 3 fixture builder, not by {state.lower() + 'ShowAndSell'}: "
            f"§5's mutation is absent from this SDL. The builder changed only status, the approved finalization "
            "pointer, the version and updatedAt of the row createShowAndSell wrote, and wrote no FINALIZATION# row — "
            "that row family is §5's, so a Stage 3 lane reading finalization detail from this fixture is reading a "
            "fixture, not a finalization."
        ),
        "note": stage_three.BUILDER_ONLY_STATE_FIXTURE_NOTE,
    }


def finalize_event_fixture_writes(
    clock: stage_three.ScenarioClock, ids: Mapping[str, str], *, event_ref: str = "finalized"
) -> dict[str, Any]:
    """The FINALIZED fixture: a conditioned update of the event row the lane created.

    ``API-FIX-01`` requires an ACTIVE/ENDED/REOPENED/FINALIZED/CANCELLED fixture; §5's
    ``finalizeShowAndSell`` is not in this SDL, so this is the documented test fixture
    FIX-AC-04 allows, and :func:`apply_state_fixture` reports blocked naming the grant when the QA
    identity cannot perform it.
    """
    finalization_id = f"FINAL#{clock.token}-finalized"
    return _state_fixture_plan(
        clock, ids, event_ref, state=show_and_sell_models.STATUS_FINALIZED, finalization_id=finalization_id
    )


def reopen_event_fixture_writes(
    clock: stage_three.ScenarioClock, ids: Mapping[str, str], *, event_ref: str = "reopened"
) -> dict[str, Any]:
    """The REOPENED fixture: the same update with ``approvedFinalizationId`` cleared and the history kept.

    The model refuses a ``REOPENED`` row that still points at an approved finalization (§5.10), so
    clearing that pointer is part of the fixture rather than a detail a later read has to forgive.  What
    the fixture must not do is clear ``latestFinalizationId`` too: §5.3.1 reopens "while retaining
    latestFinalizationId", and that pointer is what the finalization history and a re-finalization's
    supersede chain hang off.  The update therefore names only the approved pointer, and the row's own
    latest pointer survives it untouched.
    """
    return _state_fixture_plan(clock, ids, event_ref, state=show_and_sell_models.STATUS_REOPENED, finalization_id=None)


def apply_state_fixture(
    client: Any, plan: Mapping[str, Any], *, on_read: Callable[[Mapping[str, Any]], None] | None = None
) -> dict[str, str]:
    """Apply one state fixture and prove it by reading the row back.

    Three calls, each of which can be the one that says the fixture cannot be built:

    1. ``get_item`` with ``ConsistentRead`` — the row the public create wrote, and the action the
       identity may or may not have;
    2. ``update_item`` — the transition, conditioned on **the version that read answered**, so a
       concurrent write makes this fixture stale rather than silently overwritten;
    3. ``get_item`` again, also consistent — the read-back.  A row that still answers the old status is
       a fixture that did not happen, which is a ``failed`` verdict, not an observation.

    The low-level client speaks in DynamoDB wire form: a read answers ``{"S": "FINALIZED"}``, not
    ``"FINALIZED"``.  Every comparison here goes through :func:`_python_row` first, so the fixture is
    judged on the value the table holds rather than on the container it arrives in.

    Args:
        client: a DynamoDB client (or a stand-in with the same three calls).
        plan: the plan from :func:`finalize_event_fixture_writes` or :func:`reopen_event_fixture_writes`.
        on_read: called with the decoded before-image, so a lane can record what the row was.

    Returns:
        A cleanup-vocabulary row: ``observed`` when the read-back confirms the state, ``blocked`` when
        an action is denied, ``failed`` when the row is missing, carries no version to condition on, or
        answers a state the fixture did not write.
    """
    table, key = str(plan["table"]), wire_key(plan["key"])

    def action() -> str:
        try:
            before = client.get_item(TableName=table, Key=key, ConsistentRead=True)
        except Exception as exc:  # noqa: BLE001 - the reason it failed decides the verdict
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:GetItem on {table}: {exc}") from exc
            raise
        item = before.get("Item")
        if not item:
            raise AssertionError(
                f"no event row to transition: the lane's createShowAndSell wrote nothing at {plan['key']}"
            )
        before_image = _python_row(item)
        if on_read is not None:
            on_read(before_image)
        read_version = before_image.get(show_and_sell_models.VERSION_ATTRIBUTE)
        if read_version is None:
            raise AssertionError(
                f"the row at {plan['key']} carries no {show_and_sell_models.VERSION_ATTRIBUTE}, so the fixture "
                "has no version to condition on and would be writing blind"
            )
        # The version the fixture writes is derived from the row it read, exactly like the version it
        # conditions on.  A plan built before the read cannot know where the row is: if the SET carried the
        # plan's own guess, a fixture would condition on version 12 and write version 2, moving the event's
        # optimistic-locking history backwards and leaving every later version check in the lane bogus.
        next_version = int(read_version) + 1
        changes = dict(plan["changes"], **{show_and_sell_models.VERSION_ATTRIBUTE: next_version})
        try:
            client.update_item(
                TableName=table,
                Key=key,
                UpdateExpression=_update_expression(changes),
                ExpressionAttributeNames=_expression_names(changes),
                ConditionExpression="#version = :expected",
                ExpressionAttributeValues=_condition_values(changes, int(read_version)),
            )
        except Exception as exc:  # noqa: BLE001
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:UpdateItem on {table}: {exc}") from exc
            raise
        try:
            after = client.get_item(TableName=table, Key=key, ConsistentRead=True)
        except Exception as exc:  # noqa: BLE001
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:GetItem (read-back) on {table}: {exc}") from exc
            raise
        row = after.get("Item")
        if not row:
            raise AssertionError(f"the read-back answers nothing at {plan['key']} after the transition was accepted")
        written = _python_row(row)
        if str(written.get(show_and_sell_models.STATUS_ATTRIBUTE)) != str(plan["state"]):
            raise AssertionError(
                f"read-back status is {written.get(show_and_sell_models.STATUS_ATTRIBUTE)!r}, "
                f"the fixture wrote {plan['state']!r}"
            )
        violations = show_and_sell_models.event_invariant_violations(written)
        if violations:
            raise AssertionError(f"the fixture row breaks the model's invariants: {'; '.join(violations)}")
        written_version = written.get(show_and_sell_models.VERSION_ATTRIBUTE)
        if int(written_version) != next_version:
            raise AssertionError(
                f"the read-back version is {written_version!r}; the fixture read version {read_version} and "
                f"had to write {next_version}, so the event's version history is not intact"
            )
        return (
            f"{plan['state']} written and read back at {table}/{plan['key']['pk']}/{plan['key']['sk']}, "
            f"version {read_version} -> {written_version}; {plan['attestation']}"
        )

    return stage_two.run_cleanup_step(f"API-FIX-01 {plan['state']} fixture", action)


def _python_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A DynamoDB item in wire form, or a plain mapping, as the plain mapping the model validates."""
    return {name: _python_value(value) for name, value in row.items()}


def _python_value(value: Any) -> Any:
    """One AttributeValue decoded to the Python value the model works in."""
    if (
        not isinstance(value, Mapping)
        or not value
        or not (set(value) <= {"S", "N", "BOOL", "NULL", "L", "M", "SS", "NS"})
    ):
        return value
    marker, payload = next(iter(value.items()))
    if marker == "NULL":
        return None
    if marker == "N":
        return _number(payload)
    if marker == "L":
        return [_python_value(item) for item in payload]
    if marker == "M":
        return {name: _python_value(item) for name, item in payload.items()}
    return payload


def _number(value: Any) -> Any:
    try:
        return int(value)
    except TypeError, ValueError:
        return value


def _update_expression(changes: Mapping[str, Any]) -> str:
    """The SET clause for the fixture's own attributes — the transition and nothing else."""
    return "SET " + ", ".join(f"#{name} = :{name}" for name in changes)


def _expression_names(changes: Mapping[str, Any]) -> dict[str, str]:
    return {f"#{name}": name for name in changes}


def _condition_values(changes: Mapping[str, Any], read_version: int) -> dict[str, dict[str, Any]]:
    """The values for the write **and** its version condition, both taken from the row that was read.

    The condition is the version the consistent read answered, so a concurrent write makes this fixture
    stale rather than quietly overwritten; the written version is that same answer plus one, so the
    fixture can never move an event's version backwards.
    """
    values = _expression_values(changes)
    values[":expected"] = {"N": str(read_version)}
    return values


def _expression_values(changes: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for name, value in changes.items():
        if value is None:
            values[f":{name}"] = {"NULL": True}
        elif isinstance(value, bool):
            values[f":{name}"] = {"BOOL": value}
        elif isinstance(value, int):
            values[f":{name}"] = {"N": str(value)}
        else:
            values[f":{name}"] = {"S": str(value)}
    return values


# ---------------------------------------------------------------------------
# Lane cleanup: plan, delete, read back, canary
# ---------------------------------------------------------------------------


def run_stage_three_cleanup(
    client: Any,
    *,
    lane: str,
    plan: Sequence[Mapping[str, Any]],
    canary: Mapping[str, Any],
    sweep_tokens: Sequence[str] = (),
    sweep_report: Sequence[str] | None = None,
    sweep_exit_code: int | None = None,
    sweep_runner: Callable[[Sequence[str]], tuple[int, list[str], list[str]]] | None = None,
    proven_residue: Mapping[str, str] | None = None,
    ledger: stage_three.WriteLedger | None = None,
    ids: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Delete every row this lane planned, read each one back, and prove another lane's canary survived.

    Each planned row runs through :func:`stage_two.run_cleanup_step`, so nothing a step reports can be
    softer than a verdict:

    * a row whose key still holds a ``<placeholder>`` is ``blocked`` — the lane never identified it, so
      deleting a guess is not cleanup;
    * a row owned by a *different* lane token is refused outright and is a ``failed`` row: a lane's
      teardown may not reach into another lane's rows, and this is the rule the canary proves held;
    * a ``delete_item`` that returns without an error is not enough — the ``get_item`` read-back must
      answer nothing, or the row is ``failed`` (the same rule ``scripts/qa_fixture.py`` applies when it
      prints ``LEFT``);
    * an ``AccessDeniedException`` is ``blocked`` naming the action, never an empty table;
    * the canary must still be present afterwards, or the whole teardown is ``failed``.

    Returns:
        Cleanup-vocabulary rows, one per planned row plus the canary step and the sweep row.
    """
    rows: list[dict[str, str]] = []
    sweep = next((row for row in plan if str(row.get("kind") or "") == "sweep"), None)
    seen: set[tuple[str, str, str]] = set()

    def address(row: Mapping[str, Any]) -> tuple[str, str, str]:
        key = dict(row.get("key") or {})
        return (str(row.get("table") or ""), str(key.get("pk", "")), str(key.get("sk", "")))

    sent = set(ledger.keys()) if ledger is not None else None
    for planned in plan:
        if str(planned.get("kind") or "") == "sweep":
            continue
        seen.add(address(planned))
        step = _delete_step(client, lane, planned)
        if str(planned.get("kind") or "") == "marker" and sent is not None:
            step = _require_recorded(planned, sent, step)
        rows.append(stage_two.run_cleanup_step(str(planned.get("acceptance") or ""), step))

    # Whatever this lane actually wrote, whether or not the plan foresaw it.  The version-advancing slot
    # write and the winner of each race barrier are the cases: they are real accepted mutations whose
    # markers are real rows, and a plan read off the fixture tree does not name them.
    if ledger is not None:
        for recorded in ledger.marker_rows(dict(ids or {})):
            if address(recorded) in seen:
                continue
            seen.add(address(recorded))
            rows.append(stage_two.run_cleanup_step(str(recorded["acceptance"]), _delete_step(client, lane, recorded)))

    rows.append(
        stage_two.run_cleanup_step(str(canary.get("acceptance") or "canary"), _canary_step(client, lane, canary))
    )
    rows.append(
        _sweep_row(
            sweep or {"acceptance": "§2.8.7"},
            tokens=sweep_tokens,
            report=sweep_report,
            exit_code=sweep_exit_code,
            runner=sweep_runner,
            proven_residue=proven_residue,
        )
    )
    return rows


SWEEP_CLASSES: tuple[tuple[str, str], ...] = (
    ("LEFT", "left"),
    ("FAILED", "failed"),
    ("UNKNOWN", "unknown"),
    ("HISTORY", "history"),
)


def _sweep_row(
    planned: Mapping[str, Any],
    *,
    tokens: Sequence[str],
    report: Sequence[str] | None,
    exit_code: int | None,
    runner: Callable[[Sequence[str]], tuple[int, list[str], list[str]]] | None = None,
    proven_residue: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The residue sweep, taken by running the sanctioned sweeper and judged by its own report.

    Three rules make this step impossible to satisfy by writing about it:

    * the sweep is **always** accounted for.  A lane whose plan omits the row still owes the evidence, so
      dropping the row from the plan is not a way to skip the gate;
    * when the caller supplies no report, the sanctioned sweeper is run here
      (:func:`tests.e2e.utils.show_sell_stage2_support.fixture_sweep` is the only supported way to delete
      fixture residue), and a lane with no typed tokens cannot run it, so it blocks;
    * the verdict is :func:`tests.e2e.utils.show_sell_stage2_support.sweep_verdict` over the report's own
      classes, including its ``unproven`` input: a table this identity cannot read is accepted residue
      only when the record names the application read that proves the rows are still standing
      (:data:`tests.e2e.utils.show_sell_stage3_support.STAGE_THREE_RESIDUE_PROOF`).  An unreadable table
      with no such read is not clean, whatever the exit code says.
    """
    acceptance = str(planned.get("acceptance") or "§2.8.7")
    if report is None or exit_code is None:
        if not tokens:
            return stage_two.cleanup_row(
                acceptance,
                "the typed-token sweep has no lane tokens, so the sanctioned sweeper cannot be run for this lane",
                stage_two.CLEANUP_BLOCKED,
            )
        exit_code, _blocked_lines, report = (runner or stage_two.fixture_sweep)(list(tokens))
    classes = {name: [line for line in report if line.startswith(prefix)] for prefix, name in SWEEP_CLASSES}
    blocked = [line for line in report if line.startswith("BLOCKED")]
    proof = dict(stage_three.STAGE_THREE_RESIDUE_PROOF if proven_residue is None else proven_residue)
    unproven = [line for line in blocked if _blocked_table(line) not in proof]
    proven = [
        f"{_blocked_table(line)} by {proof[_blocked_table(line)]}" for line in blocked if _blocked_table(line) in proof
    ]
    kept = [line for line in report if line.startswith("kept")]
    deleted = sum(1 for line in report if line.startswith("deleted row"))
    counted = "; ".join(f"{name}={len(lines)}" for name, lines in classes.items() if lines)
    return {
        "acceptance": acceptance,
        "summary": (
            f"scripts/qa_fixture.py sweep --lane {' '.join(tokens)} exited {exit_code}: deleted={deleted}, "
            f"kept={len(kept)}, {counted or 'no surviving class'}"
            + (f"; blocked residue proven by a product read: {'; '.join(proven)}" if proven else "")
            + (f"; blocked residue no product read proves: {'; '.join(unproven)}" if unproven else "")
        ),
        "result": stage_two.sweep_verdict(
            left=classes["left"],
            failed=classes["failed"],
            unknown=classes["unknown"],
            history=classes["history"],
            blocked=blocked,
            unproven=unproven,
            exit_code=exit_code,
        ),
    }


def _blocked_table(line: str) -> str:
    """The table one ``BLOCKED <table>: <action> …`` report line names."""
    parts = line.removeprefix("BLOCKED").strip().split(":", 1)
    return parts[0].strip()


def _require_recorded(planned: Mapping[str, Any], sent: set[str], step: Callable[[], str]) -> Callable[[], str]:
    """A marker row is only this lane's to clean if the lane recorded sending the write that wrote it.

    A marker for a key that was never sent is a row that does not exist, and a read-back confirming an
    absence is not evidence of a cleanup — it is the false clean this gate exists to prevent.  So a planned
    marker whose key is absent from the ledger blocks the step and names the key, and the lane either
    recorded the write or it did not.
    """
    key = str(planned.get("idempotencyKey") or planned.get("key", {}).get("sk", ""))

    def action() -> str:
        if key not in sent:
            raise stage_two.CleanupBlocked(
                f"marker {key}: the lane recorded no accepted write with this key, so there is no marker "
                "here to clean and an absent read-back would prove nothing"
            )
        return step()

    return action


def _delete_step(client: Any, lane: str, planned: Mapping[str, Any]) -> Callable[[], str]:
    """One plan row turned into a delete-and-read-back action, with its refusals."""
    key = dict(planned.get("key") or {})
    table = str(planned.get("table") or "")
    kind = str(planned.get("kind") or "")
    owner = str(planned.get("lane") or "")

    def action() -> str:
        if not key or not table:
            raise AssertionError(f"{kind}: the plan names no table and key, so there is nothing to delete")
        if owner != lane:
            raise AssertionError(f"{kind}: the row is owned by lane {owner!r}, not this lane {lane!r}")
        unbound = unbound_key_cells(key)
        if unbound:
            raise stage_two.CleanupBlocked(f"{kind}: key cells {list(unbound)} were never bound to an id")
        wire = wire_key(key)
        try:
            client.delete_item(TableName=table, Key=wire)
        except Exception as exc:  # noqa: BLE001 - the reason decides the verdict
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:DeleteItem on {table}: {exc}") from exc
            raise
        try:
            after = client.get_item(TableName=table, Key=wire, ConsistentRead=True)
        except Exception as exc:  # noqa: BLE001
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:GetItem on {table}: {exc}") from exc
            raise
        if after.get("Item"):
            raise AssertionError(f"{kind}: the row is still there after delete_item returned — the delete did not take")
        return f"{kind} {key} is gone: get_item answers nothing"

    return action


def _canary_step(client: Any, lane: str, canary: Mapping[str, Any]) -> Callable[[], str]:
    """The canary check: a row a *different* lane token owns must still be readable."""
    key = dict(canary.get("key") or {})
    table = str(canary.get("table") or "")
    owner = str(canary.get("lane") or "")

    def action() -> str:
        if owner == lane:
            raise AssertionError("a canary must belong to a different lane token, or it proves nothing")
        if not key or not table:
            raise AssertionError("the canary names no table and key")
        wire = wire_key(key)
        try:
            found = client.get_item(TableName=table, Key=wire, ConsistentRead=True)
        except Exception as exc:  # noqa: BLE001
            if is_access_denied(exc):
                raise stage_two.CleanupBlocked(f"dynamodb:GetItem on {table}: {exc}") from exc
            raise
        if not found.get("Item"):
            raise AssertionError(
                f"lane {owner}'s canary row {key} is gone: this lane's teardown reached outside its own rows"
            )
        return f"lane {owner}'s canary row {key} survived this lane's teardown"

    return action


# ---------------------------------------------------------------------------
# The ICS captures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _ics_stamp(instant: str) -> str:
    """An ISO instant in the ``DTSTAMP`` spelling RFC 5545 and ``icsUtc`` both use."""
    return instant.replace("-", "").replace(":", "").split(".")[0]


def invite_capture_names() -> tuple[str, ...]:
    """The captured ``buildInvite`` bytes the validator is fed."""
    return stage_three.ICS_CAPTURE_NAMES


def read_invite_capture(name: str) -> str:
    """One capture, byte for byte as the browser wrote it.

    ``newline=''`` matters: reading in text mode with universal newlines rewrites the CRLF pairs the
    invite is built with, and a validator that accepts LF is validating a file nobody downloaded.
    """
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def validate_invite_captures() -> dict[str, Any]:
    """Validate both captures of one signup's invite and compare their UIDs to the DTO that made them.

    The UID is rebuilt from :data:`stage_three.ICS_CAPTURE_DTO` rather than read out of the file, so a
    capture that is a hand-written stand-in — a plausible ``.ics`` nobody downloaded — fails here instead
    of passing the shape check.  The two ``DTSTAMP`` values are compared to
    :data:`stage_three.ICS_CAPTURE_CLOCKS` for the same reason: the pair is one signup built twice, and
    only the clock differs.

    Returns:
        ``{"uid", "expectedUid", "first", "repeat", "uidStable", "uidMatchesDto", "dtstamps",
        "dtstampsMatchClocks", "maxPhysicalOctets", "foldOctets"}`` — the two validator problem tuples,
        whether the UID survived the second download (CAL-01) and matches the DTO it was built from, the
        two stamps against the two documented clocks, and the widest physical line against the emitter's
        own fold budget.
    """
    first_name, repeat_name = stage_three.ICS_CAPTURE_NAMES
    first = read_invite_capture(first_name)
    repeat = read_invite_capture(repeat_name)
    first_uid = stage_three.ics_uid(first)
    repeat_uid = stage_three.ics_uid(repeat)
    expected_uid = stage_three.calendar_invite_uid(
        str(stage_three.ICS_CAPTURE_DTO["unitCampaignId"]),
        str(stage_three.ICS_CAPTURE_DTO["showAndSellId"]),
        str(stage_three.ICS_CAPTURE_DTO["slotId"]),
        str(stage_three.ICS_CAPTURE_DTO["profileId"]),
    )
    dtstamps = (
        stage_three.ics_property_value(first, "DTSTAMP"),
        stage_three.ics_property_value(repeat, "DTSTAMP"),
    )
    return {
        "uid": first_uid,
        "expectedUid": expected_uid,
        "first": stage_three.validate_ics(first, expected_uid),
        "repeat": stage_three.validate_ics(repeat, expected_uid),
        "uidStable": bool(first_uid) and first_uid == repeat_uid,
        "uidMatchesDto": first_uid == expected_uid and repeat_uid == expected_uid,
        "repeatUid": repeat_uid,
        "dtstamps": dtstamps,
        "dtstampsMatchClocks": dtstamps == tuple(_ics_stamp(stamp) for stamp in stage_three.ICS_CAPTURE_CLOCKS),
        "maxPhysicalOctets": max(stage_three.ics_physical_line_octets(first), default=0),
        "foldOctets": stage_three.ICS_FOLD_OCTETS,
    }
