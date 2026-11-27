"""Wave 6.1 — the Kernel's rounding draft, stored without approving a cent (§5.1.3, FIN-M-01).

Resolver-level cases for ``updateShowAndSellRoundingDraft``: the valid update that
assigns the leftover cent of a $100 three-way split and answers the updated preview
with no approved credit, the refusals the work order names (ineligible participant,
duplicate entry, negative cents, over-sum), the stale ``expectedVersion`` race, and
the idempotent retry that answers the same preview without writing a second draft.
Everything runs through ``handle_unit_operation`` against moto, and the pool under
draft is written by ``createShowAndSellSale`` rather than seeded — the ceiling a
draft is bounded by is computed live from those rows, exactly as the preview computes
it, so a draft can never be legal against one answer and illegal against the next.

``AUTH-U`` is asserted here and in ``test_unit_tenant_wiring``; the ``REOPENED`` leg
is seeded, per Amendment A — no reopening writer ships on this card, and a row
storing ``REOPENED`` is a row §5.3's future writer would produce.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import UPDATE_ROUNDING_DRAFT_FIELD
from src.utils import show_and_sell_finalization_models as fm
from src.utils import show_and_sell_models as ssm
from tests.unit.show_sell_fixtures import (
    assert_is_error,
    seed_show_sell_fixtures,
)
from tests.unit.test_show_and_sell_finalization_preview import (  # the §5.1.2 scenario: ended table, three Scouts
    A_SCOUT,
    B_SCOUT,
    C_SCOUT,
    ENDED_EVENT,
    _call,
    _confirm,
    _ended_event,
    _ok,
    _preview,
    _sell,
)

DRAFT_EVENT = ENDED_EVENT


def _draft(
    caller: Any = "Avery",
    *,
    event_id: str = DRAFT_EVENT,
    assignments: List[Dict[str, Any]],
    version: int,
    key: str,
) -> Any:
    return _call(
        UPDATE_ROUNDING_DRAFT_FIELD,
        caller,
        mutation={
            "showAndSellId": event_id,
            "assignments": assignments,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": key},
        },
    )


def _version_of(show_and_sells: Any, event_id: str = DRAFT_EVENT) -> int:
    return int(ssm.read_show_and_sell(event_id)[ssm.VERSION_ATTRIBUTE])  # type: ignore[index]


def _stored_draft(show_and_sells: Any, event_id: str = DRAFT_EVENT) -> Dict[str, int]:
    event = ssm.read_show_and_sell(event_id)
    raw = dict(event.get(ssm.ROUNDING_DRAFT_ATTRIBUTE) or {}) if event else {}
    return {str(k): int(v) for k, v in raw.items()}


def _hundred_dollar_three_way(world: Dict[str, Any]) -> int:
    """The AC-55 table: $100 three ways, $33.33 each, one cent unassigned."""
    _ended_event(world, boxes=20)
    _sell(world, boxes=20, key="pool-100-draft")
    for scout in (A_SCOUT, B_SCOUT, C_SCOUT):
        _confirm(world, scout, 10)
    return _version_of(world["show_and_sells"])


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world plus the tables finalization drafting touches."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    from tests.unit.test_show_and_sell_sales import _offer_products

    _offer_products(catalogs_table, 4)
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "catalogs": catalogs_table,
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
    }


# --- The valid update (FIN-M-01-01) ----------------------------------------------


def test_a_valid_draft_assigns_the_leftover_cent_and_answers_the_updated_preview(
    world: Dict[str, Any],
) -> None:
    """FIN-M-01-01 / AC-55: the cent goes where the Kernel points it, and nothing is approved."""
    version = _hundred_dollar_three_way(world)

    answer = _ok(_draft(assignments=[{"profileId": A_SCOUT, "cents": 1}], version=version, key="draft-1"))
    assert answer["wholePoolCents"] == 10000
    assert answer["unassignedCents"] == 1
    by_profile = {row["profileId"]: row for row in answer["baseAllocations"]}
    assert by_profile[A_SCOUT]["roundingCreditCents"] == 1
    assert by_profile[A_SCOUT]["amountCents"] == 3334
    assert by_profile[B_SCOUT]["amountCents"] == 3333
    assert answer["eventVersion"] == version + 1

    # Stored on the event row and nowhere else: no credit, no total, version moved once.
    assert _stored_draft(world["show_and_sells"]) == {A_SCOUT: 1}
    assert not [
        row
        for row in world["show_and_sells"].scan()["Items"]
        if str(row.get("entityType", "")) in (fm.CREDIT_ENTITY_TYPE, fm.FINALIZATION_ENTITY_TYPE, fm.TOTAL_ENTITY_TYPE)
        or str(row.get("sk", "")).startswith(f"{fm.CREDIT_SK_PREFIX}#")
        or str(row.get("sk", "")).startswith("FINALIZATION#")
    ]
    assert not [
        row
        for row in world["unit_campaigns"].scan()["Items"]
        if str(row.get("entityType", "")) == fm.TOTAL_ENTITY_TYPE or str(row.get("sk", "")) == fm.SHOW_AND_SELL_TOTAL_SK
    ]

    # The preview repeats exactly what the mutation answered.
    assert _ok(_preview()) == answer


def test_a_draft_is_one_complete_answer_replacing_the_last_one(world: Dict[str, Any]) -> None:
    """A participant left out of the new draft holds zero draft cents afterwards."""
    version = _hundred_dollar_three_way(world)
    _ok(_draft(assignments=[{"profileId": A_SCOUT, "cents": 1}], version=version, key="draft-first"))

    moved = _ok(
        _draft(
            assignments=[{"profileId": B_SCOUT, "cents": 1}],
            version=_version_of(world["show_and_sells"]),
            key="draft-second",
        )
    )
    by_profile = {row["profileId"]: row for row in moved["baseAllocations"]}
    assert by_profile[A_SCOUT]["roundingCreditCents"] == 0
    assert by_profile[B_SCOUT]["roundingCreditCents"] == 1
    assert _stored_draft(world["show_and_sells"]) == {B_SCOUT: 1}

    # The empty draft clears the map: drafting is work in progress, undoing included.
    cleared = _ok(_draft(assignments=[], version=_version_of(world["show_and_sells"]), key="draft-clear"))
    assert all(row["roundingCreditCents"] == 0 for row in cleared["baseAllocations"])
    assert _stored_draft(world["show_and_sells"]) == {}


# --- The refusals (FIN-M-01-02) ---------------------------------------------------


def test_an_ineligible_participant_is_refused_and_writes_nothing(world: Dict[str, Any]) -> None:
    version = _hundred_dollar_three_way(world)
    version_before = _version_of(world["show_and_sells"])

    error = assert_is_error(
        _draft(assignments=[{"profileId": "PROFILE#never-confirmed", "cents": 1}], version=version, key="draft-bad"),
        "CONFLICT",
    )
    assert "eligible confirmed participant" in error["message"]
    assert _version_of(world["show_and_sells"]) == version_before
    assert _stored_draft(world["show_and_sells"]) == {}


def test_a_participant_named_twice_in_one_draft_is_refused(world: Dict[str, Any]) -> None:
    """The draft is a complete answer; resolving a duplicate would guess at intent with money on the line."""
    version = _hundred_dollar_three_way(world)

    error = assert_is_error(
        _draft(
            assignments=[{"profileId": A_SCOUT, "cents": 1}, {"profileId": A_SCOUT, "cents": 0}],
            version=version,
            key="draft-dupe",
        ),
        "CONFLICT",
    )
    assert "appear twice" in error["message"]
    assert _stored_draft(world["show_and_sells"]) == {}


def test_negative_cents_are_refused_as_invalid_input(world: Dict[str, Any]) -> None:
    version = _hundred_dollar_three_way(world)

    assert_is_error(
        _draft(assignments=[{"profileId": A_SCOUT, "cents": -1}], version=version, key="draft-negative"),
        "INVALID_INPUT",
    )
    assert _stored_draft(world["show_and_sells"]) == {}


def test_a_draft_above_the_unassigned_cents_is_refused_whole(world: Dict[str, Any]) -> None:
    """§7.2: the ceiling is the split's residue — one cent exists, two cannot be assigned."""
    version = _hundred_dollar_three_way(world)

    error = assert_is_error(
        _draft(
            assignments=[{"profileId": A_SCOUT, "cents": 1}, {"profileId": B_SCOUT, "cents": 1}],
            version=version,
            key="draft-oversum",
        ),
        "CONFLICT",
    )
    assert "more cents than the split left unassigned" in error["message"]
    assert _stored_draft(world["show_and_sells"]) == {}


def test_assignments_that_are_not_profile_cents_entries_are_refused(world: Dict[str, Any]) -> None:
    version = _hundred_dollar_three_way(world)

    assert_is_error(_draft(assignments=["not-an-entry"], version=version, key="draft-shape"), "INVALID_INPUT")  # type: ignore[list-item]
    answer = _call(
        UPDATE_ROUNDING_DRAFT_FIELD,
        "Avery",
        mutation={
            "showAndSellId": DRAFT_EVENT,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": "draft-no-assignments"},
        },
    )
    assert_is_error(answer, "INVALID_INPUT")


# --- Versions and retries (VER-01, IDEM) ------------------------------------------


def test_a_stale_expected_version_writes_nothing(world: Dict[str, Any]) -> None:
    """VER-01: a draft read against a moved event loses cleanly and is retried against the fresh preview."""
    version = _hundred_dollar_three_way(world)
    _ok(_draft(assignments=[{"profileId": A_SCOUT, "cents": 1}], version=version, key="draft-winner"))

    error = assert_is_error(
        _draft(assignments=[{"profileId": B_SCOUT, "cents": 1}], version=version, key="draft-loser"),
        "CONFLICT",
    )
    assert "changed since you read it" in error["message"]
    assert _stored_draft(world["show_and_sells"]) == {A_SCOUT: 1}


def test_an_idempotent_retry_answers_the_same_preview_and_writes_one_draft(world: Dict[str, Any]) -> None:
    """IDEM: the retry of a committed draft answers its preview, not a CONFLICT about its own write."""
    version = _hundred_dollar_three_way(world)
    assignments = [{"profileId": C_SCOUT, "cents": 1}]

    first = _ok(_draft(assignments=assignments, version=version, key="draft-retry"))
    second = _ok(_draft(assignments=assignments, version=version, key="draft-retry"))

    assert first == second
    assert first["eventVersion"] == version + 1
    assert _version_of(world["show_and_sells"]) == version + 1
    assert _stored_draft(world["show_and_sells"]) == {C_SCOUT: 1}

    # The same key with different assignments is a different request wearing a used
    # name: refused on the fingerprint, and the stored draft does not move.
    mismatched = assert_is_error(
        _draft(assignments=[{"profileId": B_SCOUT, "cents": 1}], version=version, key="draft-retry"),
        "INVALID_INPUT",
    )
    assert mismatched is not None
    assert _stored_draft(world["show_and_sells"]) == {C_SCOUT: 1}
    assert _version_of(world["show_and_sells"]) == version + 1


# --- State matrix (pre-approval and REOPENED only) --------------------------------


def test_a_finalized_or_cancelled_event_refuses_the_draft(world: Dict[str, Any]) -> None:
    """The draft belongs to work in progress; an approved answer is revised by reopening, not drafting."""
    _seed_finalized = ssm.STATUS_FINALIZED
    _seed_event_row(world, "SSE#draft-finalized", status=_seed_finalized)
    error = assert_is_error(
        _draft(
            event_id="SSE#draft-finalized", assignments=[{"profileId": A_SCOUT, "cents": 0}], version=1, key="d-fin"
        ),
        "CONFLICT",
    )
    assert "cannot be edited" in error["message"]

    _seed_event_row(world, "SSE#draft-cancelled", status=ssm.STATUS_CANCELLED)
    assert_is_error(
        _draft(event_id="SSE#draft-cancelled", assignments=[], version=1, key="d-can"),
        "CONFLICT",
    )


def test_a_reopened_event_accepts_draft_corrections(world: Dict[str, Any]) -> None:
    """§3.5's draft window: a reopened event's rounding numbers are work in progress again.

    Seeded, per Amendment A: no reopening writer ships on this card, and a row
    storing REOPENED is exactly the row §5.3 will write.
    """
    _seed_event_row(world, "SSE#draft-reopened", status=ssm.STATUS_REOPENED)
    version = _version_of(world["show_and_sells"], "SSE#draft-reopened")

    answer = _ok(_draft(event_id="SSE#draft-reopened", assignments=[], version=version, key="d-reopen"))
    assert answer["wholePoolCents"] == 0
    assert answer["eventVersion"] == version + 1
    assert answer["issues"] == []  # REOPENED answers as ended-and-awaiting: no EVENT_NOT_ENDED


def test_only_the_events_unit_admin_drafts(world: Dict[str, Any]) -> None:
    """AUTH-U: a removed admin, another Unit's admin, and an unauthenticated caller all get no existence."""
    _ended_event(world, boxes=4)
    version = _version_of(world["show_and_sells"])
    for caller in ("Blake", "Riley"):
        error = assert_is_error(_draft(caller, assignments=[], version=version, key="d-auth"), "NOT_FOUND")
        assert "not found" in error["message"]
    assert_is_error(_draft(None, assignments=[], version=version, key="d-anon"), "UNAUTHORIZED")
    assert _version_of(world["show_and_sells"]) == version


def _seed_event_row(world: Dict[str, Any], event_id: str, *, status: str) -> None:
    """A stored-state event row (FINALIZED/CANCELLED/REOPENED) — states the clock never derives."""
    from tests.unit.test_show_and_sell_sales import _seed_event

    _seed_event(
        world["show_and_sells"],
        event_id,
        status=status,
    )
