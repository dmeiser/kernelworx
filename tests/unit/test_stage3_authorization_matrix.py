"""Leaf 3.7.5 — the Stage 3 authorization matrix: who may reach each of the seventeen fields.

§3.7.5 asks for one verification sweep over the whole Stage 3 surface: participant outputs
that carry no actor/admin fields, READ-only users who cannot mutate, and ``AUTH-U``, ``AUTH-P``
and ``AUTH-C`` asserted at the API itself. The §3.1-§3.4 leaf tests prove each rule where its
own field lives; this is the sweep that proves no field forgets it — the analogue of
``test_stage2_authorization_matrix.py`` for the event, slot, signup, and calendar surface.

Three things make the sweep worth running rather than reading:

* **Every argument block is one its authorized caller actually succeeds with** (the control
  test). A denial that came from a malformed request would look identical in the response and
  prove nothing, so the matrix is only meaningful against requests that are otherwise valid.
  The one exception is ``confirmShowAndSellWork`` on a SCHEDULED board: the Admin's control
  call reaches the business guard (``CONFLICT``), while every unauthorized caller is refused
  BEFORE any business state is consulted — the difference in where the refusal comes from is
  itself the proof that authorization precedes logic.
* **Denial is a write-set claim too.** Every refused call is followed by a multiset
  fingerprint of every table a Stage 3 write can reach (``show_and_sells``, ``inventory``,
  ``unit_campaigns``, ``profiles``, ``shares``): a resolver that authorized after staging
  would leave a marker, a bumped counter, or a commitment behind.
* **The participant half is asserted as a key set**, recursively over the whole answer —
  actor, audit, stock, and money spellings must be absent from every nested object, not just
  the top row.

The isolation rules under test are the ones ``src/utils/unit_auth.py`` and the profile-share
checks state: the ``UnitAccessGrant`` row is the only thing that grants Unit administration
(a removed admin is met with ``NOT_FOUND`` on the Unit surfaces, the same answer as a tenant
that never existed), profile surfaces decide on the caller's share (READ is never a write),
and anonymous/API-key callers reach nothing (AUTH-C).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import pytest

from src.handlers.unit_operations import (
    ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
    CANCEL_SHOW_AND_SELL_FIELD,
    CANCEL_SIGNUP_FIELD,
    CONFIRM_WORK_FIELD,
    CREATE_SHOW_AND_SELL_FIELD,
    DELETE_SLOT_FIELD,
    EVENT_INVENTORY_ALLOCATIONS_FIELD,
    MY_COMMITMENTS_FIELD,
    SHOW_AND_SELL_FIELD,
    SHOW_AND_SELL_OPPORTUNITY_FIELD,
    SHOW_AND_SELL_SIGNUPS_FIELD,
    SHOW_AND_SELLS_FIELD,
    SIGNUP_CALENDAR_FIELD,
    SIGNUP_SCOUT_FIELD,
    UNIT_CAMPAIGN_OPPORTUNITIES_FIELD,
    UPDATE_SHOW_AND_SELL_FIELD,
    UPSERT_SLOT_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    assert_is_error,
    seed_show_sell_fixtures,
    share_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
BOARD = "SSE#auth-board"
EDIT_EVENT = "SSE#auth-edit"
CANCEL_EVENT = "SSE#auth-cancel"
LOCATION = "Aurora armory lot"


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


BOARD_START, BOARD_END = _shift(72), _shift(84)
SLOT_START, SLOT_END = _shift(73), _shift(75)


def _profile(persona: str) -> str:
    return str(PROFILES[persona]["profileId"])


def _scout_campaign(persona: str) -> str:
    return str(PROFILES[persona]["campaignId"])


# --- Handler turns ---------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _ok(payload: Any) -> Dict[str, Any]:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    return payload


def _refusal(payload: Any, code: str) -> str:
    return str(assert_is_error(payload, code).get("message") or "")


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


# --- The board -------------------------------------------------------------------


def _seed_event(
    show_and_sells_table: Any,
    event_id: str,
    *,
    start_at: str = BOARD_START,
    end_at: str = BOARD_END,
    version: int = 1,
) -> None:
    show_and_sells_table.put_item(
        Item=ssm.build_show_and_sell_item(
            show_and_sell_id=event_id,
            unit_id=PACK_3149,
            unit_campaign_id=CAMPAIGN,
            location_name=LOCATION,
            start_at=start_at,
            end_at=end_at,
            created_by_account_id="ACCOUNT#avery-fixture",
            now_iso=start_at,
            version=version,
        )
    )


def _seed_slot(
    show_and_sells_table: Any,
    event_id: str = BOARD,
    slot_id: str = "slot-1",
    *,
    capacity: int = 4,
) -> None:
    stored = show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    show_and_sells_table.put_item(
        Item=ssm.build_show_and_sell_slot_item(
            event=dict(stored) if stored else {},
            slot_id=slot_id,
            start_at=SLOT_START,
            end_at=SLOT_END,
            capacity=capacity,
            active_signup_count=0,
            version=1,
            label="Door",
            now_iso=BOARD_START,
        )
    )


def _seed_balance(inventory_table: Any) -> None:
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            kernel_physical_qty=4,
            sold_in_possession_qty=0,
            council_on_order_qty=0,
            now_iso=BOARD_START,
        )
    )


@pytest.fixture
def board(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """A board in the state §3.7.5's sweep needs, plus one extra WRITE share to aim with.

    The setup signup (Avery signing Devon into ``slot-1``) is a real handler call, so the
    calendar read, the signup cancellation, and the participant allowlist all walk over a
    committed aggregate rather than a hand-stamped row.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _seed_balance(inventory_table)
    for event_id in (BOARD, EDIT_EVENT, CANCEL_EVENT):
        _seed_event(show_and_sells_table, event_id)
    _seed_slot(show_and_sells_table)
    _ok(
        _call(
            SIGNUP_SCOUT_FIELD,
            "Avery",
            mutation={
                "showAndSellId": BOARD,
                "slotId": "slot-1",
                "campaignId": _scout_campaign("Devon"),
                "profileId": _profile("Devon"),
                **_idem("setup-signup"),
            },
        )
    )
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "unit_campaigns": unit_campaigns_table,
        "profiles": profiles_table,
        "shares": shares_table,
    }


def _event_version(world: Dict[str, Any], event_id: str) -> int:
    item = world["show_and_sells"].get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    assert item is not None, f"event {event_id} is missing"
    return int(item[ssm.VERSION_ATTRIBUTE])


def _snapshot(world: Dict[str, Any]) -> Counter:
    rows: Counter = Counter()
    for table in (
        world["show_and_sells"],
        world["inventory"],
        world["unit_campaigns"],
        world["profiles"],
        world["shares"],
    ):
        rows.update(json.dumps(item, sort_keys=True, default=str) for item in table.scan()["Items"])
    return rows


# --- The matrix: one argument block per field, valid for its authorized caller ----


def _field_calls(caller: Optional[str], world: Dict[str, Any]) -> Dict[str, Callable[[], Any]]:
    """Every Stage 3 field, one callable each, built from one shared board state.

    The blocks are the shape the authorized caller sends: a real ``expectedVersion`` read
    from the row, the roster identity pair for the Scout fields, and the real ``slotId``.
    """
    signup_identity = {"campaignId": _scout_campaign("Devon"), "profileId": _profile("Devon")}
    return {
        CREATE_SHOW_AND_SELL_FIELD: lambda: _call(
            CREATE_SHOW_AND_SELL_FIELD,
            caller,
            mutation={
                "unitCampaignId": CAMPAIGN,
                "locationName": LOCATION,
                "startAt": _shift(96),
                "endAt": _shift(100),
                **_idem("sweep-create"),
            },
        ),
        UPDATE_SHOW_AND_SELL_FIELD: lambda: _call(
            UPDATE_SHOW_AND_SELL_FIELD,
            caller,
            mutation={
                "showAndSellId": EDIT_EVENT,
                "locationName": "Renamed lot",
                **_version(_event_version(world, EDIT_EVENT)),
                **_idem("sweep-update"),
            },
        ),
        CANCEL_SHOW_AND_SELL_FIELD: lambda: _call(
            CANCEL_SHOW_AND_SELL_FIELD,
            caller,
            mutation={
                "showAndSellId": CANCEL_EVENT,
                **_version(_event_version(world, CANCEL_EVENT)),
                "reason": "sweep",
                **_idem("sweep-cancel"),
            },
        ),
        SHOW_AND_SELL_FIELD: lambda: _call(SHOW_AND_SELL_FIELD, caller, arguments={"showAndSellId": BOARD}),
        SHOW_AND_SELLS_FIELD: lambda: _call(
            SHOW_AND_SELLS_FIELD, caller, arguments={"unitCampaignId": CAMPAIGN}
        ),
        UNIT_CAMPAIGN_OPPORTUNITIES_FIELD: lambda: _call(
            UNIT_CAMPAIGN_OPPORTUNITIES_FIELD, caller, arguments={"unitCampaignId": CAMPAIGN}
        ),
        SHOW_AND_SELL_OPPORTUNITY_FIELD: lambda: _call(
            SHOW_AND_SELL_OPPORTUNITY_FIELD,
            caller,
            arguments={"showAndSellId": BOARD, "profileId": _profile("Devon")},
        ),
        ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD: lambda: _call(
            ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
            caller,
            mutation={
                "showAndSellId": BOARD,
                "items": [{"productId": PRODUCT, "quantity": 1}],
                **_version(_event_version(world, BOARD)),
                **_idem("sweep-assign"),
            },
        ),
        EVENT_INVENTORY_ALLOCATIONS_FIELD: lambda: _call(
            EVENT_INVENTORY_ALLOCATIONS_FIELD, caller, arguments={"unitCampaignId": CAMPAIGN}
        ),
        UPSERT_SLOT_FIELD: lambda: _call(
            UPSERT_SLOT_FIELD,
            caller,
            mutation={
                "showAndSellId": BOARD,
                "label": "Sweep",
                "startAt": _shift(76),
                "endAt": _shift(77),
                "capacity": 1,
                **_version(_event_version(world, BOARD)),
                **_idem("sweep-slot"),
            },
        ),
        DELETE_SLOT_FIELD: lambda: _call(
            DELETE_SLOT_FIELD,
            caller,
            mutation={
                "showAndSellId": BOARD,
                "slotId": "slot-1",
                **_version(_event_version(world, BOARD)),
                **_idem("sweep-delete"),
            },
        ),
        SIGNUP_SCOUT_FIELD: lambda: _call(
            SIGNUP_SCOUT_FIELD,
            caller,
            mutation={"showAndSellId": BOARD, "slotId": "slot-1", **signup_identity, **_idem("sweep-signup")},
        ),
        CANCEL_SIGNUP_FIELD: lambda: _call(
            CANCEL_SIGNUP_FIELD,
            caller,
            mutation={
                "showAndSellId": BOARD,
                "slotId": "slot-1",
                "profileId": _profile("Devon"),
                **_version(1),
                **_idem("sweep-cancel-signup"),
            },
        ),
        CONFIRM_WORK_FIELD: lambda: _call(
            CONFIRM_WORK_FIELD,
            caller,
            mutation={
                "showAndSellId": BOARD,
                "work": [{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 30}],
                **_version(_event_version(world, BOARD)),
                **_idem("sweep-confirm"),
            },
        ),
        SHOW_AND_SELL_SIGNUPS_FIELD: lambda: _call(
            SHOW_AND_SELL_SIGNUPS_FIELD, caller, arguments={"showAndSellId": BOARD}
        ),
        MY_COMMITMENTS_FIELD: lambda: _call(
            MY_COMMITMENTS_FIELD, caller, arguments={"profileId": _profile("Devon")}
        ),
        SIGNUP_CALENDAR_FIELD: lambda: _call(
            SIGNUP_CALENDAR_FIELD,
            caller,
            arguments={"showAndSellId": BOARD, "slotId": "slot-1", "profileId": _profile("Devon")},
        ),
    }


# Riley administers TROOP 7150, not this Unit, and holds only READ on a profile here;
# Blake was removed as this Unit's admin. Both are otherwise valid Cognito sessions.
SWEEP_DENIALS = [
    (None, "UNAUTHORIZED"),
    ("Riley", "DENIAL"),
    ("Blake", "DENIAL"),
]

# Where the profile surface, not Unit tenancy, answers: a caller with no standing on the
# Unit and no share on the profile is refused FORBIDDEN, and the Unit-admin-only surfaces
# answer the Scout identity with NOT_FOUND. Everything else hides the tenant behind NOT_FOUND.
_FORBIDDEN_FIELDS = {SIGNUP_SCOUT_FIELD, CANCEL_SIGNUP_FIELD, SIGNUP_CALENDAR_FIELD, MY_COMMITMENTS_FIELD}
_NOT_FOUND_CONFIRM = {CONFIRM_WORK_FIELD}

SWEEP_FIELDS = sorted(
    {
        CREATE_SHOW_AND_SELL_FIELD,
        UPDATE_SHOW_AND_SELL_FIELD,
        CANCEL_SHOW_AND_SELL_FIELD,
        SHOW_AND_SELL_FIELD,
        SHOW_AND_SELLS_FIELD,
        UNIT_CAMPAIGN_OPPORTUNITIES_FIELD,
        SHOW_AND_SELL_OPPORTUNITY_FIELD,
        ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
        EVENT_INVENTORY_ALLOCATIONS_FIELD,
        UPSERT_SLOT_FIELD,
        DELETE_SLOT_FIELD,
        SIGNUP_SCOUT_FIELD,
        CANCEL_SIGNUP_FIELD,
        CONFIRM_WORK_FIELD,
        SHOW_AND_SELL_SIGNUPS_FIELD,
        MY_COMMITMENTS_FIELD,
        SIGNUP_CALENDAR_FIELD,
    }
)


def _expected_code(field: str, caller: str) -> str:
    if field in _FORBIDDEN_FIELDS:
        return "FORBIDDEN"
    if field in _NOT_FOUND_CONFIRM:
        return "NOT_FOUND"
    return "NOT_FOUND"


def test_the_control_board_answers_every_stage_three_field_to_its_authorized_caller(
    board: Dict[str, Any],
) -> None:
    """The control half of the matrix: each block SUCCEEDS for the caller it belongs to.

    ``confirmShowAndSellWork`` is the documented exception: on a SCHEDULED board the Admin's
    valid block reaches the business guard (``CONFLICT`` — a scheduled event has no work to
    confirm), which still proves the Admin passed authorization and every denial below fails
    before any business rule is consulted.
    """
    world = board
    _ok(_call(UPDATE_SHOW_AND_SELL_FIELD, "Avery", mutation={
        "showAndSellId": EDIT_EVENT, "locationName": "Renamed lot",
        **_version(_event_version(world, EDIT_EVENT)), **_idem("control-update")}))
    _ok(_call(CANCEL_SHOW_AND_SELL_FIELD, "Avery", mutation={
        "showAndSellId": CANCEL_EVENT, **_version(_event_version(world, CANCEL_EVENT)),
        "reason": "control", **_idem("control-cancel")}))
    _ok(_call(ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "items": [{"productId": PRODUCT, "quantity": 1}],
        **_version(_event_version(world, BOARD)), **_idem("control-assign")}))
    slot = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "Control", "startAt": _shift(76), "endAt": _shift(77),
        "capacity": 1, **_version(_event_version(world, BOARD)), **_idem("control-slot")}))
    _refusal(_call(CONFIRM_WORK_FIELD, "Avery", mutation={
        "showAndSellId": BOARD,
        "work": [{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 30}],
        **_version(_event_version(world, BOARD)), **_idem("control-confirm")}), "CONFLICT")
    _ok(_call(DELETE_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "slotId": slot["slotId"],
        **_version(_event_version(world, BOARD)), **_idem("control-delete")}))
    for field, arguments in (
        (SHOW_AND_SELL_FIELD, {"showAndSellId": BOARD}),
        (SHOW_AND_SELLS_FIELD, {"unitCampaignId": CAMPAIGN}),
        (EVENT_INVENTORY_ALLOCATIONS_FIELD, {"unitCampaignId": CAMPAIGN}),
        (SHOW_AND_SELL_SIGNUPS_FIELD, {"showAndSellId": BOARD}),
        (SIGNUP_CALENDAR_FIELD, {"showAndSellId": BOARD, "slotId": "slot-1", "profileId": _profile("Devon")}),
    ):
        _ok(_call(field, "Avery", arguments=arguments))
    # myScoutCommitments is the participant surface: the Scout's own read, not the Admin's
    # (the Admin's full board is ``showAndSellSignups``, proved on the line above).
    _ok(_call(MY_COMMITMENTS_FIELD, "Devon", arguments={"profileId": _profile("Devon")}))
    for field, arguments in (
        (UNIT_CAMPAIGN_OPPORTUNITIES_FIELD, {"unitCampaignId": CAMPAIGN}),
        (SHOW_AND_SELL_OPPORTUNITY_FIELD, {"showAndSellId": BOARD, "profileId": _profile("Devon")}),
    ):
        _ok(_call(field, "Devon", arguments=arguments))
    # Taylor holds WRITE on Devon's profile: the owner-side half of signup standing.
    # A second slot, so the duplicate guard cannot mask the authorization result.
    second = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "Second", "startAt": _shift(78), "endAt": _shift(79),
        "capacity": 2, **_version(_event_version(world, BOARD)), **_idem("control-slot-2")}))
    _ok(_call(SIGNUP_SCOUT_FIELD, "Taylor", mutation={
        "showAndSellId": BOARD, "slotId": second["slotId"], "campaignId": _scout_campaign("Devon"),
        "profileId": _profile("Devon"), **_idem("control-signup")}))
    _ok(_call(CANCEL_SIGNUP_FIELD, "Taylor", mutation={
        "showAndSellId": BOARD, "slotId": second["slotId"], "profileId": _profile("Devon"),
        **_version(1), **_idem("control-cancel-signup")}))


@pytest.mark.parametrize("field", SWEEP_FIELDS)
def test_an_anonymous_caller_reaches_no_stage_three_field(field: str, board: Dict[str, Any]) -> None:
    """AUTH-C: the API admits no unauthenticated caller to any Stage 3 field, and nothing is written."""
    world = board
    before = _snapshot(world)
    _refusal(_field_calls(None, world)[field](), "UNAUTHORIZED")
    assert _snapshot(world) == before


@pytest.mark.parametrize("field", SWEEP_FIELDS)
def test_a_foreign_unit_admin_reaches_no_field_of_another_unit(field: str, board: Dict[str, Any]) -> None:
    """AUTH-U / AUTH-P: Riley administers TROOP 7150; that grant buys nothing on this board."""
    world = board
    before = _snapshot(world)
    _refusal(_field_calls("Riley", world)[field](), _expected_code(field, "Riley"))
    assert _snapshot(world) == before


@pytest.mark.parametrize("field", SWEEP_FIELDS)
def test_a_removed_admin_holds_nothing_it_had_before(field: str, board: Dict[str, Any]) -> None:
    """AUTH-U: Blake's ``UnitAccessGrant`` row is gone, so the Unit surface answers as absent."""
    world = board
    before = _snapshot(world)
    _refusal(_field_calls("Blake", world)[field](), _expected_code(field, "Blake"))
    assert _snapshot(world) == before


def test_a_read_only_share_cannot_mutate_anything_on_the_profile_it_holds(
    board: Dict[str, Any],
) -> None:
    """§3.7.5: READ on a profile is a read of it, never a write through it.

    Riley holds READ on Devon, who is signed up on this board. The three profile-scoped
    surfaces — signup, signup cancellation, calendar — each refuse with the code the Unit
    surfaces use for a caller with no standing, and the board is byte-identical after.
    """
    world = board
    world["shares"].put_item(Item=share_item("Devon", "Riley", "READ"))
    before = _snapshot(world)
    calls = _field_calls("Riley", world)
    for field in (SIGNUP_SCOUT_FIELD, CANCEL_SIGNUP_FIELD, SIGNUP_CALENDAR_FIELD):
        _refusal(calls[field](), "FORBIDDEN")
    assert _snapshot(world) == before


def test_an_unjoined_or_removed_scout_takes_no_place_on_this_board(board: Dict[str, Any]) -> None:
    """AUTH-C / AUTH-P roster half: the place is refused as absent, never offered.

    Taylor has never joined a Unit Campaign and Emery's membership is REMOVED — neither is
    on this campaign's roster, so signing them in is not a permission question but a
    not-there one, and the refusal writes no roster row, commitment, guard, or marker.
    """
    world = board
    before = _snapshot(world)
    for persona in ("Taylor", "Emery"):
        refusal = _refusal(
            _call(
                SIGNUP_SCOUT_FIELD,
                "Avery",
                mutation={
                    "showAndSellId": BOARD,
                    "slotId": "slot-1",
                    "campaignId": _scout_campaign(persona),
                    "profileId": _profile(persona),
                    **_idem(f"sweep-{persona}"),
                },
            ),
            "NOT_FOUND",
        )
        assert "slot" not in refusal, "the refusal does not describe the place to a Scout who is not here"
    assert _snapshot(world) == before


def _nested_keys(node: Any) -> set:
    if isinstance(node, dict):
        return set(node) | {key for child in node.values() for key in _nested_keys(child)}
    if isinstance(node, list):
        return {key for child in node for key in _nested_keys(child)}
    return set()


def test_participant_surfaces_answer_no_actor_admin_stock_or_money_field(board: Dict[str, Any]) -> None:
    """§3.7.5: every key reachable from a participant read is participant-safe.

    The forbidden spellings are the audit and money vocabulary of the admin surfaces: who
    signed a Scout up, who confirmed work and when, cancellation actor/reason, event audit,
    and the whole stock/cash vocabulary. The answer is walked recursively, so a leak in a
    nested slot or signup object fails the same as one at the top row.
    """
    forbidden = {
        "createdByAccountId",
        "updatedByAccountId",
        "cancelledByAccountId",
        "cancelledAt",
        "cancellationReason",
        "signedUpByAccountId",
        "confirmedByAccountId",
        "confirmedAt",
        "workVersion",
        "finalizationPointer",
        "approvedFinalizationId",
        "kernelPhysicalQty",
        "allocatedQty",
        "remainingQty",
        "soldQty",
        "releasedQty",
        "totalCents",
        "approvedCents",
        "buyerName",
        "paymentMethod",
    }
    answers = [
        _ok(_call(UNIT_CAMPAIGN_OPPORTUNITIES_FIELD, "Devon", arguments={"unitCampaignId": CAMPAIGN})),
        _ok(_call(SHOW_AND_SELL_OPPORTUNITY_FIELD, "Devon", arguments={"showAndSellId": BOARD, "profileId": _profile("Devon")})),
        _ok(_call(MY_COMMITMENTS_FIELD, "Devon", arguments={"profileId": _profile("Devon")})),
        _ok(_call(SIGNUP_CALENDAR_FIELD, "Devon", arguments={"showAndSellId": BOARD, "slotId": "slot-1", "profileId": _profile("Devon")})),
    ]
    for answer in answers:
        leaked = forbidden & _nested_keys(answer)
        assert leaked == set(), f"participant answer carries administrative keys: {sorted(leaked)}"
