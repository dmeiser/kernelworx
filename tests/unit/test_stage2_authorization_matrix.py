"""Leaf 2.8.6 — the Stage 2 authorization matrix: who may reach each of the thirteen fields.

§2.8.6 asks for one verification sweep over the whole Stage 2 surface: removed Unit Admin,
cross-Unit ``NOT_FOUND``, READ-only denial, non-owner WRITE success and revocation, global ADMIN
isolation, anonymous/API-key denial, and participant/admin output separation. The §2.2-§2.4 leaf
tests prove each rule where its own mutation lives; this card is the sweep that proves no field
forgets it, including the three §2.4 fields the Stage 2 AUTH-U sweep never walked.

Two things make the sweep worth running rather than reading:

* **Every argument block is one the Unit Admin actually succeeds with** (the control test). A denial
  that came from a malformed request would look identical in the response and prove nothing, so the
  matrix is only meaningful against requests that are otherwise valid.
* **Denial is a write-set claim too.** Every refused call is followed by a fingerprint of
  ``inventory``, ``orders`` and ``order_fulfillments``: a resolver that authorized after staging
  would leave a movement, a marker, or a bumped ``fulfillmentVersion`` behind.

The isolation rule under test is the one ``src/utils/unit_auth.py`` states: the ``UnitAccessGrant``
row is the only thing that grants Unit administration, so the app-wide ``ADMIN`` group is inert here
— neither a shortcut in, nor a reason to refuse a real admin. The global-ADMIN cases therefore carry
``cognito:groups: ["ADMIN"]`` in the event itself, and one of them pairs with the same admin wearing
the group and still getting through.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

import pytest

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    FULFILL_LINE_FIELD,
    INVENTORY_MOVEMENTS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    ISSUE_STOCK_FIELD,
    MY_SCOUT_CUSTODY_FIELD,
    ORDER_FULFILLMENTS_FIELD,
    RECORD_RECEIPT_FIELD,
    RETURN_STOCK_FIELD,
    REVERSE_FULFILLMENT_FIELD,
    SCOUT_CUSTODY_FIELD,
    UNIT_SCOUT_ORDERS_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from src.utils.dynamodb import tables
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    account_id,
    assert_is_error,
    order_line_item,
    seed_show_sell_fixtures,
    share_item,
    sold_order_item,
)

CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
SCOUT = "Devon"
SCOUT_PROFILE = str(PROFILES[SCOUT]["profileId"])
SCOUT_CAMPAIGN = str(PROFILES[SCOUT]["campaignId"])
ADMIN = "Avery"
ADMIN_PROFILE = str(PROFILES[ADMIN]["profileId"])
LINE = "line-auth-1"
ORDER_ID = "ORDER#camp-devon-fixture#auth-1"
FULFILLMENT_ID = "22222222-2222-4222-8222-222222222222"
MORNING = "2026-11-07T08:00:00+00:00"

#: The thirteen fields Stage 2 ships (§2.2-§2.4). A sweep that walks a named list cannot silently
#: stop walking one when a new query lands next to it.
STAGE_TWO_FIELDS = (
    RECORD_RECEIPT_FIELD,
    ADJUST_INVENTORY_FIELD,
    ADJUST_COUNCIL_FIELD,
    INVENTORY_POSITIONS_FIELD,
    INVENTORY_MOVEMENTS_FIELD,
    ISSUE_STOCK_FIELD,
    RETURN_STOCK_FIELD,
    SCOUT_CUSTODY_FIELD,
    MY_SCOUT_CUSTODY_FIELD,
    FULFILL_LINE_FIELD,
    REVERSE_FULFILLMENT_FIELD,
    ORDER_FULFILLMENTS_FIELD,
    UNIT_SCOUT_ORDERS_FIELD,
)

#: Twelve of the thirteen are Unit-admin surfaces. The thirteenth, ``myScoutCustody``, also has a
#: Profile door on purpose (§2.3.3), so it is swept separately — as a denial for the callers that
#: have no share, and as a success for the ones that do.
ADMIN_ONLY_FIELDS = tuple(field for field in STAGE_TWO_FIELDS if field != MY_SCOUT_CUSTODY_FIELD)

#: The Stage 2 fields that change a row.
WRITING_FIELDS = (
    RECORD_RECEIPT_FIELD,
    ADJUST_INVENTORY_FIELD,
    ADJUST_COUNCIL_FIELD,
    ISSUE_STOCK_FIELD,
    RETURN_STOCK_FIELD,
    FULFILL_LINE_FIELD,
    REVERSE_FULFILLMENT_FIELD,
)


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _page(limit: int = 10) -> Dict[str, Any]:
    return {"page": {"limit": limit}}


def arguments_for(field: str) -> Dict[str, Any]:
    """One valid request for ``field`` in the arranged world.

    Every block below is answered successfully by the campaign's own admin (see the control test),
    so a denial anywhere else in this module has the caller as its only cause.
    """
    scout_ids = {"profileId": SCOUT_PROFILE, "campaignId": SCOUT_CAMPAIGN}
    if field == RECORD_RECEIPT_FIELD:
        return {"input": {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantity": 4, **_idem("auth-receipt")}}
    if field == ADJUST_INVENTORY_FIELD:
        return {
            "input": {
                "unitCampaignId": CAMPAIGN,
                "productId": PRODUCT,
                "quantityDelta": -1,
                "reason": "recount",
                **_idem("auth-adjust"),
            }
        }
    if field == ADJUST_COUNCIL_FIELD:
        return {
            "input": {
                "unitCampaignId": CAMPAIGN,
                "productId": PRODUCT,
                "quantityDelta": 3,
                "reason": "council promised a case",
                **_idem("auth-council"),
            }
        }
    if field == INVENTORY_POSITIONS_FIELD:
        return {"unitCampaignId": CAMPAIGN}
    if field == INVENTORY_MOVEMENTS_FIELD:
        return {"unitCampaignId": CAMPAIGN, **_page()}
    if field == ISSUE_STOCK_FIELD:
        return {
            "input": {
                "unitCampaignId": CAMPAIGN,
                **scout_ids,
                "productId": PRODUCT,
                "quantity": 2,
                **_idem("auth-issue"),
            }
        }
    if field == RETURN_STOCK_FIELD:
        return {
            "input": {
                "unitCampaignId": CAMPAIGN,
                **scout_ids,
                "items": [{"productId": PRODUCT, "quantity": 1}],
                **_idem("auth-return"),
            }
        }
    if field == SCOUT_CUSTODY_FIELD:
        return {"unitCampaignId": CAMPAIGN, **_page()}
    if field == MY_SCOUT_CUSTODY_FIELD:
        return {"unitCampaignId": CAMPAIGN, **scout_ids}
    if field == FULFILL_LINE_FIELD:
        return {
            "input": {
                "orderId": ORDER_ID,
                "lineItemId": LINE,
                "quantity": 1,
                "source": "KERNEL_STOCK",
                "expectedFulfillmentVersion": 1,
                **_idem("auth-fulfill"),
            }
        }
    if field == REVERSE_FULFILLMENT_FIELD:
        return {
            "input": {
                "orderId": ORDER_ID,
                "fulfillmentId": FULFILLMENT_ID,
                "expectedFulfillmentVersion": 1,
                **_idem("auth-reverse"),
            }
        }
    if field == ORDER_FULFILLMENTS_FIELD:
        return {"orderId": ORDER_ID, **_page()}
    if field == UNIT_SCOUT_ORDERS_FIELD:
        return {"unitCampaignId": CAMPAIGN, "campaignId": SCOUT_CAMPAIGN, **_page()}
    raise AssertionError(f"no argument block for {field}")


def _event(field: str, identity: Optional[Mapping[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """The raw AppSync invoke payload, with the identity this case wants.

    Deliberately not the persona-shaped fixture helper: the API-key and claims-bearing identities
    below have no persona, and the point of those cases is the exact shape AppSync hands the Lambda.
    """
    return {
        "arguments": arguments,
        "identity": identity,
        "requestContext": {"requestId": "fixture-auth-sweep"},
        "info": {"fieldName": field, "parentTypeName": "Query"},
    }


def _call(field: str, identity: Optional[Mapping[str, Any]], arguments: Optional[Dict[str, Any]] = None) -> Any:
    return handle_unit_operation(_event(field, identity, arguments or arguments_for(field)), None)


def _persona_identity(name: str, *, groups: Optional[List[str]] = None) -> Dict[str, Any]:
    """The ``sub`` AppSync hands a signed-in persona, optionally with group claims."""
    identity: Dict[str, Any] = {"sub": account_id(name)}
    if groups is not None:
        identity["claims"] = {"sub": account_id(name), "cognito:groups": groups}
    return identity


# ---------------------------------------------------------------------------
# The arranged world: a shelf, a custody, a sale, and a fulfillment on it.
# ---------------------------------------------------------------------------


@pytest.fixture
def stage_two(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
) -> Dict[str, Any]:
    """A world where every Stage 2 argument block is valid, so denials are about the caller."""
    seeded = seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            kernel_physical_qty=10,
            sold_in_possession_qty=0,
            council_on_order_qty=0,
            now_iso=MORNING,
        )
    )
    inventory_table.put_item(
        Item=inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT_PROFILE,
            campaign_id=SCOUT_CAMPAIGN,
            with_scout_qty=3,
            now_iso=MORNING,
        )
    )
    inventory_table.put_item(
        Item=inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=ADMIN_PROFILE,
            campaign_id=str(PROFILES[ADMIN]["campaignId"]),
            with_scout_qty=2,
            now_iso=MORNING,
        )
    )
    order = sold_order_item(
        SCOUT,
        suffix="auth-1",
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        lines=[order_line_item(product_id=PRODUCT, quantity=6, line_item_id=LINE, fulfilled_quantity=1)],
    )
    order["fulfillmentVersion"] = 1
    orders_table.put_item(Item=order)
    order_fulfillments_table.put_item(
        Item=ful.build_fulfillment_item(
            fulfillment_id=FULFILLMENT_ID,
            order_id=ORDER_ID,
            campaign_id=SCOUT_CAMPAIGN,
            profile_id=SCOUT_PROFILE,
            unit_id=PACK_3149,
            unit_campaign_id=CAMPAIGN,
            line_item_id=LINE,
            product_id=PRODUCT,
            record_type=ful.RECORD_TYPE_FULFILL,
            quantity=1,
            source=ful.SOURCE_KERNEL_STOCK,
            actor_account_id=account_id(ADMIN),
            created_at=MORNING,
            inventory_movement_id="mov-auth-1",
        )
    )
    return seeded


def _rows(table: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    token: Optional[Dict[str, Any]] = None
    while True:
        kwargs: Dict[str, Any] = {}
        if token is not None:
            kwargs["ExclusiveStartKey"] = token
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            return items


def _stage_state(inventory_table: Any, orders_table: Any, order_fulfillments_table: Any) -> List[str]:
    """Every Stage 2 row, marker rows included, as one sorted list."""
    rows: List[str] = []
    for table in (inventory_table, orders_table, order_fulfillments_table):
        rows.extend(json.dumps(row, sort_keys=True, default=str) for row in _rows(table))
    return sorted(rows)


def _ok(payload: Any) -> Any:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    assert payload is not None, "the resolver answered null"
    return payload


# ---------------------------------------------------------------------------
# The control: every argument block is really valid.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", STAGE_TWO_FIELDS, ids=list(STAGE_TWO_FIELDS))
def test_the_units_own_admin_reaches_every_stage_two_field(stage_two: Dict[str, Any], field: str) -> None:
    """Without this, every denial below would be provable by a typo in the request instead."""
    _ok(_call(field, _persona_identity(ADMIN)))


# ---------------------------------------------------------------------------
# The sweep: no other caller reaches any of them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,caller",
    [(field, caller) for caller in ("Blake", "Devon", "Riley", "Taylor") for field in ADMIN_ONLY_FIELDS],
    ids=[f"{field}#{caller}" for caller in ("Blake", "Devon", "Riley", "Taylor") for field in ADMIN_ONLY_FIELDS],
)
def test_no_other_caller_reaches_a_unit_admin_stage_two_field(
    stage_two: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    field: str,
    caller: str,
) -> None:
    """A revoked admin, a Scout, another Unit's admin, and a Profile WRITE holder are all denied.

    Blake is the removed Unit Admin (his grant row is gone), Devon is the Scout whose stock and
    Orders these are, Riley is the cross-Unit admin, and Taylor holds WRITE on Devon's Profile — a
    door onto the Scout's own reads, never onto Unit stock. All four are answered exactly like a
    Unit that does not exist, so a denial never confirms that this campaign exists at all.
    """
    before = _stage_state(inventory_table, orders_table, order_fulfillments_table)

    assert_is_error(_call(field, _persona_identity(caller)), "NOT_FOUND")

    assert _stage_state(inventory_table, orders_table, order_fulfillments_table) == before, (
        "a refused request changed a Stage 2 row"
    )


def test_the_participant_door_admits_the_scout_and_the_share_holder_only(
    stage_two: Dict[str, Any], inventory_table: Any
) -> None:
    """``myScoutCustody`` is the one field with a second door, and that door is the Profile grant.

    Devon owns the Profile and Taylor holds WRITE on it, so both read Devon's custody. Riley holds
    READ on a different Scout's Profile and is refused here, which is the half that keeps the second
    door from becoming a general read.
    """
    for caller in ("Devon", "Taylor"):
        rows = _ok(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity(caller)))
        assert [row["withScoutQty"] for row in rows] == [3], f"{caller} was refused the custody they may see"

    before = _stage_state(inventory_table, tables.orders, tables.order_fulfillments)
    for caller in ("Blake", "Riley", "Emery"):
        assert_is_error(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity(caller)), "FORBIDDEN")
    assert _stage_state(inventory_table, tables.orders, tables.order_fulfillments) == before


@pytest.mark.parametrize(
    "field,identity",
    [(field, None) for field in STAGE_TWO_FIELDS]
    + [(field, {}) for field in STAGE_TWO_FIELDS]
    + [(field, {"apiKeyId": "0f8e7c1a", "sourceIp": ["198.51.100.7"], "user": False}) for field in STAGE_TWO_FIELDS],
    ids=[f"{field}#{shape}" for shape in ("no-identity", "empty-identity", "api-key") for field in STAGE_TWO_FIELDS],
)
def test_an_anonymous_or_api_key_caller_reaches_no_stage_two_field(
    stage_two: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    field: str,
    identity: Optional[Mapping[str, Any]],
) -> None:
    """No session, an empty identity, and the API-key identity are all ``UNAUTHORIZED``.

    The API-key shape is the one AppSync actually sends for the key mode — an ``apiKeyId`` and a
    source address, and no ``sub`` at all. Stage 2 has no ``@aws_api_key`` field, so the only
    correct answer is that there is nobody to authorize; a resolver that keyed off some other
    identity attribute would answer as an anonymous admin.
    """
    before = _stage_state(inventory_table, orders_table, order_fulfillments_table)

    assert_is_error(_call(field, identity), "UNAUTHORIZED")

    assert _stage_state(inventory_table, orders_table, order_fulfillments_table) == before, (
        "an unauthenticated request changed a Stage 2 row"
    )


# ---------------------------------------------------------------------------
# Global ADMIN is inert: not a way in, and not a reason to refuse a real admin.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ADMIN_ONLY_FIELDS, ids=list(ADMIN_ONLY_FIELDS))
def test_the_app_wide_admin_group_is_not_a_unit_grant(stage_two: Dict[str, Any], field: str) -> None:
    """A caller carrying ``cognito:groups: ["ADMIN"]`` and no grant is denied like anyone else.

    Riley has no grant on Pack 3149. The group claim is put in the event so the assertion is about
    the group being ignored, not about a caller who was never an ADMIN at all.
    """
    identity = _persona_identity("Riley", groups=["ADMIN"])

    assert_is_error(_call(field, identity), "NOT_FOUND")


def test_the_app_wide_admin_group_is_not_a_profile_permission(stage_two: Dict[str, Any]) -> None:
    """Nor is it a Profile permission: the participant door closes on Riley the same way.

    The two doors deny differently on purpose. The Unit door answers ``NOT_FOUND``, the same as an
    unknown Unit, so a denial never confirms that a campaign exists; the Profile door answers
    ``FORBIDDEN``, because Riley may be told the Scout exists and still lack the action.
    """
    assert_is_error(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity("Riley", groups=["ADMIN"])), "FORBIDDEN")


@pytest.mark.parametrize("field", STAGE_TWO_FIELDS, ids=list(STAGE_TWO_FIELDS))
def test_the_app_wide_admin_group_does_not_refuse_a_real_admin(stage_two: Dict[str, Any], field: str) -> None:
    """The same group on a caller who does hold the grant changes nothing.

    Inert means both halves: the group never opens a door, and it never closes one.
    """
    _ok(_call(field, _persona_identity(ADMIN, groups=["ADMIN"])))


# ---------------------------------------------------------------------------
# Profile shares: READ opens the participant read only; WRITE opens it and closes on revocation.
# ---------------------------------------------------------------------------


def test_a_read_only_share_holder_reads_the_scout_they_hold_and_writes_nothing(
    stage_two: Dict[str, Any], inventory_table: Any
) -> None:
    """Riley holds READ on Avery's Profile: that Scout's custody reads, and no write field does.

    The read is the whole point of a READ share (INV-Q-05-01); the writes move Unit stock, which a
    Profile permission has never reached. Riley asking for a Scout they do not hold is refused
    ``FORBIDDEN`` by the Profile door, so the share stays per Profile rather than becoming a read
    over every Scout in the campaign.
    """
    rows = _ok(
        _call(
            MY_SCOUT_CUSTODY_FIELD,
            _persona_identity("Riley"),
            {"unitCampaignId": CAMPAIGN, "profileId": str(PROFILES["Avery"]["profileId"])},
        )
    )
    assert [(row["profileId"], row["withScoutQty"]) for row in rows] == [(str(PROFILES["Avery"]["profileId"]), 2)]

    assert_is_error(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity("Riley")), "FORBIDDEN")

    before = _rows(inventory_table)
    for field in WRITING_FIELDS:
        assert_is_error(_call(field, _persona_identity("Riley")), "NOT_FOUND")
    assert _rows(inventory_table) == before


def test_a_write_share_holder_acts_for_the_scout_until_the_share_is_revoked(
    stage_two: Dict[str, Any], inventory_table: Any
) -> None:
    """Taylor holds WRITE on Devon's Profile, so Devon's custody read is hers until the row goes.

    This is §2.8.6's non-owner WRITE pair, run against a Stage 2 read: success while the grant row
    exists, denial the day it is deleted, with no row left behind either way.
    """
    before = _stage_state(inventory_table, tables.orders, tables.order_fulfillments)

    rows = _ok(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity("Taylor")))
    assert isinstance(rows, list) and rows, "the WRITE share holder was refused the Scout's own custody"
    assert {row["profileId"] for row in rows} == {SCOUT_PROFILE}

    tables.shares.delete_item(Key={"profileId": SCOUT_PROFILE, "targetAccountId": f"ACCOUNT#{account_id('Taylor')}"})
    assert share_item("Devon", "Taylor", "WRITE") not in _rows(tables.shares)

    denial = _call(MY_SCOUT_CUSTODY_FIELD, _persona_identity("Taylor"))
    assert isinstance(denial, dict) and denial.get("__isError"), f"a revoked share still read: {denial!r}"
    assert _stage_state(inventory_table, tables.orders, tables.order_fulfillments) == before


def test_a_unit_admin_custody_read_is_filtered_to_the_named_scout(
    stage_two: Dict[str, Any], inventory_table: Any
) -> None:
    """The Unit Admin's door returns the named Scout's rows, and naming a stranger answers empty.

    Tenancy here is the campaign partition plus the ``profileId`` filter, not the caller's claim
    about who they are asking for.
    """
    blake_profile = str(PROFILES["Blake"]["profileId"])
    rows = _ok(
        _call(
            MY_SCOUT_CUSTODY_FIELD,
            _persona_identity(ADMIN),
            {"unitCampaignId": CAMPAIGN, "profileId": blake_profile},
        )
    )
    assert rows == [], "a Unit Admin read custody belonging to a Scout outside this campaign"


# ---------------------------------------------------------------------------
# Participant/admin output separation, at the query boundary.
# ---------------------------------------------------------------------------


def test_the_two_order_surfaces_answer_different_field_sets(
    stage_two: Dict[str, Any], order_fulfillments_table: Any
) -> None:
    """The admin audit keeps the actor and movement link; the participant shape drops exactly those.

    Asserted on what the resolvers answer, not on the projection helpers: a query that started
    returning ``actorAccountId`` to a participant would not be caught by the model test.
    """
    audit = _ok(_call(ORDER_FULFILLMENTS_FIELD, _persona_identity(ADMIN)))["items"]
    assert len(audit) == 1
    row = _rows(order_fulfillments_table)[0]
    participant = ful.participant_fulfillment_payload(row)

    assert set(audit[0]) - set(participant) == set(ful.ADMIN_ONLY_FULFILLMENT_FIELDS)
    assert audit[0]["actorAccountId"] == account_id(ADMIN)
    assert "actorAccountId" not in participant and "inventoryMovementId" not in participant


def test_the_admin_order_list_carries_no_customer_contact_or_payment_fields(
    stage_two: Dict[str, Any], orders_table: Any
) -> None:
    """The fulfillment screen's Order projection is narrower than the row it reads.

    The stored Order carries ``paymentMethod``; the Stage 2 answer does not, because administering
    stock needs the Order's identity, scope and lines and nothing a participant would have to be
    protected from (§10.2).
    """
    stored = _rows(orders_table)[0]
    assert "paymentMethod" in stored, "the fixture stopped being a real Order row"

    items = _ok(_call(UNIT_SCOUT_ORDERS_FIELD, _persona_identity(ADMIN)))["items"]
    assert len(items) == 1
    assert items[0]["orderId"] == ORDER_ID
    for name in ("paymentMethod", "customerPhone", "address", "notes"):
        assert name not in items[0], f"the admin Order projection carries {name}"


def test_the_custody_projection_names_no_actor_or_movement_for_any_caller(
    stage_two: Dict[str, Any], inventory_table: Any
) -> None:
    """The same custody shape answers the admin board and the Scout, and it carries no actor field."""
    board = _ok(_call(SCOUT_CUSTODY_FIELD, _persona_identity(ADMIN)))["items"]
    own = _ok(_call(MY_SCOUT_CUSTODY_FIELD, _persona_identity(SCOUT)))

    assert board and own
    for payload in [*board, *own]:
        for name in ("actorAccountId", "inventoryMovementId", "reason", "movementId", "saleId", "orderId"):
            assert name not in payload, f"the custody payload carries {name}"
    assert {row["profileId"] for row in board} == {SCOUT_PROFILE, ADMIN_PROFILE}
