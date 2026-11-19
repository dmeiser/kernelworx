"""Wave 4.1 — the Show & Sell event resolvers (§3.1.2-§3.1.5).

Resolver-level tests for `EVT-M-01`, `EVT-M-02`, `EVT-M-03`, `EVT-Q-01`-`03`,
`AUTH-U`, `AUTH-P`, `VER-01`, `IDEM` and `PAGE-01`. Every case goes through
``handle_unit_operation`` against moto, so it exercises the real Unit Admin check, the
real Profile share check, the real idempotency marker, the real conditional
transaction, and the real payload the browser receives — the layer where "the
allocation was released and the signup cancelled in the same commit" is either true
or not.

The named assertions live in ``SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md`` §5.1
and §5.2; the personas there are the fixture personas here: Avery is the Unit Admin
(Alex/Casey), Devon the joined Scout (Morgan), Taylor the WRITE-share holder on
Devon's Profile, Riley the READ-share holder on a Profile that is NOT on this
campaign's roster, Emery the Scout with no standing on it, and Blake the former Admin
whose grant row is gone.

Event instants are written relative to the real clock, because the resolvers derive
``SCHEDULED``/``ACTIVE``/``ENDED`` from ``utc_now_iso()``: a fixture whose "future" is
a literal date stops meaning future the day the calendar crosses it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    CANCEL_SHOW_AND_SELL_FIELD,
    CREATE_SHOW_AND_SELL_FIELD,
    SHOW_AND_SELL_FIELD,
    SHOW_AND_SELL_OPPORTUNITY_FIELD,
    SHOW_AND_SELLS_FIELD,
    UNIT_CAMPAIGN_OPPORTUNITIES_FIELD,
    UPDATE_SHOW_AND_SELL_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import unit_campaign_models as ucm
from tests.unit.show_sell_fixtures import (
    CREW_529_SPRING,
    PACK_3149,
    PACK_3149_FALL,
    PACK_3149_OLD,
    PROFILES,
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_campaign_item,
    unit_campaign_membership_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_UNIT_CAMPAIGN = CREW_529_SPRING
INACTIVE_CAMPAIGN = PACK_3149_OLD
PRODUCT = "CATALOG#fixture-default#prod-1"
OTHER_PRODUCT = "CATALOG#fixture-default#prod-2"
RELEASED_PRODUCT = "CATALOG#fixture-default#prod-3"
LOCATION = "Aurora armory lot"


# Past and future, measured from the run rather than from a calendar date: the
# resolvers derive state from ``utc_now_iso()``, so a literal "future" date goes
# stale the day the calendar crosses it.
def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


FUTURE_START, FUTURE_END = _shift(72), _shift(76)
FUTURE_LATER_START, FUTURE_LATER_END = _shift(120), _shift(124)
ACTIVE_START, ACTIVE_END = _shift(-2), _shift(4)
ENDED_START, ENDED_END = _shift(-48), _shift(-44)


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
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def _create(
    caller: Optional[str] = "Avery",
    *,
    key: str = "create-1",
    campaign: str = CAMPAIGN,
    location: Any = LOCATION,
    start_at: Any = FUTURE_START,
    end_at: Any = FUTURE_END,
    **extra: Any,
) -> Any:
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "locationName": location,
        "startAt": start_at,
        "endAt": end_at,
        **_idem(key),
    }
    if location is None:
        mutation.pop("locationName")
    mutation.update(extra)
    return _call(CREATE_SHOW_AND_SELL_FIELD, caller, mutation=mutation)


def _update(
    caller: Optional[str] = "Avery",
    *,
    event_id: str,
    expected_version: int = 1,
    key: str = "update-1",
    **fields: Any,
) -> Any:
    mutation: Dict[str, Any] = {
        "showAndSellId": event_id,
        **_version(expected_version),
        **_idem(key),
        **fields,
    }
    return _call(UPDATE_SHOW_AND_SELL_FIELD, caller, mutation=mutation)


def _cancel(
    caller: Optional[str] = "Avery",
    *,
    event_id: str,
    expected_version: int = 1,
    reason: Any = "storm warning",
    key: str = "cancel-1",
) -> Any:
    mutation: Dict[str, Any] = {
        "showAndSellId": event_id,
        **_version(expected_version),
        **_idem(key),
    }
    if reason is not None:
        mutation["reason"] = reason
    return _call(CANCEL_SHOW_AND_SELL_FIELD, caller, mutation=mutation)


def _show(caller: Optional[str] = "Avery", event_id: str = "") -> Any:
    return _call(SHOW_AND_SELL_FIELD, caller, arguments={"showAndSellId": event_id})


def _list(caller: Optional[str] = "Avery", campaign: str = CAMPAIGN, **arguments: Any) -> Any:
    return _call(SHOW_AND_SELLS_FIELD, caller, arguments={"unitCampaignId": campaign, **arguments})


def _opportunities(caller: Optional[str] = "Devon", campaign: str = CAMPAIGN, **arguments: Any) -> Any:
    return _call(UNIT_CAMPAIGN_OPPORTUNITIES_FIELD, caller, arguments={"unitCampaignId": campaign, **arguments})


def _opportunity(caller: Optional[str] = "Devon", event_id: str = "", persona: str = "Devon") -> Any:
    return _call(
        SHOW_AND_SELL_OPPORTUNITY_FIELD,
        caller,
        arguments={"showAndSellId": event_id, "profileId": _profile(persona)},
    )


# --- Seeded rows -----------------------------------------------------------------


def _seed_event(
    show_and_sells_table: Any,
    event_id: str,
    *,
    campaign: str = CAMPAIGN,
    unit: str = PACK_3149,
    status: str = ssm.STATUS_SCHEDULED,
    start_at: str = FUTURE_START,
    end_at: str = FUTURE_END,
    product_ids: Optional[List[str]] = None,
    we_owe_enabled: bool = False,
    split_method: str = ssm.DEFAULT_SPLIT_METHOD,
    version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """One METADATA row, built by the model and then moved to the state a test needs.

    The workflow states carry audit the builder demands, so the state is written after
    the build — which is exactly how a later stage's row looks to this leaf's reads.
    """
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=unit,
        unit_campaign_id=campaign,
        location_name=LOCATION,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id="ACCOUNT#avery-fixture",
        now_iso=start_at,
        split_method=split_method,
        we_owe_enabled=we_owe_enabled,
        product_ids=product_ids or [],
        version=version,
    )
    item[ssm.STATUS_ATTRIBUTE] = status
    if status == ssm.STATUS_FINALIZED:
        item[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] = f"FIN#{event_id}"
    if status == ssm.STATUS_CANCELLED:
        item[ssm.CANCELLATION_REASON_ATTRIBUTE] = "earlier cancellation"
    item.update(overrides)
    show_and_sells_table.put_item(Item=item)
    return event_id


def _seed_slot(
    show_and_sells_table: Any,
    event_id: str,
    slot_id: str = "slot-1",
    *,
    active: int = 1,
    capacity: int = 4,
    version: int = 1,
    start_at: str = FUTURE_START,
    end_at: str = FUTURE_END,
) -> Dict[str, Any]:
    item = {
        **ssm.slot_key(event_id, slot_id),
        "entityType": ssm.ENTITY_TYPE_SLOT,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.LABEL_ATTRIBUTE: f"Saturday {slot_id}",
        ssm.START_AT_ATTRIBUTE: start_at,
        ssm.END_AT_ATTRIBUTE: end_at,
        ssm.CAPACITY_ATTRIBUTE: capacity,
        ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE: active,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: start_at,
        ssm.UPDATED_AT_ATTRIBUTE: start_at,
    }
    show_and_sells_table.put_item(Item=item)
    return item


def _seed_signup(
    show_and_sells_table: Any,
    event_id: str,
    slot_id: str = "slot-1",
    *,
    persona: str = "Devon",
    status: str = ssm.SIGNUP_ACTIVE,
    version: int = 1,
    start_at: str = FUTURE_START,
    end_at: str = FUTURE_END,
    capacity: int = 4,
) -> Dict[str, Any]:
    """One signup row, in the shape §3.4 writes, with the slot it belongs to.

    The slot is seeded alongside it because §5.13 gives ``ShowAndSellSignup`` no
    ``startAt``/``endAt`` — a signup runs when its slot runs — so a signup with no slot
    row is a broken aggregate, and a fixture that denormalized the interval onto the
    signup would hide any projection that read it from the wrong row. An existing slot
    row is left alone so a test that configured capacity or a counter first keeps it.
    """
    if "Item" not in show_and_sells_table.get_item(Key=ssm.slot_key(event_id, slot_id)):
        _seed_slot(
            show_and_sells_table,
            event_id,
            slot_id,
            active=0 if status == ssm.SIGNUP_CANCELLED else 1,
            capacity=capacity,
            start_at=start_at,
            end_at=end_at,
        )
    profile_id = _profile(persona)
    item = {
        "pk": ssm.show_and_sell_pk(event_id),
        "sk": ssm.signup_sk(slot_id, profile_id),
        "entityType": ssm.ENTITY_TYPE_SIGNUP,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.CAMPAIGN_ID_ATTRIBUTE: _scout_campaign(persona),
        ssm.PROFILE_ID_ATTRIBUTE: profile_id,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.ACTUAL_MINUTES_ATTRIBUTE: 30,
        ssm.SIGNED_UP_BY_ATTRIBUTE: f"ACCOUNT#{persona.lower()}-fixture",
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: FUTURE_START,
        ssm.UPDATED_AT_ATTRIBUTE: FUTURE_START,
    }
    show_and_sells_table.put_item(Item=item)
    return item


def _seed_commitment(
    unit_campaigns_table: Any,
    event_id: str,
    slot_id: str = "slot-1",
    *,
    persona: str = "Devon",
    status: str = ssm.SIGNUP_ACTIVE,
    version: int = 1,
) -> Dict[str, Any]:
    profile_id = _profile(persona)
    item = {
        **ssm.commitment_key(profile_id, FUTURE_START, CAMPAIGN, slot_id),
        "entityType": ssm.ENTITY_TYPE_COMMITMENT,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.CAMPAIGN_ID_ATTRIBUTE: _scout_campaign(persona),
        ssm.COMMITMENT_ID_ATTRIBUTE: ssm.signup_sk(slot_id, profile_id),
        ssm.PROFILE_ID_ATTRIBUTE: profile_id,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.START_AT_ATTRIBUTE: FUTURE_START,
        ssm.END_AT_ATTRIBUTE: FUTURE_END,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: FUTURE_START,
        ssm.UPDATED_AT_ATTRIBUTE: FUTURE_START,
    }
    unit_campaigns_table.put_item(Item=item)
    return item


def _seed_guard(unit_campaigns_table: Any, *, persona: str = "Devon", version: int = 3) -> Dict[str, Any]:
    profile_id = _profile(persona)
    item = {
        **ssm.commitment_guard_key(profile_id),
        "entityType": "ScoutCommitmentGuard",
        ssm.PROFILE_ID_ATTRIBUTE: profile_id,
        "commitmentVersion": version,
        ssm.UPDATED_AT_ATTRIBUTE: FUTURE_START,
    }
    unit_campaigns_table.put_item(Item=item)
    return item


def _seed_allocation(
    inventory_table: Any,
    event_id: str,
    product_id: str = PRODUCT,
    *,
    allocated: int = 10,
    sold: int = 0,
    released: int = 0,
    remaining: int = 10,
    status: str = inv.ALLOCATION_OPEN,
    version: int = 1,
) -> Dict[str, Any]:
    item = {
        **ssm.event_allocation_key(CAMPAIGN, product_id, event_id),
        "entityType": inv.ALLOCATION_ENTITY_TYPE,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        inv.PRODUCT_ID_ATTRIBUTE: product_id,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.START_AT_ATTRIBUTE: FUTURE_START,
        ssm.END_AT_ATTRIBUTE: FUTURE_END,
        ssm.STATUS_ATTRIBUTE: status,
        inv.ALLOCATED_QTY: allocated,
        inv.SOLD_QTY: sold,
        inv.RELEASED_QTY: released,
        inv.REMAINING_QTY: remaining,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: FUTURE_START,
        ssm.UPDATED_AT_ATTRIBUTE: FUTURE_START,
    }
    inventory_table.put_item(Item=item)
    return item


def _seed_we_owe(
    show_and_sells_table: Any,
    event_id: str,
    we_owe_id: str = "we-1",
    *,
    status: str = ssm.WE_OWE_STATUS_OPEN,
) -> Dict[str, Any]:
    item = {
        "pk": ssm.show_and_sell_pk(event_id),
        "sk": f"WE_OWE#{we_owe_id}",
        "entityType": "WeOweObligation",
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.PROFILE_ID_ATTRIBUTE: _profile("Devon"),
        ssm.STATUS_ATTRIBUTE: status,
        ssm.VERSION_ATTRIBUTE: 1,
    }
    show_and_sells_table.put_item(Item=item)
    return item


def _partition(show_and_sells_table: Any, event_id: str) -> List[Dict[str, Any]]:
    """Every row in one event's partition, whatever its sort key."""
    page = show_and_sells_table.query(
        KeyConditionExpression="#pk = :pk",
        ExpressionAttributeNames={"#pk": "pk"},
        ExpressionAttributeValues={":pk": ssm.show_and_sell_pk(event_id)},
    )
    return list(page["Items"])


def _all_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return list(show_and_sells_table.scan()["Items"])


def _stored(show_and_sells_table: Any, event_id: str) -> Dict[str, Any]:
    return dict(show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id))["Item"])


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    """Every idempotency marker on the event table (§8.9).

    A marker rides the table the mutation writes, so a Show & Sell marker is a row on
    ``show_and_sells`` with the ``IDEM#`` sort-key prefix — and a refused mutation must
    leave none behind, because the marker is staged inside the same transaction.
    """
    return [row for row in _all_rows(show_and_sells_table) if str(row.get("sk", "")).startswith("IDEM#")]


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
    """The Stage 1 persona world plus the two tables this leaf writes.

    ``inventory_table`` is here because an event's allocations live on it: the
    cancellation releases them in the same transaction as the event row, so the pair
    is the unit of correctness (§8.8).
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "unit_campaigns": unit_campaigns_table,
    }


def _joined_and_removed(world: Dict[str, Any], persona: str = "Emery") -> None:
    """Give a persona a REMOVED membership on the campaign under test."""
    world["unit_campaigns"].put_item(
        Item=unit_campaign_membership_item(
            CAMPAIGN,
            PACK_3149,
            _scout_campaign(persona),
            _profile(persona),
            status="REMOVED",
            joined_by=persona,
            removed_by="Avery",
            version=2,
        )
    )


# --- EVT-M-01: createShowAndSell (§3.1.2) ---------------------------------------


def test_evt_m_01_01_create_writes_one_scheduled_event_and_inherits_the_unit_split(
    world: Dict[str, Any],
) -> None:
    """EVT-M-01-01: required location, optional address, immutable times, inherited split, We Owe off."""
    answer = _ok(_create(key="create-1"))

    assert answer["unitId"] == PACK_3149
    assert answer["unitCampaignId"] == CAMPAIGN
    assert answer["locationName"] == LOCATION
    assert answer["address"] is None
    assert answer["startAt"] == ssm.normalize_moment(FUTURE_START, "startAt")
    assert answer["status"] == "SCHEDULED"
    assert answer["splitMethod"] == "EQUAL", "Pack 3149's default, not a guessed one"
    assert answer["weOweEnabled"] is False
    assert answer["productIds"] == []
    assert answer["allocations"] == []
    assert answer["slots"] == []
    assert answer["version"] == 1
    assert answer["createdByAccountId"] == answer["updatedByAccountId"]

    rows = _partition(world["show_and_sells"], answer["showAndSellId"])
    assert [row["sk"] for row in rows] == ["METADATA"], "no slot, signup, or sale row rides an event create"
    assert len(_marker_rows(world["show_and_sells"])) == 1, "the marker rides the same transaction"
    stored = _stored(world["show_and_sells"], answer["showAndSellId"])
    assert stored["version"] == 1
    assert ssm.normalize_moment(stored["endAt"], "endAt") > ssm.normalize_moment(stored["startAt"], "startAt")


def test_evt_m_01_01_a_split_override_and_we_owe_on_are_the_caller_s_choice(world: Dict[str, Any]) -> None:
    answer = _ok(_create(key="create-2", splitMethod="TIME_WORKED", weOweEnabled=True, address="12 Main St"))
    assert answer["splitMethod"] == "TIME_WORKED"
    assert answer["weOweEnabled"] is True
    assert answer["address"] == "12 Main St"
    assert _stored(world["show_and_sells"], answer["showAndSellId"])[ssm.WE_OWE_ENABLED_ATTRIBUTE] is True


def test_evt_m_01_01_two_events_on_the_same_hours_are_both_created(world: Dict[str, Any]) -> None:
    """SSE-02: overlap is never a rejection at create; §3.2 decides stock, not the calendar."""
    first = _ok(_create(key="create-a"))
    second = _ok(_create(key="create-b"))
    assert first["startAt"] == second["startAt"]
    assert first["showAndSellId"] != second["showAndSellId"]
    listed = _ok(_list())
    assert len(listed["items"]) == 2


def test_evt_m_01_02_missing_location_and_bad_times_are_refused(world: Dict[str, Any]) -> None:
    """EVT-M-01-02: the location is required and end must follow start."""
    assert_is_error(_create(location=None, key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(location="   ", key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(location="x" * 101, key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(start_at=FUTURE_START, end_at=FUTURE_START, key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(start_at=FUTURE_END, end_at=FUTURE_START, key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(start_at="2026-11-07T08:00:00", key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(address="x" * 501, key="create-1"), "INVALID_INPUT")
    assert_is_error(_create(splitMethod="BY_ALLOCATION", key="create-1"), "INVALID_INPUT")
    assert _marker_rows(world["show_and_sells"]) == [], "a refused create leaves no marker behind"
    assert _ok(_list())["items"] == []


def test_evt_m_01_03_only_an_admin_of_the_campaign_s_unit_may_create(world: Dict[str, Any]) -> None:
    """EVT-M-01-03 / AUTH-U: another Unit's Admin, a former Admin, and a Scout are all refused."""
    for persona in ("Blake", "Riley", "Devon", "Taylor"):
        assert_is_error(_create(caller=persona, key="create-x"), "NOT_FOUND")
    assert_is_error(_create(caller=None, key="create-y"), "UNAUTHORIZED")
    assert_is_error(_create(campaign="uc-none", key="create-z"), "NOT_FOUND")
    assert _ok(_list())["items"] == []


def test_evt_m_01_03_the_same_key_replays_and_a_different_intent_is_refused(world: Dict[str, Any]) -> None:
    """EVT-M-01-03 / IDEM: a retry returns the first answer and writes nothing new."""
    first = _ok(_create(key="create-1"))
    again = _ok(_create(key="create-1"))
    assert again == first
    assert [row["sk"] for row in _partition(world["show_and_sells"], first["showAndSellId"])] == ["METADATA"]
    assert len(_marker_rows(world["show_and_sells"])) == 1, "the retry wrote no second marker"

    mismatch = assert_is_error(_create(key="create-1", location="A different lot"), "INVALID_INPUT")
    assert "idempotencyKey" in mismatch["message"]
    assert len(_ok(_list())["items"]) == 1


def test_create_requires_an_idempotency_key(world: Dict[str, Any]) -> None:
    assert_is_error(_call(CREATE_SHOW_AND_SELL_FIELD, "Avery", mutation={"unitCampaignId": CAMPAIGN}), "INVALID_INPUT")


# --- EVT-M-02: updateShowAndSell (§3.1.3) ---------------------------------------


def test_evt_m_02_01_an_admin_edits_the_four_settings_and_the_version_moves(
    world: Dict[str, Any],
) -> None:
    """EVT-M-02-01: location, address, split, We Owe; and only those."""
    event_id = _ok(_create(key="create-1"))["showAndSellId"]
    answer = _ok(
        _update(
            event_id=event_id,
            expected_version=1,
            locationName="New armory lot",
            address="12 Main St",
            splitMethod="TIME_WORKED",
            weOweEnabled=True,
        )
    )
    assert answer["locationName"] == "New armory lot"
    assert answer["address"] == "12 Main St"
    assert answer["splitMethod"] == "TIME_WORKED"
    assert answer["weOweEnabled"] is True
    assert answer["version"] == 2
    stored = _stored(world["show_and_sells"], event_id)
    assert stored[ssm.UPDATED_BY_ATTRIBUTE] == account_id("Avery")

    cleared = _ok(_update(event_id=event_id, expected_version=2, key="update-2", address=None))
    assert cleared["address"] is None
    assert cleared["version"] == 3


def test_evt_m_02_01_an_update_may_not_reschedule_or_rename_the_event_itself(
    world: Dict[str, Any],
) -> None:
    """EVT-M-02-01: there is no rescheduling input, and a smuggled one is a refusal."""
    event_id = _ok(_create(key="create-1"))["showAndSellId"]
    for smuggled in ("startAt", "endAt", "status", "version", "productIds", "unitId", "createdByAccountId"):
        refused = assert_is_error(
            _update(event_id=event_id, key=f"update-{smuggled}", **{smuggled: "x"}), "INVALID_INPUT"
        )
        assert smuggled in refused["message"]
    assert_is_error(_update(event_id=event_id, key="update-empty"), "INVALID_INPUT")
    assert _stored(world["show_and_sells"], event_id)["version"] == 1


def test_evt_m_02_03_the_state_matrix_admits_every_state_before_finalization(world: Dict[str, Any]) -> None:
    """EVT-M-02-03: SCHEDULED, ACTIVE, ENDED are editable and a REOPENED event's edits are drafts."""
    cases = {
        "scheduled": (ssm.STATUS_SCHEDULED, FUTURE_START, FUTURE_END),
        "active": (ssm.STATUS_SCHEDULED, ACTIVE_START, ACTIVE_END),
        "ended": (ssm.STATUS_SCHEDULED, ENDED_START, ENDED_END),
        "reopened": (ssm.STATUS_REOPENED, ENDED_START, ENDED_END),
    }
    for label, (status, start_at, end_at) in cases.items():
        event_id = f"SSE#{label}"
        _seed_event(world["show_and_sells"], event_id, status=status, start_at=start_at, end_at=end_at)
        answer = _ok(_update(event_id=event_id, key=f"update-{label}", locationName=f"lot {label}"))
        assert answer["locationName"] == f"lot {label}", f"a {status} event in a live interval stays editable"


def test_evt_m_02_03_a_finalized_or_cancelled_event_is_not_editable(world: Dict[str, Any]) -> None:
    """EVT-M-02-01: a finalized answer is settled until it is reopened; cancelled is finished."""
    for label, status in (("finalized", ssm.STATUS_FINALIZED), ("cancelled", ssm.STATUS_CANCELLED)):
        event_id = f"SSE#{label}"
        _seed_event(world["show_and_sells"], event_id, status=status, start_at=ENDED_START, end_at=ENDED_END)
        refused = assert_is_error(_update(event_id=event_id, key="update-1", locationName="too late"), "CONFLICT")
        assert "cannot be edited" in refused["message"]
        assert _stored(world["show_and_sells"], event_id)["locationName"] == LOCATION


def test_evt_m_02_02_we_owe_stays_on_while_an_obligation_is_open(world: Dict[str, Any]) -> None:
    """EVT-M-02-02: turning We Owe off may not strand an obligation the event owes."""
    event_id = _ok(_create(key="create-1", weOweEnabled=True))["showAndSellId"]
    _seed_we_owe(world["show_and_sells"], event_id, "we-open", status=ssm.WE_OWE_STATUS_OPEN)
    refused = assert_is_error(
        _update(event_id=event_id, key="update-1", weOweEnabled=False),
        "CONFLICT",
    )
    assert "open We Owe obligation" in refused["message"]
    assert _stored(world["show_and_sells"], event_id)[ssm.WE_OWE_ENABLED_ATTRIBUTE] is True

    _seed_we_owe(world["show_and_sells"], event_id, "we-closed", status=ssm.WE_OWE_STATUS_CLOSED)
    world["show_and_sells"].update_item(
        Key={"pk": ssm.show_and_sell_pk(event_id), "sk": "WE_OWE#we-open"},
        UpdateExpression="SET #status = :closed",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":closed": ssm.WE_OWE_STATUS_CLOSED},
    )
    answer = _ok(_update(event_id=event_id, expected_version=1, key="update-2", weOweEnabled=False))
    assert answer["weOweEnabled"] is False


def test_evt_m_02_03_a_stale_version_writes_nothing(world: Dict[str, Any]) -> None:
    """EVT-M-02-03 / VER-01: the version the caller read is part of the write."""
    event_id = _ok(_create(key="create-1"))["showAndSellId"]
    _ok(_update(event_id=event_id, expected_version=1, key="update-1", locationName="first edit"))
    assert_is_error(
        _update(event_id=event_id, expected_version=1, key="update-2", locationName="stale edit"),
        "CONFLICT",
    )
    assert _stored(world["show_and_sells"], event_id)["locationName"] == "first edit"
    assert _stored(world["show_and_sells"], event_id)["version"] == 2


def test_evt_m_02_03_an_update_replays_and_a_non_admin_is_refused(world: Dict[str, Any]) -> None:
    """EVT-M-02-03 / IDEM and AUTH-U."""
    event_id = _ok(_create(key="create-1"))["showAndSellId"]
    first = _ok(_update(event_id=event_id, expected_version=1, key="update-1", locationName="replayed lot"))
    again = _ok(_update(event_id=event_id, expected_version=1, key="update-1", locationName="replayed lot"))
    assert again == first, "the retry of a committed edit is answered, not re-run"
    assert _stored(world["show_and_sells"], event_id)["version"] == 2

    for persona in ("Blake", "Riley", "Devon"):
        assert_is_error(_update(event_id=event_id, caller=persona, key="update-x", locationName="nope"), "NOT_FOUND")
    assert_is_error(_update(event_id="SSE#none", key="update-y", locationName="nope"), "NOT_FOUND")


# --- EVT-M-03: cancelShowAndSell (§3.1.4) ---------------------------------------


def test_ver_01_a_mutation_holding_a_version_that_is_not_the_row_it_read_is_refused(
    world: Dict[str, Any],
) -> None:
    """VER-01 / FUNC-3: the version the caller names must be the version that was read.

    The write's version condition only proves nobody moved the row since the *caller*
    read it. Every state rule — "still editable", "still cancellable" — is answered from
    the row *this request* read a moment earlier, so a supplied version that names a
    different row splits the two: a request holding version 2 can pass the editable
    check against a freshly-read SCHEDULED version 1, a competing cancellation can then
    commit version 2, and the write matches a row whose state was never checked.
    """
    event_id = _seed_event(world["show_and_sells"], "SSE#version-race")

    refused = assert_is_error(_update(event_id=event_id, expected_version=2, key="update-ahead"), "CONFLICT")
    assert "changed since you read it" in str(refused.get("message") or "")
    refused = assert_is_error(_cancel(event_id=event_id, expected_version=2, key="cancel-ahead"), "CONFLICT")
    assert "changed since you read it" in str(refused.get("message") or "")

    stored = _stored(world["show_and_sells"], event_id)
    assert stored[ssm.VERSION_ATTRIBUTE] == 1
    assert stored[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_SCHEDULED, "a refused mutation writes nothing"


def test_evt_m_02_04_an_update_that_arrives_after_a_cancellation_meets_the_state_guard(
    world: Dict[str, Any],
) -> None:
    """EVT-M-02-04: the update-versus-cancel interleaving, with both guards in place.

    The update arrives carrying the version the cancellation produced, so the version
    condition alone would let it write. It is the state guard that refuses it, which is
    only honest because the version check above proved the row it checked is the row it
    writes.
    """
    event_id = _seed_event(world["show_and_sells"], "SSE#cancel-then-update")
    _ok(_cancel(event_id=event_id, key="cancel-1"))

    assert_is_error(_update(event_id=event_id, expected_version=2, locationName="after the storm"), "CONFLICT")
    stored = _stored(world["show_and_sells"], event_id)
    assert stored[ssm.LOCATION_NAME_ATTRIBUTE] == LOCATION
    assert stored[ssm.VERSION_ATTRIBUTE] == 2, "a refused update does not advance the event again"
    assert stored[ssm.CANCELLATION_REASON_ATTRIBUTE] == "storm warning"


def test_evt_m_03_04_a_second_cancellation_cannot_rewrite_the_first_one_s_audit(
    world: Dict[str, Any],
) -> None:
    """EVT-M-03-04: the cancellation's own precondition rides in its write.

    A second cancellation of an empty event carrying the version the first produced
    would otherwise replace the reason, actor and instant of the cancellation that
    actually happened, and move the event to a third version.
    """
    event_id = _seed_event(world["show_and_sells"], "SSE#cancel-twice")
    first = _ok(_cancel(event_id=event_id, key="cancel-1"))

    assert_is_error(
        _cancel(event_id=event_id, expected_version=2, reason="late second thought", key="cancel-2"), "CONFLICT"
    )
    stored = _stored(world["show_and_sells"], event_id)
    assert stored[ssm.CANCELLATION_REASON_ATTRIBUTE] == "storm warning"
    assert stored[ssm.CANCELLED_AT_ATTRIBUTE] == first["event"]["cancelledAt"]
    assert stored[ssm.VERSION_ATTRIBUTE] == 2
    assert _stored(world["show_and_sells"], event_id) == _stored(world["show_and_sells"], event_id)


def test_evt_m_02_05_an_explicit_clear_is_not_the_replay_of_an_omitted_field(
    world: Dict[str, Any],
) -> None:
    """EVT-M-02-05 / IDEM: ``address`` omitted leaves it alone, ``address: null`` clears it.

    SDL §6 makes those two requests different requests. Folding nulls out of the update
    fingerprint gives them the same one, so a retry of "change the location" would answer
    a later "clear the address" as already done and clear nothing.
    """
    event_id = _ok(_create(key="create-1", address="12 Aurora Way"))["showAndSellId"]

    first = _ok(_update(event_id=event_id, expected_version=1, key="same-key", locationName="replayed lot"))
    assert first["address"] == "12 Aurora Way"

    reused = assert_is_error(
        _update(event_id=event_id, expected_version=1, key="same-key", address=None), "INVALID_INPUT"
    )
    assert "different request content" in str(reused.get("message") or ""), (
        f"an explicit clear must not be answered as the replay of an omitted field: {reused!r}"
    )
    assert _stored(world["show_and_sells"], event_id)[ssm.ADDRESS_ATTRIBUTE] == "12 Aurora Way"

    cleared = _ok(_update(event_id=event_id, expected_version=2, key="clear-key", address=None))
    assert cleared["address"] is None
    stored_after = _stored(world["show_and_sells"], event_id)
    assert ssm.ADDRESS_ATTRIBUTE in stored_after and stored_after[ssm.ADDRESS_ATTRIBUTE] is None


def _cancel_ready_event(world: Dict[str, Any], event_id: str = "SSE#cancel-me") -> str:
    """An event holding stock, a slot, a signup, and the Scout-side commitment."""
    _seed_event(world["show_and_sells"], event_id, product_ids=[PRODUCT])
    _seed_slot(world["show_and_sells"], event_id, active=1)
    _seed_signup(world["show_and_sells"], event_id)
    _seed_commitment(world["unit_campaigns"], event_id)
    _seed_guard(world["unit_campaigns"])
    _seed_allocation(world["inventory"], event_id, sold=2, released=1, remaining=7)
    return event_id


def test_evt_m_03_01_cancelling_releases_stock_and_signups_in_one_result(world: Dict[str, Any]) -> None:
    """EVT-M-03-01: released allocations, cancelled signups and commitments, zero counters, stored audit."""
    event_id = _cancel_ready_event(world)
    answer = _ok(_cancel(event_id=event_id))

    assert answer["event"]["status"] == "CANCELLED"
    assert answer["event"]["cancellationReason"] == "storm warning"
    assert answer["event"]["cancelledByAccountId"] == account_id("Avery")
    assert answer["event"]["cancelledAt"]
    assert answer["event"]["version"] == 2
    assert [row["productId"] for row in answer["releasedAllocations"]] == [PRODUCT]
    assert answer["releasedAllocations"][0]["status"] == inv.ALLOCATION_CANCELLED
    assert answer["releasedAllocations"][0]["remainingQty"] == 0
    assert answer["releasedAllocations"][0]["releasedQty"] == 8
    assert [row["profileId"] for row in answer["cancelledSignups"]] == [_profile("Devon")]
    assert answer["cancelledSignups"][0]["status"] == ssm.SIGNUP_CANCELLED

    stored = _stored(world["show_and_sells"], event_id)
    assert stored[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_CANCELLED
    assert stored[ssm.CANCELLATION_REASON_ATTRIBUTE] == "storm warning"

    allocation = dict(world["inventory"].get_item(Key=ssm.event_allocation_key(CAMPAIGN, PRODUCT, event_id))["Item"])
    assert allocation[inv.REMAINING_QTY] == 0
    assert allocation[inv.RELEASED_QTY] == 8, "the read remainder joins the read released amount"
    assert allocation[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_CANCELLED

    slot = dict(world["show_and_sells"].get_item(Key=ssm.slot_key(event_id, "slot-1"))["Item"])
    assert slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 0, "the counter is zeroed, not left counting"
    assert slot[ssm.VERSION_ATTRIBUTE] == 2

    signup = dict(
        world["show_and_sells"].get_item(
            Key={"pk": ssm.show_and_sell_pk(event_id), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
        )["Item"]
    )
    assert signup[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED

    commitment = dict(
        world["unit_campaigns"].get_item(Key=ssm.commitment_key(_profile("Devon"), FUTURE_START, CAMPAIGN, "slot-1"))[
            "Item"
        ]
    )
    assert commitment[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED
    guard = dict(world["unit_campaigns"].get_item(Key=ssm.commitment_guard_key(_profile("Devon")))["Item"])
    assert guard["commitmentVersion"] == 4, "the guard is incremented by the write itself"

    movements = [
        row
        for row in world["inventory"].query(
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "pk"},
            ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN)},
        )["Items"]
        if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE
    ]
    assert len(movements) == 1
    assert movements[0]["movementType"] == inv.EVENT_RELEASE
    # The allocation's ``releasedQty`` is the cumulative total (1 + 7 = 8); the movement
    # is a delta, so it says -7. A movement of -8 would count the earlier release twice
    # against an allocation that only ever held 10.
    assert movements[0][inv.ASSIGNED_DELTA] == -7
    assert movements[0][inv.ASSIGNED_DELTA] != -8, "the cumulative total belongs on the allocation row only"
    # SDL §5.8: ``inventoryVersion`` is non-null only when an ``InventoryPosition``
    # moved. A cancellation releases a reservation; it writes no balance.
    assert inv.INVENTORY_VERSION_ATTRIBUTE not in movements[0]
    for untouched in (
        inv.KERNEL_PHYSICAL_DELTA,
        inv.WITH_SCOUT_DELTA,
        inv.SOLD_POSSESSION_DELTA,
        inv.COUNCIL_ON_ORDER_DELTA,
    ):
        assert movements[0][untouched] == 0, f"a cancellation releases a reservation, it never moves {untouched}"


def test_evt_m_03_02_cancelling_at_or_after_start_is_refused_and_changes_nothing(
    world: Dict[str, Any],
) -> None:
    """EVT-M-03-02: past ``startAt`` the event is finished by finalizing it."""
    for label, start_at, end_at in (("active", ACTIVE_START, ACTIVE_END), ("ended", ENDED_START, ENDED_END)):
        event_id = f"SSE#{label}"
        _seed_event(world["show_and_sells"], event_id, start_at=start_at, end_at=end_at, product_ids=[PRODUCT])
        _seed_allocation(world["inventory"], event_id)
        _seed_signup(world["show_and_sells"], event_id)
        refused = assert_is_error(_cancel(event_id=event_id), "CONFLICT")
        assert "has not started" in refused["message"]
        assert _stored(world["show_and_sells"], event_id)[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_SCHEDULED
        allocation = dict(
            world["inventory"].get_item(Key=ssm.event_allocation_key(CAMPAIGN, PRODUCT, event_id))["Item"]
        )
        assert allocation[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN


def test_evt_m_03_02_a_scout_may_not_cancel_and_a_second_cancel_is_refused(world: Dict[str, Any]) -> None:
    """EVT-M-03-02 / AUTH-U: the cancellation door is the Unit Admin's."""
    event_id = _cancel_ready_event(world)
    for persona in ("Devon", "Taylor", "Riley", "Blake"):
        assert_is_error(_cancel(caller=persona, event_id=event_id, key=f"cancel-{persona}"), "NOT_FOUND")
    _ok(_cancel(event_id=event_id))
    assert_is_error(_cancel(event_id=event_id, expected_version=2, key="cancel-2"), "CONFLICT")
    assert (
        len(
            [
                row
                for row in world["inventory"].query(
                    KeyConditionExpression="#pk = :pk",
                    ExpressionAttributeNames={"#pk": "pk"},
                    ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN)},
                )["Items"]
                if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE
            ]
        )
        == 1
    ), "a refused second cancel released nothing twice"


def test_evt_m_03_01_cancelling_an_empty_event_returns_empty_lists(world: Dict[str, Any]) -> None:
    event_id = _seed_event(world["show_and_sells"], "SSE#empty-event")
    answer = _ok(_cancel(event_id=event_id))
    assert answer["releasedAllocations"] == []
    assert answer["cancelledSignups"] == []
    assert answer["event"]["status"] == "CANCELLED"


def test_evt_m_03_01_one_scout_holding_two_slots_is_released_with_one_guard_bump(
    world: Dict[str, Any],
) -> None:
    """The commitment pair is per signup, the guard per Scout (§5.13).

    A Scout who holds two slots of one event has two signup rows, two commitment
    projections, and exactly one guard: bumping it twice would be a version that
    serializes against nothing, and skipping the second commitment would leave a
    blocker standing for a place that this same transaction released.
    """
    event_id = "SSE#two-slots"
    _seed_event(world["show_and_sells"], event_id)
    _seed_slot(world["show_and_sells"], event_id, slot_id="slot-1")
    _seed_slot(world["show_and_sells"], event_id, slot_id="slot-2")
    _seed_signup(world["show_and_sells"], event_id, "slot-1")
    _seed_signup(world["show_and_sells"], event_id, "slot-2")
    _seed_commitment(world["unit_campaigns"], event_id, "slot-1")
    _seed_commitment(world["unit_campaigns"], event_id, "slot-2")
    _seed_guard(world["unit_campaigns"])

    answer = _ok(_cancel(event_id=event_id))
    assert [row["slotId"] for row in answer["cancelledSignups"]] == ["slot-1", "slot-2"]
    for slot_id in ("slot-1", "slot-2"):
        slot = dict(world["show_and_sells"].get_item(Key=ssm.slot_key(event_id, slot_id))["Item"])
        assert slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 0
        commitment = dict(
            world["unit_campaigns"].get_item(
                Key=ssm.commitment_key(_profile("Devon"), FUTURE_START, CAMPAIGN, slot_id)
            )["Item"]
        )
        assert commitment[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED
    guard = dict(world["unit_campaigns"].get_item(Key=ssm.commitment_guard_key(_profile("Devon")))["Item"])
    assert guard["commitmentVersion"] == 4, "one Scout, one guard, bumped once for the whole cancellation"


def test_evt_m_03_03_a_plan_too_large_for_one_transaction_writes_nothing(world: Dict[str, Any]) -> None:
    """EVT-M-03-03: the 90-action budget is counted before any write (§8.10)."""
    event_id = "SSE#huge-event"
    products = [f"CATALOG#fixture-default#prod-{index}" for index in range(45)]
    _seed_event(world["show_and_sells"], event_id, product_ids=products)
    for product in products:
        _seed_allocation(world["inventory"], event_id, product_id=product)
    refused = assert_is_error(_cancel(event_id=event_id), "CONFLICT")
    assert "too large" in refused["message"]

    assert _stored(world["show_and_sells"], event_id)[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_SCHEDULED
    assert _marker_rows(world["show_and_sells"]) == [], "the marker rides the transaction, so nothing committed"
    allocations = world["inventory"].query(
        KeyConditionExpression="#pk = :pk",
        ExpressionAttributeNames={"#pk": "pk"},
        ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN)},
    )["Items"]
    assert len(allocations) == 45
    assert all(row[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN for row in allocations)


def test_evt_m_03_03_a_stale_version_cancels_the_whole_plan_not_half_of_it(
    world: Dict[str, Any],
) -> None:
    """EVT-M-03-03 / VER-01 and the cancellation race: a lost race leaves nothing applied."""
    event_id = _cancel_ready_event(world)
    _ok(_update(event_id=event_id, expected_version=1, key="update-1", locationName="edited first"))
    assert_is_error(_cancel(event_id=event_id, expected_version=1), "CONFLICT")

    assert _stored(world["show_and_sells"], event_id)[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_SCHEDULED
    signup = dict(
        world["show_and_sells"].get_item(
            Key={"pk": ssm.show_and_sell_pk(event_id), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
        )["Item"]
    )
    assert signup[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE
    allocation = dict(world["inventory"].get_item(Key=ssm.event_allocation_key(CAMPAIGN, PRODUCT, event_id))["Item"])
    assert allocation[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN
    guard = dict(world["unit_campaigns"].get_item(Key=ssm.commitment_guard_key(_profile("Devon")))["Item"])
    assert guard["commitmentVersion"] == 3, "the guard was not touched by the failed plan"


def test_evt_m_03_03_cancellation_requires_a_reason_and_replays_its_first_answer(
    world: Dict[str, Any],
) -> None:
    """EVT-M-03-03 / IDEM: the retry of a committed cancellation is the same answer."""
    event_id = _cancel_ready_event(world, "SSE#replay-me")
    assert_is_error(_cancel(event_id=event_id, reason=None), "INVALID_INPUT")
    assert_is_error(_cancel(event_id=event_id, reason="   "), "INVALID_INPUT")

    first = _ok(_cancel(event_id=event_id))
    again = _ok(_cancel(event_id=event_id))
    assert again == first
    assert (
        len(
            [
                row
                for row in world["inventory"].query(
                    KeyConditionExpression="#pk = :pk",
                    ExpressionAttributeNames={"#pk": "pk"},
                    ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN)},
                )["Items"]
                if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE
            ]
        )
        == 1
    )


def test_evt_m_03_05_a_cancellation_touches_and_reports_only_the_rows_it_releases(
    world: Dict[str, Any],
) -> None:
    """EVT-M-03-05: history another request closed stays history.

    A Scout who cancelled her own signup, and an allocation §3.2 released before the
    event was called off, are both terminal rows. Rewriting them moves an audit record
    this request did not create, spends a transaction action on a row that cannot
    change, and makes the result claim work the caller never did — so a replay answers a
    different set of rows than the first attempt committed.
    """
    event_id = "SSE#mixed-history"
    _seed_event(world["show_and_sells"], event_id, product_ids=[PRODUCT, OTHER_PRODUCT, RELEASED_PRODUCT])
    _seed_slot(world["show_and_sells"], event_id, active=2)
    _seed_signup(world["show_and_sells"], event_id, persona="Devon")
    _seed_commitment(world["unit_campaigns"], event_id, persona="Devon")
    _seed_signup(world["show_and_sells"], event_id, persona="Emery", status=ssm.SIGNUP_CANCELLED, version=4)
    _seed_commitment(world["unit_campaigns"], event_id, persona="Emery", status=ssm.SIGNUP_CANCELLED, version=4)
    _seed_guard(world["unit_campaigns"])
    _seed_allocation(world["inventory"], event_id, sold=2, released=1, remaining=7)
    _seed_allocation(
        world["inventory"],
        event_id,
        OTHER_PRODUCT,
        allocated=4,
        sold=0,
        released=4,
        remaining=0,
        status=inv.ALLOCATION_CANCELLED,
        version=3,
    )
    _seed_allocation(
        world["inventory"],
        event_id,
        RELEASED_PRODUCT,
        allocated=3,
        sold=3,
        released=0,
        remaining=0,
        status=inv.ALLOCATION_RELEASED,
        version=5,
    )

    answer = _ok(_cancel(event_id=event_id))
    assert [row["productId"] for row in answer["releasedAllocations"]] == [PRODUCT], (
        "an allocation another path already closed is not this cancellation's work, whether it was "
        "released by §3.2 or cancelled earlier"
    )
    assert [row["profileId"] for row in answer["cancelledSignups"]] == [_profile("Devon")]

    signup_key = {"pk": ssm.show_and_sell_pk(event_id), "sk": ssm.signup_sk("slot-1", _profile("Emery"))}
    past_signup = dict(world["show_and_sells"].get_item(Key=signup_key)["Item"])
    assert past_signup[ssm.VERSION_ATTRIBUTE] == 4, "a cancelled signup keeps the version that closed it"
    assert past_signup[ssm.UPDATED_AT_ATTRIBUTE] == FUTURE_START, "and the instant that closed it"

    commitment_key = ssm.commitment_key(_profile("Devon"), FUTURE_START, CAMPAIGN, "slot-1")
    commitment = dict(world["unit_campaigns"].get_item(Key=commitment_key)["Item"])
    past_commitment = dict(
        world["unit_campaigns"].get_item(Key=ssm.commitment_key(_profile("Emery"), FUTURE_START, CAMPAIGN, "slot-1"))[
            "Item"
        ]
    )
    assert past_commitment[ssm.VERSION_ATTRIBUTE] == 4, "a released commitment is not re-dated"

    released_signup = dict(
        world["show_and_sells"].get_item(
            Key={"pk": ssm.show_and_sell_pk(event_id), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
        )["Item"]
    )
    # §5.13 defines ``ScoutCommitment.version`` as matching the source signup's update,
    # so the pair a reader compares moves to one number, not two disagreeing ones.
    assert released_signup[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED
    assert released_signup[ssm.VERSION_ATTRIBUTE] == 2
    assert commitment[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED
    assert commitment[ssm.VERSION_ATTRIBUTE] == released_signup[ssm.VERSION_ATTRIBUTE]

    allocation = dict(
        world["inventory"].get_item(Key=ssm.event_allocation_key(CAMPAIGN, OTHER_PRODUCT, event_id))["Item"]
    )
    assert allocation[ssm.VERSION_ATTRIBUTE] == 3, "the closed allocation is not rewritten"

    again = _ok(_cancel(event_id=event_id))
    assert again == answer, "the replay answers exactly the rows the first attempt committed"

    admin = _ok(_show(event_id=event_id))
    assert {row["productId"] for row in admin["allocations"]} == {PRODUCT, OTHER_PRODUCT, RELEASED_PRODUCT}, (
        "the administrative read still shows the whole history; only the result narrows"
    )


# --- EVT-Q-01: the administrative reads (§3.1.5) --------------------------------


def test_evt_q_01_01_an_admin_reads_the_event_with_its_allocations_and_slots(
    world: Dict[str, Any],
) -> None:
    """EVT-Q-01-01: location, immutable times, split, We Owe, allocations, slots, status, version."""
    event_id = _seed_event(world["show_and_sells"], "SSE#detail", product_ids=[PRODUCT, OTHER_PRODUCT])
    _seed_slot(world["show_and_sells"], event_id, slot_id="slot-2", start_at=ACTIVE_START, end_at=ACTIVE_END)
    _seed_slot(world["show_and_sells"], event_id, slot_id="slot-1")
    _seed_allocation(world["inventory"], event_id)
    _seed_allocation(world["inventory"], event_id, product_id=OTHER_PRODUCT, status=inv.ALLOCATION_CANCELLED)

    answer = _ok(_show(event_id=event_id))
    assert answer["showAndSellId"] == event_id
    assert answer["unitId"] == PACK_3149 and answer["unitCampaignId"] == CAMPAIGN
    assert answer["status"] == "SCHEDULED"
    assert answer["version"] == 1
    assert [slot["slotId"] for slot in answer["slots"]] == ["slot-2", "slot-1"], "soonest first"
    assert answer["slots"][1]["activeSignupCount"] == 1
    found = {row["productId"]: row for row in answer["allocations"]}
    assert set(found) == {PRODUCT, OTHER_PRODUCT}
    assert found[PRODUCT]["status"] == inv.ALLOCATION_OPEN
    assert found[OTHER_PRODUCT]["status"] == inv.ALLOCATION_CANCELLED, (
        "an admin sees a released allocation, because it is part of what this event did"
    )


def test_evt_q_01_02_only_an_admin_reads_the_administrative_surface(world: Dict[str, Any]) -> None:
    """EVT-Q-01-02 / AUTH-U: a Scout and another Unit's Admin get the same answer as a missing event."""
    event_id = _seed_event(world["show_and_sells"], "SSE#detail")
    for persona in ("Devon", "Taylor", "Riley", "Blake"):
        assert_is_error(_show(caller=persona, event_id=event_id), "NOT_FOUND")
    assert_is_error(_show(event_id="SSE#nope"), "NOT_FOUND")
    assert_is_error(_list(campaign="uc-none"), "NOT_FOUND")


def test_evt_q_01_02_listing_is_ordered_and_filtered_by_state_and_window(world: Dict[str, Any]) -> None:
    """EVT-Q-01-02: soonest first, with the state and date-window filters applied server-side."""
    _seed_event(world["show_and_sells"], "SSE#ended", start_at=ENDED_START, end_at=ENDED_END)
    _seed_event(world["show_and_sells"], "SSE#active", start_at=ACTIVE_START, end_at=ACTIVE_END)
    _seed_event(world["show_and_sells"], "SSE#later", start_at=FUTURE_LATER_START, end_at=FUTURE_LATER_END)
    _seed_event(world["show_and_sells"], "SSE#cancelled", status=ssm.STATUS_CANCELLED)

    ordered = _ok(_list())
    assert [item["showAndSellId"] for item in ordered["items"]] == [
        "SSE#ended",
        "SSE#active",
        "SSE#cancelled",
        "SSE#later",
    ]
    assert [item["status"] for item in ordered["items"]] == ["ENDED", "ACTIVE", "CANCELLED", "SCHEDULED"]

    ended = _ok(_list(status="ENDED"))
    assert [item["showAndSellId"] for item in ended["items"]] == ["SSE#ended"], (
        "the filter compares the state the answer reports, not the stored spelling"
    )
    upcoming = _ok(_list(status="SCHEDULED"))
    assert [item["showAndSellId"] for item in upcoming["items"]] == ["SSE#later"]
    window = _ok(_list(dateRange={"startAt": FUTURE_START, "endAt": FUTURE_LATER_START}))
    assert [item["showAndSellId"] for item in window["items"]] == ["SSE#cancelled", "SSE#later"]
    assert_is_error(_list(dateRange={"startAt": FUTURE_LATER_START, "endAt": FUTURE_START}), "INVALID_INPUT")
    assert_is_error(_list(status="ABANDONED"), "INVALID_INPUT")


def test_page_01_an_event_cursor_belongs_to_one_filtered_page(world: Dict[str, Any]) -> None:
    """PAGE-01: the cursor is a positional claim inside one filtered result set."""
    for index in range(4):
        _seed_event(
            world["show_and_sells"],
            f"SSE#page-{index}",
            start_at=_shift(24 * (index + 1)),
            end_at=_shift(24 * (index + 1) + 4),
        )
    first = _ok(_list(page={"limit": 2}))
    assert len(first["items"]) == 2 and first["pageInfo"]["hasNextPage"] is True
    second = _ok(_list(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert len(second["items"]) == 2 and second["pageInfo"]["hasNextPage"] is False
    assert {item["showAndSellId"] for item in first["items"]}.isdisjoint(
        {item["showAndSellId"] for item in second["items"]}
    )

    cursor = first["pageInfo"]["endCursor"]
    assert_is_error(_list(page={"limit": 2, "cursor": cursor}, status="CANCELLED"), "INVALID_INPUT")
    assert_is_error(
        _list(page={"limit": 2, "cursor": cursor}, dateRange={"startAt": FUTURE_START, "endAt": FUTURE_END}),
        "INVALID_INPUT",
    )
    assert_is_error(_list(campaign=OTHER_UNIT_CAMPAIGN, page={"limit": 2, "cursor": cursor}), "INVALID_INPUT")


# --- EVT-Q-02 / EVT-Q-03: the participant surface (AUTH-P) ----------------------


def test_evt_q_02_01_a_joined_scout_reads_only_participant_safe_fields(world: Dict[str, Any]) -> None:
    """EVT-Q-02-01: participant-safe event/slot/signup fields and pageInfo, nothing else."""
    event_id = _seed_event(world["show_and_sells"], "SSE#opportunity", product_ids=[PRODUCT], we_owe_enabled=True)
    _seed_slot(world["show_and_sells"], event_id, capacity=5, active=2)
    _seed_signup(world["show_and_sells"], event_id)
    _seed_allocation(world["inventory"], event_id)

    for caller in ("Devon", "Taylor"):
        answer = _ok(_opportunities(caller=caller))
        assert [item["showAndSellId"] for item in answer["items"]] == [event_id]
        assert set(answer) == {"items", "pageInfo"}
        only = answer["items"][0]
        assert set(only) == {
            "showAndSellId",
            "locationName",
            "address",
            "startAt",
            "endAt",
            "status",
            "splitMethod",
            "weOweEnabled",
            "timezone",
            "eventVersion",
            "slots",
            "mySignups",
        }
        assert only["timezone"] == "America/Denver"
        assert only["slots"][0]["openCapacity"] == 3
        assert [signup["slotId"] for signup in only["mySignups"]] == ["slot-1"]


def test_evt_q_02_01_no_stock_sale_buyer_or_actor_field_reaches_a_participant(
    world: Dict[str, Any],
) -> None:
    """SEC-04 / AUTH-P-04: the participant answer is an allowlist, asserted by key set."""
    event_id = _seed_event(world["show_and_sells"], "SSE#allowlist", product_ids=[PRODUCT])
    _seed_slot(world["show_and_sells"], event_id)
    _seed_signup(world["show_and_sells"], event_id)
    _seed_allocation(world["inventory"], event_id)

    forbidden = {
        "unitId",
        "unitCampaignId",
        "productIds",
        "allocations",
        "approvedFinalizationId",
        "latestFinalizationId",
        "version",
        "createdAt",
        "updatedAt",
        "createdByAccountId",
        "updatedByAccountId",
        "cancelledByAccountId",
        "cancelledAt",
        "cancellationReason",
        "signedUpByAccountId",
        "confirmedByAccountId",
        "confirmedAt",
        inv.ALLOCATED_QTY,
        inv.SOLD_QTY,
        inv.RELEASED_QTY,
        inv.REMAINING_QTY,
        inv.KERNEL_PHYSICAL_QTY,
    }
    surfaces: List[Any] = []
    for answer in (_ok(_opportunities(caller="Devon")), _ok(_opportunity(event_id=event_id, caller="Devon"))):
        items = answer["items"] if "items" in answer else [answer]
        for item in items:
            surfaces.extend([item, item["slots"], item["mySignups"]])
    for surface in surfaces:
        for name in forbidden:
            assert name not in surface, f"{name} must never appear on a participant surface"

    admin = _ok(_show(event_id=event_id))
    assert "allocations" in admin and "productIds" in admin, "the same read pair keeps the two surfaces apart"


def test_evt_q_02_02_visibility_is_a_roster_fact_not_a_profile_id(world: Dict[str, Any]) -> None:
    """EVT-Q-02-02: a Scout with no standing on the campaign is told NOT_FOUND."""
    _seed_event(world["show_and_sells"], "SSE#opportunity")
    assert_is_error(_opportunities(caller="Emery"), "NOT_FOUND")
    # Riley holds a READ share, but on a Profile with no roster row here: a share is
    # not a membership, and the roster is what makes someone a participant.
    assert_is_error(_opportunities(caller="Riley"), "NOT_FOUND")
    # An Admin is not a participant: the administrative read is showAndSells.
    assert_is_error(_opportunities(caller="Avery"), "NOT_FOUND")
    assert_is_error(_opportunities(campaign="uc-none"), "NOT_FOUND")


def test_evt_q_02_02_a_campaign_with_no_roster_offers_nothing_to_anyone(world: Dict[str, Any]) -> None:
    """An empty roster is the cheapest possible proof that the caller has no Scout here.

    The event exists and the campaign exists; only the roster is empty, so the answer
    cannot be a matter of "there is nothing to show" — it is the same NOT_FOUND every
    other ineligibility gets.
    """
    lonely = "uc-pack-3149-empty-27"
    world["unit_campaigns"].put_item(
        Item=unit_campaign_item(
            lonely,
            unit_id=PACK_3149,
            campaign_name="Pack 3149 Empty Roster Show & Sell",
            campaign_year=2027,
            catalog_id="CATALOG#fixture-default",
            join_code="JOINPK3149MATE01",
            created_by="Avery",
        )
    )
    _seed_event(world["show_and_sells"], "SSE#empty-roster", campaign=lonely)
    assert_is_error(_opportunities(caller="Devon", campaign=lonely), "NOT_FOUND")
    assert_is_error(_opportunity(caller="Devon", event_id="SSE#empty-roster", persona="Devon"), "NOT_FOUND")


def test_evt_q_02_02_a_removed_scout_keeps_only_the_events_they_took_part_in(world: Dict[str, Any]) -> None:
    """EVT-Q-02-02: removal blocks a new signup and preserves the participation history."""
    joined = "SSE#past-participation"
    _seed_event(world["show_and_sells"], joined)
    _seed_event(world["show_and_sells"], "SSE#new-offering", start_at=FUTURE_LATER_START, end_at=FUTURE_LATER_END)
    _seed_signup(world["show_and_sells"], "SSE#past-participation", persona="Emery", status=ssm.SIGNUP_CANCELLED)
    _joined_and_removed(world, "Emery")

    answer = _ok(_opportunities(caller="Emery"))
    assert [item["showAndSellId"] for item in answer["items"]] == [joined]
    assert [signup["status"] for signup in answer["items"][0]["mySignups"]] == [ssm.SIGNUP_CANCELLED]


def test_evt_q_02_02_a_cancelled_event_is_never_an_opportunity(world: Dict[str, Any]) -> None:
    _seed_event(world["show_and_sells"], "SSE#cancelled-offering", status=ssm.STATUS_CANCELLED)
    _seed_signup(world["show_and_sells"], "SSE#cancelled-offering")
    answer = _ok(_opportunities(caller="Devon"))
    assert answer["items"] == []


def test_evt_q_02_02_past_events_appear_only_when_asked_for(world: Dict[str, Any]) -> None:
    _seed_event(world["show_and_sells"], "SSE#history", start_at=ENDED_START, end_at=ENDED_END)
    _seed_event(world["show_and_sells"], "SSE#upcoming")
    assert [item["showAndSellId"] for item in _ok(_opportunities(caller="Devon"))["items"]] == ["SSE#upcoming"]
    both = _ok(_opportunities(caller="Devon", includePast=True))
    assert [item["showAndSellId"] for item in both["items"]] == ["SSE#history", "SSE#upcoming"]


def test_evt_q_03_03_a_cancelled_event_is_not_a_participant_view_even_to_its_own_scout(
    world: Dict[str, Any],
) -> None:
    """EVT-Q-03-03: the two participant surfaces agree about a cancelled event.

    The campaign-level read already drops a cancelled event. If the per-event field kept
    answering it, a Scout would hold a path to a cancelled offer the list refuses, and
    the same row would have two answers.
    """
    event_id = _seed_event(world["show_and_sells"], "SSE#cancelled-view", status=ssm.STATUS_CANCELLED)
    _seed_slot(world["show_and_sells"], event_id)
    _seed_signup(world["show_and_sells"], event_id)
    assert [item["showAndSellId"] for item in _ok(_opportunities(caller="Devon"))["items"]] == []
    assert_is_error(_opportunity(caller="Devon", event_id=event_id, persona="Devon"), "NOT_FOUND")
    assert_is_error(_opportunity(caller="Avery", event_id=event_id, persona="Devon"), "NOT_FOUND")


def test_the_participant_surface_decides_authorization_from_a_strongly_consistent_roster(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The roster read behind the participant decision is the current one.

    ``active_ids``/``former_ids`` come from that read, and they decide whether a caller
    sees the campaign's whole upcoming schedule or only the events their own signup rows
    name. An eventually consistent ``ACTIVE`` row that outlives a removal would put a
    former member back in ``active_ids`` and hand them every event on the campaign.
    """
    seen: List[Dict[str, Any]] = []
    real = ucm.list_memberships

    def spy(unit_campaign_id: str, **kwargs: Any) -> List[Dict[str, Any]]:
        seen.append(kwargs)
        return real(unit_campaign_id, **kwargs)

    monkeypatch.setattr(ucm, "list_memberships", spy)
    _seed_event(world["show_and_sells"], "SSE#roster-read")
    _ok(_opportunities(caller="Devon"))
    _ok(_opportunity(caller="Devon", event_id="SSE#roster-read", persona="Devon"))

    assert seen, "the participant resolvers read the roster"
    assert all(kwargs.get("consistent_read") is True for kwargs in seen), (
        "an authorization decision may not be made from an eventually consistent roster"
    )


def test_page_01_only_the_events_on_the_page_are_hydrated(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PAGE-01: ``page.limit`` bounds the reads, not only the items.

    Slot hydration costs a partition read per event, so it happens after the page is
    cut. A campaign with a long history otherwise pays for every event on every page,
    and the caller's limit changes nothing about what the handler asked DynamoDB for.
    """
    hydrated: List[str] = []
    real = ssm.event_slot_rows

    def spy(show_and_sell_id: str) -> List[Dict[str, Any]]:
        hydrated.append(show_and_sell_id)
        return real(show_and_sell_id)

    for index in range(4):
        _seed_event(
            world["show_and_sells"],
            f"SSE#bounded-{index}",
            start_at=_shift(24 * (index + 1)),
            end_at=_shift(24 * (index + 1) + 4),
        )
    monkeypatch.setattr(ssm, "event_slot_rows", spy)

    page = _ok(_opportunities(caller="Devon", page={"limit": 2}))
    assert len(page["items"]) == 2 and page["pageInfo"]["hasNextPage"] is True
    assert len(hydrated) == 2, f"hydration ran for {hydrated}, more events than this page holds"


def test_page_01_an_opportunity_cursor_carries_the_caller_and_the_past_flag(world: Dict[str, Any]) -> None:
    for index in range(3):
        _seed_event(
            world["show_and_sells"],
            f"SSE#page-{index}",
            start_at=_shift(24 * (index + 1)),
            end_at=_shift(24 * (index + 1) + 4),
        )
    _seed_event(world["show_and_sells"], "SSE#history", start_at=ENDED_START, end_at=ENDED_END)
    first = _ok(_opportunities(caller="Devon", page={"limit": 2}))
    assert len(first["items"]) == 2 and first["pageInfo"]["hasNextPage"] is True
    cursor = first["pageInfo"]["endCursor"]
    assert_is_error(
        _opportunities(caller="Devon", page={"limit": 2, "cursor": cursor}, includePast=True), "INVALID_INPUT"
    )
    assert_is_error(_opportunities(caller="Taylor", page={"limit": 2, "cursor": cursor}), "INVALID_INPUT")


def test_evt_q_03_01_the_scout_and_a_share_holder_read_the_same_commitment_view(
    world: Dict[str, Any],
) -> None:
    """EVT-Q-03-01: Morgan reads Avery's slot view; Riley-type READ holders and the Admin too."""
    event_id = _seed_event(world["show_and_sells"], "SSE#view")
    _seed_slot(world["show_and_sells"], event_id)
    _seed_signup(world["show_and_sells"], event_id)

    own = _ok(_opportunity(caller="Devon", event_id=event_id, persona="Devon"))
    shared = _ok(_opportunity(caller="Taylor", event_id=event_id, persona="Devon"))
    admin = _ok(_opportunity(caller="Avery", event_id=event_id, persona="Devon"))
    assert own == shared == admin
    assert [slot["slotId"] for slot in own["slots"]] == ["slot-1"]
    assert [signup["signupVersion"] for signup in own["mySignups"]] == [1]


def test_evt_q_03_02_an_unjoined_scout_or_another_unit_s_event_is_not_found(
    world: Dict[str, Any],
) -> None:
    """EVT-Q-03-02: every refusal is NOT_FOUND, and none of them discloses that anything exists."""
    event_id = _seed_event(world["show_and_sells"], "SSE#view")
    _seed_slot(world["show_and_sells"], event_id)

    assert_is_error(_opportunity(caller="Emery", event_id=event_id, persona="Emery"), "NOT_FOUND")
    assert_is_error(_opportunity(caller="Riley", event_id=event_id, persona="Devon"), "NOT_FOUND")
    assert_is_error(_opportunity(caller="Devon", event_id="SSE#none", persona="Devon"), "NOT_FOUND")

    other_unit_event = _seed_event(
        world["show_and_sells"], "SSE#other-unit", campaign=OTHER_UNIT_CAMPAIGN, unit="unit-crew-529-denver"
    )
    assert_is_error(_opportunity(caller="Devon", event_id=other_unit_event, persona="Devon"), "NOT_FOUND")
    assert_is_error(_opportunity(caller="Avery", event_id=event_id, persona="Emery"), "NOT_FOUND")


def test_evt_q_03_02_a_removed_scout_sees_the_view_only_with_a_signup(world: Dict[str, Any]) -> None:
    event_id = _seed_event(world["show_and_sells"], "SSE#removed-view")
    _joined_and_removed(world, "Emery")
    assert_is_error(_opportunity(caller="Emery", event_id=event_id, persona="Emery"), "NOT_FOUND")
    _seed_signup(world["show_and_sells"], event_id, persona="Emery")
    answer = _ok(_opportunity(caller="Emery", event_id=event_id, persona="Emery"))
    assert [signup["slotId"] for signup in answer["mySignups"]] == ["slot-1"]
