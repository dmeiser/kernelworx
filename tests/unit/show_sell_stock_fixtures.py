"""Stage 2 stock fixtures: one deterministic lane for ``SS-SM-03``, ``SS-SM-04`` and ``SS-SM-10``.

Checklist leaf 2.7.2. The smoke plan (``SHOW_AND_SELL_SMOKE_TEST_PLAN.md`` §3.3 and the
``SS-SM-03``/``SS-SM-04``/``SS-SM-10`` scenarios) is the source of every name, price and
quantity here: the three catalog products at ``$30``/``$20``/``$25``, ``Stock Admin``'s
stock-only trail, ``Door to Door``'s issue 4 → sale 3 → sale 2 → issue 2 → return 1
sequence, and ``Council Planning``'s ten-unit demand with both fulfillment sources. Those
numbers are stated once, in this module, so a scenario test that disagrees with the plan
disagrees with the fixture and the mismatch is visible instead of argued about later.

**Actor mapping.** The smoke plan's actors are Lane personas, and the personas this
repository already seeds are Avery/Blake/Taylor/Riley/Devon/Emery, so the lane's actors are:

- **Alex** (the acting Unit Admin) → ``ADMIN`` = Avery, the multi-unit owner who already
  administers Pack 3149;
- **Casey** (the second Unit Admin, SS-SM-03 step 8) → ``SECOND_ADMIN`` = Devon;
- **Morgan** (whoever records a Scout's sale) → ``RECORDER`` = Taylor, who already holds
  WRITE on a Scout profile.

This lane gets **its own Unit** (``SMOKE_PACK``) and its own Unit Campaigns rather than
writing into ``PACK_3149``'s Stage 1 fixtures: those personas and their ``adminCount`` are
what batch A's FIX-AC tests assert, and a stock lane that had to edit them would be a lane
that cannot be cleaned up.

**What goes through the product and what is arranged (FIX-AC-04).** Every receipt,
adjustment, on-order change, issue, return, fulfillment and reversal in this module is
driven through ``handle_unit_operation``, because those are the rules a stock scenario
asserts. Two things are arranged as rows, and only two:

- the ``CONSUME_SCOUT_CUSTODY`` sale (SS-SM-04 steps 2 and 3). That write is an AppSync
  pipeline step (``tofu/application/appsync/js-resolvers/lib/custody_sale.js``), not a
  Lambda, and it is pinned by ``create_order_fn.test.js`` and ``custody_sale.test.js``.
  :func:`arrange_custody_sale` reproduces its row-level effect — the Order line's
  ``fulfilledQuantity``, the ``SCOUT_CUSTODY`` fulfillment, the ``INDIVIDUAL_FULFILL``
  movement and the custody decrement — using the same production builders, and skips the
  Order idempotency marker and the ``totalOrders`` counter ADD, which no stock assertion
  reads. A scenario built on it therefore asserts custody arithmetic and never the sale's
  own write;
- the Show & Sell stock assignment (SS-SM-10 step 2). The allocation row comes from
  production's own builder; the ``EVENT_ASSIGN`` write belongs to §3.2 and has not landed,
  so no ``EVENT_ASSIGN`` movement is invented to fill the gap, and
  :func:`movement_trail_violations` does not try to reconcile the assigned column.

**Lane cleanup.** :func:`clean_stage2_lane` removes one lane's Stage 2 records — inventory
balances, custody rows, movements, allocations, markers, Orders and fulfillment history —
addressed by the lane's own Unit Campaign ids, and nothing else. Leaf 2.8.7 runs it, and
``test_show_sell_stock_fixtures.py`` proves that a canary campaign on the same Unit and the
Stage 1 persona rows survive it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from botocore.exceptions import ClientError

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    FULFILL_LINE_FIELD,
    INVENTORY_MOVEMENTS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    ISSUE_STOCK_FIELD,
    RECORD_RECEIPT_FIELD,
    RETURN_STOCK_FIELD,
    REVERSE_FULFILLMENT_FIELD,
    SCOUT_CUSTODY_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from src.utils.dynamodb import get_dynamodb_client, tables
from src.utils.mutations import MarkerKeys, WritePlan, marker_keys
from tests.unit.show_sell_fixtures import (
    PROFILES,
    account_id,
    catalog_item,
    grant_item,
    join_code_pointer_item,
    order_line_item,
    sold_order_item,
    unit_campaign_item,
    unit_campaign_membership_item,
    unit_item,
    unit_operation_event,
)

# ---------------------------------------------------------------------------
# The lane's identity (smoke plan §3.1, FIX-AC-03).
#
# ``DATA_ID`` is the plan's ``<RUN_ID>-<SCENARIO_ID>-<LANE_ID>-<ATTEMPT_ID>``, and every
# entity id, idempotency key and stamp in a lane is derived from it. A lane is therefore a
# value, not a set of module constants: two attempts of one scenario, run at the same time
# or one after a failure, hold different ids, so they cannot replay each other's writes
# through a shared idempotency key or delete each other's rows during cleanup.
#
# :data:`DEFAULT_LANE` keeps the plan's numbers reproducible for the fidelity tests in
# ``test_show_sell_stock_fixtures.py``; :meth:`SmokeLane.new` is what a scenario run uses,
# and it is what :func:`clean_stage2_lane` can address without touching another attempt.
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    """``RUN_ID`` as the plan spells it: UTC epoch seconds plus a short uuid4 tail."""
    return f"{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:6]}"


def _new_attempt_id() -> str:
    """``ATTEMPT_ID``: fresh for every attempt, including every retry of a failed one."""
    return uuid.uuid4().hex[:6]


@dataclass(frozen=True)
class SmokeLane:
    """One scenario attempt's identity, and everything derived from it.

    Nothing in here is a calendar date or a fixed suffix. The Unit, Unit Campaigns, catalog,
    products, Show & Sell, Order suffixes, line identities and idempotency keys all carry
    ``data_id``, which is what makes a lane's rows addressable as one set — by the cleanup
    sweep, by the demand and sales readers, and by a second attempt that has to be able to
    sit beside the first.
    """

    data_id: str
    t0: datetime
    run_id: str = ""
    lane_id: str = "L01"
    scenario_id: str = ""
    attempt_id: str = ""

    @classmethod
    def new(
        cls,
        scenario_id: str,
        *,
        run_id: Optional[str] = None,
        lane_id: str = "L01",
        attempt_id: Optional[str] = None,
        t0: Optional[datetime] = None,
    ) -> "SmokeLane":
        """A lane for one fresh attempt: nothing in it collides with an earlier attempt."""
        run = run_id or _new_run_id()
        attempt = attempt_id or _new_attempt_id()
        return cls(
            data_id=f"{run}-{scenario_id}-{lane_id}-{attempt}",
            t0=t0 or datetime.now(timezone.utc).replace(microsecond=0),
            run_id=run,
            lane_id=lane_id,
            scenario_id=scenario_id,
            attempt_id=attempt,
        )

    # --- ids ------------------------------------------------------------------

    @property
    def pack(self) -> str:
        """The lane's own Pack 3149 (``SMOKE_PACK``)."""
        return f"unit-{self.data_id}-pack-3149"

    @property
    def catalog_id(self) -> str:
        return f"CATALOG#smoke-popcorn-{self.data_id}"

    @property
    def caramel(self) -> str:
        return f"{self.catalog_id}#caramel-popcorn"

    @property
    def butter(self) -> str:
        return f"{self.catalog_id}#butter-popcorn"

    @property
    def chocolate(self) -> str:
        return f"{self.catalog_id}#chocolate-popcorn"

    @property
    def products(self) -> Dict[str, Tuple[str, Decimal]]:
        """``productId -> (productName, price per ONE inventory unit)`` — §3.3 verbatim.

        One unit is one sale unit: this catalog carries no case quantities or conversions.
        """
        return {
            self.caramel: (f"Caramel Popcorn {self.data_id}", Decimal("30.00")),
            self.butter: (f"Butter Popcorn {self.data_id}", Decimal("20.00")),
            self.chocolate: (f"Chocolate Popcorn {self.data_id}", Decimal("25.00")),
        }

    @property
    def four_box(self) -> str:
        return f"uc-{self.data_id}-fall-popcorn"

    @property
    def stock_admin(self) -> str:
        return f"uc-{self.data_id}-stock-admin"

    @property
    def door_to_door(self) -> str:
        return f"uc-{self.data_id}-door-to-door"

    @property
    def council_planning(self) -> str:
        return f"uc-{self.data_id}-council-planning"

    @property
    def canary_campaign(self) -> str:
        """A campaign on the same Unit this lane never writes to: the cleanup survivor."""
        return f"uc-{self.data_id}-split-math"

    @property
    def unit_campaigns(self) -> Dict[str, str]:
        """Every campaign this lane seeds, including the canary it never writes to."""
        suffixes = {
            self.four_box: "Fall Popcorn 2026",
            self.stock_admin: "Stock Admin",
            self.door_to_door: "Door to Door",
            self.council_planning: "Council Planning",
            self.canary_campaign: "Split Math",
        }
        return {campaign_id: f"{name} {self.data_id}" for campaign_id, name in suffixes.items()}

    @property
    def stock_campaign_ids(self) -> List[str]:
        """The four campaigns the scenarios write to; the canary is deliberately absent.

        Cleanup and the demand/sales readers address a lane through this list, so a canary
        that shares the Unit and the Scout Campaigns is not swept with them.
        """
        return [self.four_box, self.stock_admin, self.door_to_door, self.council_planning]

    @property
    def council_booth(self) -> str:
        """The isolated future Show & Sell SS-SM-10 step 2 assigns four Kernels to."""
        return f"SSE#{self.data_id}-council-future-booth"

    @property
    def council_line_id(self) -> str:
        """The one line on Council Customer's ten-unit Order.

        Named because §2.4.3 addresses a fulfillment by ``lineItemId``, and a scenario that
        fulfills the same line twice has to name the same id rather than hope a builder
        regenerates it. It is attempt-scoped for the same reason the Order suffix is: two
        attempts' Orders sit in one Scout Campaign partition.
        """
        return f"line-{self.attempt_key}-council-10"

    # --- time and keys --------------------------------------------------------

    def moment(self, step: int) -> str:
        """One lane stamp: ``t0`` plus ``step`` minutes, in the ``+00:00`` spelling.

        ``occurredAt`` is part of a movement's sort key, so a scenario that asserts the order
        of a history needs stamps tied to when its own setup ran.
        """
        return (self.t0 + timedelta(minutes=step)).isoformat()

    def key(self, label: str) -> str:
        """An idempotency key that belongs to this attempt and to this one write.

        A fixed key is the collision FIX-AC-03 exists to prevent: a retried attempt would
        answer the earlier attempt's stored result instead of performing the write, and a
        lane's cleanup could not tell its own markers from another attempt's.
        """
        return f"{self.data_id}-{label}"[:_IDEMPOTENCY_KEY_LIMIT]

    def order_suffix(self, tag: str) -> str:
        """An Order id suffix unique to this attempt.

        An Order id is ``ORDER#<bare Scout Campaign>#<suffix>``, and the Scout Campaigns are
        the shared Stage 1 personas, so the suffix is the only part a lane can make its own.
        """
        return f"{self.attempt_key}-{tag}"

    def line_id(self, tag: str) -> str:
        """A line identity unique to this attempt (§5.19 addresses a line by this id)."""
        return f"line-{self.attempt_key}-{tag}"

    @property
    def attempt_key(self) -> str:
        """The short tail every id inside a shared partition carries."""
        return self.attempt_id or self.data_id

#: The reproducible lane the plan-fidelity tests assert against: the same ids every run, so a
#: number that disagrees with §3.3 is a fixture bug rather than a different attempt.
DEFAULT_LANE = SmokeLane(data_id="smoke3149", t0=datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc))

#: The reference lane's ``DATA_ID``, kept for the fidelity tests that name the plan's row.
DATA_ID = DEFAULT_LANE.data_id

SMOKE_PACK = DEFAULT_LANE.pack

SMOKE_CATALOG_ID = DEFAULT_LANE.catalog_id
CARAMEL = DEFAULT_LANE.caramel
BUTTER = DEFAULT_LANE.butter
CHOCOLATE = DEFAULT_LANE.chocolate

#: ``productId -> (productName, price per ONE inventory unit)``, as the reference lane spells
#: them. ``SmokeLane.products`` is the same table for any lane.
SMOKE_PRODUCTS: Dict[str, Tuple[str, Decimal]] = DEFAULT_LANE.products

FOUR_BOX = DEFAULT_LANE.four_box
STOCK_ADMIN = DEFAULT_LANE.stock_admin
DOOR_TO_DOOR = DEFAULT_LANE.door_to_door
COUNCIL_PLANNING = DEFAULT_LANE.council_planning
#: A campaign on the same Unit that this lane never writes to: the survivor of the cleanup
#: canary, named after one of the smoke plan's other isolated Unit Campaigns.
CANARY_CAMPAIGN = DEFAULT_LANE.canary_campaign

#: The isolated future Show & Sell that SS-SM-10 step 2 assigns four Kernels to.
COUNCIL_BOOTH = DEFAULT_LANE.council_booth

#: The one line on Council Customer's ten-unit Order on the reference lane.
COUNCIL_LINE_ID = DEFAULT_LANE.council_line_id

SMOKE_UNIT_CAMPAIGNS: Dict[str, str] = DEFAULT_LANE.unit_campaigns

ADMIN = "Avery"
SECOND_ADMIN = "Devon"
RECORDER = "Taylor"

#: Scouts on this lane's rosters. Both are Stage 1 personas, so the profile and campaign
#: ids a custody or Order row names are ids the rest of the suite already knows.
SMOKE_SCOUTS: Tuple[str, ...] = (ADMIN, SECOND_ADMIN)

#: SS-SM-04's starting stock and SS-SM-05's four-box count, in the plan's own numbers.
BUTTER_START_QTY = 10
CARAMEL_FOUR_BOX_QTY = 4

#: Deterministic moments for :data:`DEFAULT_LANE`. ``SmokeLane.moment`` is the same rule for
#: any lane, computed from that lane's own ``t0``.
LANE_T0 = DEFAULT_LANE.t0


def moment(step: int) -> str:
    """One ``DEFAULT_LANE`` stamp; see :meth:`SmokeLane.moment`."""
    return DEFAULT_LANE.moment(step)


def _join_code(tag: str, scope: str) -> str:
    """A 16-character Unit Campaign join code, unique to this lane's campaign.

    The tag says which campaign it is; the digest tail carries the lane's ``DATA_ID``, so two
    attempts of one scenario hold different codes and a join-code pointer row from attempt one
    is never in attempt two's way (data model §6.6 fixes the length at 16).
    """
    tail = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:6].upper()
    return f"JN{tag.upper()[:7]}{tail}".ljust(16, "0")[:16]


_IDEMPOTENCY_KEY_LIMIT = 128


# ---------------------------------------------------------------------------
# Seeding: the Unit and its two admins, the lane's Unit Campaigns, and its catalog.
# ---------------------------------------------------------------------------


def smoke_catalog_item(lane: SmokeLane = DEFAULT_LANE) -> Dict[str, Any]:
    """The smoke catalog row: three products, three prices, one sale unit each (§3.3)."""
    products = [
        {
            "productId": product_id,
            "productName": name,
            "description": f"Smoke catalog product {index} (one unit is one sale unit)",
            "price": price,
            "sortOrder": index,
        }
        for index, (product_id, (name, price)) in enumerate(lane.products.items(), start=1)
    ]
    return catalog_item(lane.catalog_id, f"Smoke Popcorn Catalog {lane.data_id}", owner=ADMIN, products=products)


def smoke_join_codes(lane: SmokeLane = DEFAULT_LANE) -> Dict[str, str]:
    """Each of this lane's Unit Campaigns' join codes, so a test can name one without rebuilding it."""
    return {campaign_id: _join_code(campaign_id.split("-")[-1], f"{lane.data_id}|{campaign_id}") for campaign_id in lane.unit_campaigns}


def smoke_unit_metadata_item(lane: SmokeLane = DEFAULT_LANE) -> Dict[str, Any]:
    """This lane's Unit row at ``UNIT#<unitId> / METADATA``."""
    return unit_item(
        lane.pack,
        "Pack",
        3149,
        "Aurora",
        "CO",
        split_default="TIME_WORKED",
        council_need_basis="PHYSICAL_STOCK",
        display_name=f"Pack 3149 {lane.data_id}",
        created_by=account_id(ADMIN),
        admin_count=2,
    )


def seed_smoke_lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    *,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """Write this lane's Unit, Unit Campaigns, rosters and catalog, and return what landed.

    The Unit carries two admins because SS-SM-03 step 8 is a permission claim: Casey's
    equal Unit Admin grant has to be a real ``GRANT#`` row for the second receipt and its
    movement to name Casey rather than Alex. The rosters are what §2.3.1's eligibility gate
    reads, so an issue to a Scout with no membership row here is a ``NOT_FOUND`` and not a
    fixture bug.

    The membership guard row (``SCOUT_CAMPAIGN#…/MEMBERSHIP_GUARD``) is deliberately absent:
    the guard belongs to the join path, and §2.3.1 gates a stock issue on the roster row
    alone. A guard naming one campaign active would also contradict the other smoke
    campaigns this lane keeps the same Scout on.
    """
    written_units = _seed_smoke_unit(units_table, lane)
    written_campaigns = _seed_smoke_campaigns(unit_campaigns_table, lane)
    catalog = smoke_catalog_item(lane)
    catalogs_table.put_item(Item=catalog)
    return {"units": written_units, "unit_campaigns": written_campaigns, "catalogs": [catalog]}


def _seed_smoke_unit(units_table: Any, lane: SmokeLane = DEFAULT_LANE) -> List[Dict[str, Any]]:
    """Pack 3149 ``<DATA_ID>`` with Alex and Casey as its two Unit Admins."""
    written: List[Dict[str, Any]] = []
    metadata = smoke_unit_metadata_item(lane)
    units_table.put_item(Item=metadata)
    written.append(metadata)
    for admin in (ADMIN, SECOND_ADMIN):
        grant = grant_item(lane.pack, admin, created_by=ADMIN)
        units_table.put_item(Item=grant)
        written.append(grant)
    return written


def _seed_smoke_campaigns(unit_campaigns_table: Any, lane: SmokeLane = DEFAULT_LANE) -> List[Dict[str, Any]]:
    """The lane's five Unit Campaigns, their join-code pointers, and their rosters."""
    written: List[Dict[str, Any]] = []
    codes = smoke_join_codes(lane)
    for campaign_id, campaign_name in lane.unit_campaigns.items():
        item = unit_campaign_item(
            campaign_id,
            unit_id=lane.pack,
            campaign_name=campaign_name,
            campaign_year=2026,
            catalog_id=lane.catalog_id,
            join_code=codes[campaign_id],
            created_by=ADMIN,
        )
        unit_campaigns_table.put_item(Item=item)
        written.append(item)
        pointer = join_code_pointer_item(codes[campaign_id], campaign_id)
        unit_campaigns_table.put_item(Item=pointer)
        written.append(pointer)
        written.extend(_seed_smoke_roster(unit_campaigns_table, campaign_id, lane))
    return written


def _seed_smoke_roster(
    unit_campaigns_table: Any, campaign_id: str, lane: SmokeLane = DEFAULT_LANE
) -> List[Dict[str, Any]]:
    """This campaign's ACTIVE roster rows — Alex and Casey, each also a Scout."""
    written: List[Dict[str, Any]] = []
    for scout in SMOKE_SCOUTS:
        membership = unit_campaign_membership_item(
            campaign_id,
            lane.pack,
            str(PROFILES[scout]["campaignId"]),
            str(PROFILES[scout]["profileId"]),
            joined_by=scout,
        )
        unit_campaigns_table.put_item(Item=membership)
        written.append(membership)
    return written


# ---------------------------------------------------------------------------
# The resolvers, one named call each. Nothing here invents a row: every mutation goes
# through the deployed handler, which is what makes a fixture usable as evidence.
# ---------------------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """One resolver turn through the deployed entry point."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def record_receipt(
    campaign: str,
    product_id: str,
    quantity: int,
    *,
    caller: str = ADMIN,
    key: str,
    occurred_at: Optional[str] = None,
) -> Any:
    """``recordInventoryReceipt``: stock arriving (§2.2.1)."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": product_id,
        "quantity": quantity,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(RECORD_RECEIPT_FIELD, caller, mutation=mutation)


def stock_adjust(
    campaign: str,
    product_id: str,
    delta: int,
    reason: str,
    *,
    caller: str = ADMIN,
    key: str,
    occurred_at: Optional[str] = None,
) -> Any:
    """``adjustInventory``: a reasoned, signed, stock-only correction (§2.2.2)."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": product_id,
        "quantityDelta": delta,
        "reason": reason,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(ADJUST_INVENTORY_FIELD, caller, mutation=mutation)


def council_on_order(
    campaign: str,
    product_id: str,
    delta: int,
    reason: str,
    *,
    caller: str = ADMIN,
    key: str,
    occurred_at: Optional[str] = None,
) -> Any:
    """``adjustCouncilOnOrder``: the expected-supply column and nothing else (§2.2.3)."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "productId": product_id,
        "quantityDelta": delta,
        "reason": reason,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(ADJUST_COUNCIL_FIELD, caller, mutation=mutation)


def issue_to_scout(
    campaign: str,
    scout: str,
    product_id: str,
    quantity: int,
    *,
    caller: str = ADMIN,
    key: str,
    occurred_at: Optional[str] = None,
) -> Any:
    """``issueStockToScout``: unassigned Kernel stock into one Scout's custody (§2.3.1)."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "campaignId": str(PROFILES[scout]["campaignId"]),
        "profileId": str(PROFILES[scout]["profileId"]),
        "productId": product_id,
        "quantity": quantity,
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(ISSUE_STOCK_FIELD, caller, mutation=mutation)


def return_from_scout(
    campaign: str,
    scout: str,
    items: Sequence[Tuple[str, int]],
    *,
    caller: str = ADMIN,
    key: str,
    occurred_at: Optional[str] = None,
) -> Any:
    """``returnStockFromScout``: one whole-batch return, which is §2.6.2's one-click return."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": campaign,
        "campaignId": str(PROFILES[scout]["campaignId"]),
        "profileId": str(PROFILES[scout]["profileId"]),
        "items": [{"productId": product_id, "quantity": quantity} for product_id, quantity in items],
        **_idem(key),
    }
    if occurred_at is not None:
        mutation["occurredAt"] = occurred_at
    return _call(RETURN_STOCK_FIELD, caller, mutation=mutation)


def fulfill_line(
    order_id: str,
    line_item_id: str,
    quantity: int,
    source: str,
    *,
    version: int,
    caller: str = ADMIN,
    key: str,
) -> Any:
    """``fulfillIndividualOrderLine`` from Kernel stock or from outside it (§2.4.3)."""
    return _call(
        FULFILL_LINE_FIELD,
        caller,
        mutation={
            "orderId": order_id,
            "lineItemId": line_item_id,
            "quantity": quantity,
            "source": source,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def reverse_fulfillment(
    order_id: str, fulfillment_id: str, *, version: int, caller: str = ADMIN, key: str
) -> Any:
    """``reverseIndividualOrderFulfillment``: restore demand and its original source (§2.4.4)."""
    return _call(
        REVERSE_FULFILLMENT_FIELD,
        caller,
        mutation={
            "orderId": order_id,
            "fulfillmentId": fulfillment_id,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def positions(campaign: str, product_ids: Optional[Sequence[str]] = None, *, caller: str = ADMIN) -> Any:
    """``inventoryPositions``, with the §7 derived quantities computed server-side (§2.2.4)."""
    arguments: Dict[str, Any] = {"unitCampaignId": campaign}
    if product_ids is not None:
        arguments["productIds"] = list(product_ids)
    return _call(INVENTORY_POSITIONS_FIELD, caller, arguments=arguments)


def movement_history(campaign: str, *, caller: str = ADMIN, **filters: Any) -> Any:
    """``inventoryMovements`` newest-first with the §5.8 filters (§2.2.4)."""
    arguments: Dict[str, Any] = {"unitCampaignId": campaign}
    arguments.update({name: value for name, value in filters.items() if value is not None})
    return _call(INVENTORY_MOVEMENTS_FIELD, caller, arguments=arguments)


def custody_balances(campaign: str, *, caller: str = ADMIN, **filters: Any) -> Any:
    """``scoutCustodyBalances``: per Scout, per product, and the aggregate (§2.3.3)."""
    arguments: Dict[str, Any] = {"unitCampaignId": campaign}
    arguments.update({name: value for name, value in filters.items() if value is not None})
    return _call(SCOUT_CUSTODY_FIELD, caller, arguments=arguments)


# ---------------------------------------------------------------------------
# Reading stored rows: the fixture's own view, independent of the resolver's.
# ---------------------------------------------------------------------------


def lane_inventory_rows(inventory_table: Any, unit_campaign_id: str) -> List[Dict[str, Any]]:
    """Every inventory row of one Unit Campaign, in sort-key order, paging to the end."""
    items: List[Dict[str, Any]] = []
    token: Optional[Dict[str, Any]] = None
    while True:
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": inv.inventory_pk(unit_campaign_id)},
        }
        if token is not None:
            kwargs["ExclusiveStartKey"] = token
        page = inventory_table.query(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            break
    return items


def product_rows(inventory_table: Any, unit_campaign_id: str, product_id: str) -> List[Dict[str, Any]]:
    """One product's rows: balance, allocations, custody, and its whole movement trail."""
    prefix = inv.product_scope_prefix(product_id)
    return [
        row for row in lane_inventory_rows(inventory_table, unit_campaign_id) if str(row["sk"]).startswith(prefix)
    ]


def _of_type(rows: Iterable[Dict[str, Any]], entity_type: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == entity_type]


def _qty(item: Optional[Mapping[str, Any]], name: str) -> int:
    """A stored count as ``int``; a row that does not carry one reads as zero."""
    if item is None:
        return 0
    return int(item.get(name, 0) or 0)


def stock_picture(inventory_table: Any, unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    """One product's whole stock picture: stored rows read directly, derived by §7 code.

    Deliberately a second view next to ``inventoryPositions``: the resolvers answer through
    the accessor, this reads the table, and every quantity the derived set reports comes
    from :func:`src.utils.inventory_models.derived_inventory_quantities` rather than from a
    number this module typed.
    """
    rows = product_rows(inventory_table, unit_campaign_id, product_id)
    balance = next(iter(_of_type(rows, inv.BALANCE_ENTITY_TYPE)), None)
    allocations = _of_type(rows, inv.ALLOCATION_ENTITY_TYPE)
    custody = _of_type(rows, inv.CUSTODY_ENTITY_TYPE)
    picture: Dict[str, Any] = {
        "kernelPhysicalQty": _qty(balance, inv.KERNEL_PHYSICAL_QTY),
        "soldInPossessionQty": _qty(balance, inv.SOLD_IN_POSSESSION_QTY),
        "councilOnOrderQty": _qty(balance, inv.COUNCIL_ON_ORDER_QTY),
        "balanceVersion": _qty(balance, inv.VERSION_ATTRIBUTE),
        "custodyRows": [
            {"profileId": str(row[inv.PROFILE_ID_ATTRIBUTE]), "withScoutQty": _qty(row, inv.WITH_SCOUT_QTY)}
            for row in custody
        ],
        "allocations": [
            {"showAndSellId": str(row[inv.SHOW_AND_SELL_ID_ATTRIBUTE]), "remainingQty": _qty(row, inv.REMAINING_QTY)}
            for row in allocations
        ],
    }
    picture.update(inv.derived_inventory_quantities(balance, allocations, custody))
    return picture


def movement_trail_violations(inventory_table: Any, unit_campaign_id: str, product_id: str) -> List[str]:
    """Every way one product's movement trail fails to explain its balances.

    This is the reconciliation leaf 2.8.7 asks for: the audit trail and the aggregate are
    two records of one history, so the summed deltas have to equal the stored quantities,
    and no row of the trail may break the append-only shape. A non-empty list is a bug in
    the product or in the fixture, and each string names which column is out.

    The assigned column is not reconciled. Its ``EVENT_ASSIGN`` write is §3.2's and does
    not exist yet, so a lane holding an allocation row (SS-SM-10) has an assigned quantity
    with no movement behind it by construction, and inventing a movement to balance the
    column would hide that — the opposite of what a checker is for.
    """
    rows = product_rows(inventory_table, unit_campaign_id, product_id)
    movements = _of_type(rows, inv.MOVEMENT_ENTITY_TYPE)
    violations: List[str] = []
    for movement in movements:
        for text in inv.movement_row_violations(movement):
            violations.append(f"movement {movement.get(inv.MOVEMENT_ID_ATTRIBUTE)}: {text}")

    totals = {name: sum(_qty(row, name) for row in movements) for name in inv.MOVEMENT_DELTA_ATTRIBUTES}
    balance = next(iter(_of_type(rows, inv.BALANCE_ENTITY_TYPE)), None)
    pairs = [
        (inv.KERNEL_PHYSICAL_DELTA, inv.KERNEL_PHYSICAL_QTY),
        (inv.SOLD_POSSESSION_DELTA, inv.SOLD_IN_POSSESSION_QTY),
        (inv.COUNCIL_ON_ORDER_DELTA, inv.COUNCIL_ON_ORDER_QTY),
    ]
    for delta_name, qty_name in pairs:
        if totals[delta_name] != _qty(balance, qty_name):
            violations.append(
                f"sum({delta_name}) = {totals[delta_name]} but the balance carries {qty_name} = "
                f"{_qty(balance, qty_name)}"
            )
    held = sum(_qty(row, inv.WITH_SCOUT_QTY) for row in _of_type(rows, inv.CUSTODY_ENTITY_TYPE))
    if totals[inv.WITH_SCOUT_DELTA] != held:
        violations.append(f"sum({inv.WITH_SCOUT_DELTA}) = {totals[inv.WITH_SCOUT_DELTA]} but custody holds {held}")
    return violations


def _paged(table: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Every item a Query or Scan answers, following ``LastEvaluatedKey`` to the end.

    One DynamoDB page is capped at 1 MB, and the Scout Campaign partition is shared by every
    lane that sells through it, so a single call answers a prefix of the rows. A fixture that
    reads a prefix and calls it the whole list reports a lane's demand, its sales, and its
    own leftover Orders as short, and the cleanup sweep would leave the rest behind.
    """
    items: List[Dict[str, Any]] = []
    while True:
        page = table.query(**kwargs) if "KeyConditionExpression" in kwargs else table.scan(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if token is None:
            return items
        kwargs["ExclusiveStartKey"] = token


def order_rows(orders_table: Any, campaign_id: str) -> List[Dict[str, Any]]:
    """Every Order of one Scout Campaign — which is every lane's, not just this one's.

    The orders table is hash-keyed on the Scout Campaign, and Scout Campaigns are the shared
    Stage 1 personas, so this read answers other lanes' Orders too. Anything that counts a
    lane's demand or sales goes through :func:`lane_orders` instead.
    """
    return _paged(
        orders_table,
        KeyConditionExpression="campaignId = :c",
        ExpressionAttributeValues={":c": campaign_id},
    )


def lane_orders(orders_table: Any, unit_campaign_ids: Sequence[str]) -> List[Dict[str, Any]]:
    """The Orders whose immutable originating scope is one of this lane's campaigns.

    Origin scope is what makes a read, and the sweep that follows it, lane-scoped: an Order is
    addressed by the Scout Campaign that sold it, and Scout Campaigns are shared between
    lanes, while ``unitCampaignId`` is only ever the campaign that stood behind that sale.
    Fixture tables are small, so the filter runs after the read, as ``cascade_delete_unit``
    does it.
    """
    wanted = set(unit_campaign_ids)
    return [row for row in _paged(orders_table) if str(row.get("unitCampaignId")) in wanted]


def demand_counts(orders_table: Any, unit_campaign_ids: Sequence[str], product_id: str) -> Dict[str, int]:
    """Ordered / fulfilled / unfulfilled units of one product across this lane's campaigns.

    Unfulfilled individual demand is what Council Needs subtracts stock from, and it is a
    per-line number: a line of four with one fulfilled still asks for three. The orders table
    is keyed on the Scout Campaign, which every lane sharing this Scout also writes to, so the
    read is scoped by originating Unit Campaign — otherwise another lane's Order, or this
    lane's own canary campaign, joins the count and the promised ten units stop being ten.
    """
    ordered = fulfilled = 0
    for order in lane_orders(orders_table, unit_campaign_ids):
        for line in order.get(ful.LINE_ITEMS_ATTRIBUTE, []):
            if str(line.get(ful.PRODUCT_ID_ATTRIBUTE)) != product_id:
                continue
            ordered += _qty(line, "quantity")
            fulfilled += _qty(line, ful.FULFILLED_QUANTITY_ATTRIBUTE)
    return {"orderedQty": ordered, "fulfilledQty": fulfilled, "unfulfilledQty": ordered - fulfilled}


def sale_totals(orders_table: Any, unit_campaign_ids: Sequence[str]) -> Dict[str, Any]:
    """Dollars and units across this lane's individual sales (SS-SM-04 step 4).

    Scoped by originating Unit Campaign, not by Scout Campaign: the same Scout sells for
    several campaigns and several lanes, and the plan's five sold units are the ones this
    campaign owes stock for.
    """
    money = Decimal("0")
    orders = 0
    units = fulfilled = 0
    for order in lane_orders(orders_table, unit_campaign_ids):
        orders += 1
        money += Decimal(str(order.get("totalAmount", 0)))
        for line in order.get(ful.LINE_ITEMS_ATTRIBUTE, []):
            units += _qty(line, "quantity")
            fulfilled += _qty(line, ful.FULFILLED_QUANTITY_ATTRIBUTE)
    return {"orderCount": orders, "money": money, "units": units, "fulfilledQty": fulfilled}


def council_needs(demand_qty: int, picture: Mapping[str, Any]) -> Dict[str, int]:
    """Council Needs on both bases, from one read (SS-SM-10 steps 2-4).

    ``PHYSICAL_STOCK`` subtracts what the Unit physically holds that it could sell;
    ``AFTER_ASSIGNMENTS`` subtracts what is left after tomorrow's Show & Sell has taken its
    assignment. A Unit shows both and presents one, so both come back rather than whichever
    basis the Unit's preference happens to name. Floored at zero because a need below zero
    is not a quantity a Kernel can go and buy.
    """
    return {
        "PHYSICAL_STOCK": max(0, demand_qty - int(picture["sellableKernelQty"])),
        "AFTER_ASSIGNMENTS": max(0, demand_qty - int(picture["unassignedKernelQty"])),
    }


# ---------------------------------------------------------------------------
# Arranged rows: the custody sale (§2.4.2) and the event assignment (§3.2).
# ---------------------------------------------------------------------------


def smoke_line(
    product_id: str,
    quantity: int,
    line_item_id: str,
    *,
    fulfilled_quantity: int = 0,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """One catalog-priced line: the price always comes from §3.3, never from the caller."""
    name, price = lane.products[product_id]
    line = order_line_item(
        product_id=product_id,
        quantity=quantity,
        price=price,
        line_item_id=line_item_id,
        fulfilled_quantity=fulfilled_quantity,
    )
    line["productName"] = name
    return line


def smoke_order(
    scout: str,
    suffix: str,
    lines: Sequence[Dict[str, Any]],
    *,
    unit_campaign_id: str,
    customer_name: str,
    order_date: str,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """An individual Order row carrying this lane as its immutable originating scope.

    The id, the campaign and profile ids, and ``fulfillmentVersion: 0`` all come from the
    shared ``sold_order_item`` builder, because §2.4 reads the campaign half of the id out
    of the id itself and an Order spelled any other way exercises only the refusal path.
    ``unitCampaignId`` is the scope captured at sale time (§1.4.3 API-FIX-05): it is what a
    fulfillment's stock and a cleanup sweep are both addressed by, and it never follows the
    Scout Campaign's later link.
    """
    order = sold_order_item(
        scout,
        suffix=suffix,
        unit_id=lane.pack,
        unit_campaign_id=unit_campaign_id,
        lines=list(lines),
    )
    order["customerName"] = customer_name
    order["orderDate"] = order_date
    return order


def arrange_custody_sale(
    orders_table: Any,
    inventory_table: Any,
    fulfillments_table: Any,
    *,
    scout: str,
    unit_campaign_id: str,
    suffix: str,
    product_id: str,
    quantity: int,
    line_item_id: str,
    occurred_at: str,
    idempotency_key: str,
    customer_name: str = "Taylor Door",
    actor: str = RECORDER,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """The row-level effect of a ``CONSUME_SCOUT_CUSTODY`` sale (SS-SM-04 steps 2 and 3).

    The sale consumes ``min(orderedQty, availableWithScoutQty)`` and **never** touches
    Kernel physical: those Kernels left the unassigned balance when the Unit issued them,
    and taking them from the balance again is how one Kernel turns into two sales. A line
    that finds no custody writes no fulfillment, no movement and no custody update at all,
    and the remainder stays as unfulfilled Council demand — which is why SS-SM-04 step 3
    ends with With Scout at zero, Kernel physical untouched, and one unit still owed.

    Every row comes from the production builders this pipeline calls, so an arranged sale
    cannot drift from a real one without the builder changing first. The Order row is built
    from the caller's own lane, and that matters: ``unitId`` and every id come from the lane,
    and the fulfillment history copies the Order's ``unitId``, so a lane left behind here
    attributes one attempt's sale to another attempt's Unit.
    What the arrangement
    leaves out is the campaign's ``totalOrders`` counter: it is the sale's own bookkeeping
    rather than a stock quantity, and it is tested through the pipeline in
    ``create_order_fn.test.js``. The replay marker is arranged, because leaving it out is how a
    cleanup sweep comes to report a lane it did not actually finish.
    """
    taken = _consume_custody(inventory_table, unit_campaign_id, scout, product_id, quantity, occurred_at)
    order = smoke_order(
        scout,
        suffix,
        [smoke_line(product_id, quantity, line_item_id, fulfilled_quantity=taken, lane=lane)],
        unit_campaign_id=unit_campaign_id,
        customer_name=f"{customer_name} {lane.data_id}",
        order_date=occurred_at,
        lane=lane,
    )
    _write_sale_history(
        inventory_table, fulfillments_table, order, line_item_id, product_id, taken, occurred_at, actor, idempotency_key
    )
    orders_table.put_item(Item=order)
    marker = _write_sale_marker(fulfillments_table, order, actor, idempotency_key)
    return {"order": order, "consumedQty": taken, "unfulfilledQty": quantity - taken, "marker": marker}


#: The operation segment of a custody sale's marker, spelled as the pipeline spells it.
CREATE_ORDER_OPERATION = "createOrder"


def _write_sale_marker(fulfillments_table: Any, order: Mapping[str, Any], actor: str, idempotency_key: str) -> MarkerKeys:
    """The ``createOrder`` replay marker at the address the pipeline would have written it.

    The key is actor + operation + Scout Campaign (``lib/custody_sale.js:markerKeysFor``), and
    an Order id appears nowhere in that key — only in the ``resultId`` attribute. So the marker
    of a custody sale survives any sweep that searches for Order ids, replays the caller's key
    for the next attempt that reuses it, and outlives a lane cleanup that does not name it.
    Arranging it here is what lets cleanup prove it removed one.
    """
    keys = marker_keys(
        table_key="order_fulfillments",
        table_name=tables.order_fulfillments.table_name,
        actor_id=account_id(actor),
        operation=CREATE_ORDER_OPERATION,
        scope=str(order["campaignId"]),
        idempotency_key=idempotency_key,
    )
    body = json.dumps({key: str(order[key]) for key in ("orderId", "campaignId", "totalAmount") if key in order})
    fulfillments_table.put_item(
        Item={
            "pk": keys.pk,
            "sk": keys.sk,
            "fingerprint": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "status": "COMPLETED",
            "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86_400,
            "resultId": str(order["orderId"]),
            "resultPayload": body,
        }
    )
    return keys


def _consume_custody(
    inventory_table: Any,
    unit_campaign_id: str,
    scout: str,
    product_id: str,
    quantity: int,
    occurred_at: str,
) -> int:
    """Decrement the custody row the way the sale does, and report how much it took."""
    key = inv.custody_key(unit_campaign_id, product_id, str(PROFILES[scout]["profileId"]))
    row = inventory_table.get_item(Key=key).get("Item")
    taken = min(quantity, _qty(row, inv.WITH_SCOUT_QTY))
    if row is None or taken == 0:
        return 0
    # The version pin and the non-negative floor are one condition here too, exactly as the
    # pipeline states them: "she holds three" is a statement about the row this read saw, and
    # With Scout never goes negative (CUST-04). A row that moved underneath this read fails
    # the condition and the arrangement stops loudly rather than writing a negative balance.
    inventory_table.update_item(
        Key={"pk": row["pk"], "sk": row["sk"]},
        UpdateExpression="SET #held = #held - :take, #version = #version + :one, #updatedAt = :updatedAt",
        ExpressionAttributeNames={
            "#held": inv.WITH_SCOUT_QTY,
            "#version": inv.VERSION_ATTRIBUTE,
            "#updatedAt": inv.UPDATED_AT_ATTRIBUTE,
        },
        ExpressionAttributeValues={
            ":take": taken,
            ":one": 1,
            ":version": _qty(row, inv.VERSION_ATTRIBUTE),
            ":updatedAt": occurred_at,
        },
        ConditionExpression="#version = :version AND #held >= :take",
    )
    return taken


def _write_sale_history(
    inventory_table: Any,
    fulfillments_table: Any,
    order: Mapping[str, Any],
    line_item_id: str,
    product_id: str,
    consumed: int,
    occurred_at: str,
    actor: str,
    idempotency_key: str,
) -> None:
    """Append the sale's fulfillment and its ``INDIVIDUAL_FULFILL`` movement, if it took any."""
    if consumed == 0:
        return
    movement_id = str(inv.new_inventory_movement_id())
    fulfillment_id = ful.new_fulfillment_id()
    fulfillments_table.put_item(
        Item=ful.build_fulfillment_item(
            fulfillment_id=fulfillment_id,
            order_id=str(order["orderId"]),
            campaign_id=str(order["campaignId"]),
            profile_id=str(order["profileId"]),
            unit_id=str(order["unitId"]),
            unit_campaign_id=str(order["unitCampaignId"]),
            line_item_id=line_item_id,
            product_id=product_id,
            record_type=ful.RECORD_TYPE_FULFILL,
            quantity=consumed,
            source=ful.SOURCE_SCOUT_CUSTODY,
            actor_account_id=account_id(actor),
            created_at=occurred_at,
            inventory_movement_id=movement_id,
        )
    )
    # A Kernel delta of zero is written rather than omitted: every movement carries the same
    # five delta columns, a reader reconciles the trail by summing a column, and a missing
    # cell is not the same statement as a zero. ``inventoryVersion`` stays absent because
    # the row that moved was the custody row, not an aggregate balance.
    inventory_table.put_item(
        Item=inv.build_inventory_movement_item(
            movement_id=movement_id,
            unit_campaign_id=str(order["unitCampaignId"]),
            product_id=product_id,
            movement_type=inv.INDIVIDUAL_FULFILL,
            actor_account_id=account_id(actor),
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            kernel_physical_delta=0,
            sold_possession_delta=0,
            with_scout_delta=-consumed,
            assigned_delta=0,
            council_on_order_delta=0,
            profile_id=str(order["profileId"]),
            order_id=str(order["orderId"]),
            fulfillment_id=fulfillment_id,
        )
    )


def arrange_event_assignment(
    inventory_table: Any,
    *,
    campaign: str,
    product_id: str,
    quantity: int,
    start_at: str,
    end_at: str,
    show_and_sell_id: Optional[str] = None,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """Put stock under a future Show & Sell (SS-SM-10 step 2's assignment of four Butter).

    Arranged because §3.2 owns the ``EVENT_ASSIGN`` write and has not landed. The row comes
    from production's own allocation builder, which derives ``remainingQty`` from the three
    authoritative counts, so the ``assignedOpenQty``/``unassignedKernelQty`` the scenario
    asserts come from the same code the resolvers use. No movement row is written for it,
    and :func:`movement_trail_violations` therefore leaves the assigned column alone.
    """
    item = inv.build_event_inventory_allocation_item(
        unit_campaign_id=campaign,
        show_and_sell_id=show_and_sell_id or lane.council_booth,
        product_id=product_id,
        start_at=start_at,
        end_at=end_at,
        allocated_qty=quantity,
        now_iso=start_at,
    )
    inventory_table.put_item(Item=item)
    return item


# ---------------------------------------------------------------------------
# The three scenarios' setups, in the smoke plan's own numbers.
# ---------------------------------------------------------------------------


def setup_ss_sm_03(inventory_table: Any, *, lane: SmokeLane = DEFAULT_LANE) -> List[Dict[str, Any]]:
    """``Stock Admin``: receipt 2, ``+2`` trade, ``-1`` gift, then Casey's receipt (steps 4-8).

    The trail is the evidence: each step's resulting position, and the actor and reason
    that step was required to give. The reasons are the plan's own wording, because a
    reason the screen can only reach by shortening it is not the reason the Kernel typed.
    """
    steps = [
        ("receipt", ADMIN, 2, None, "receipt", 1),
        ("adjustment", ADMIN, 2, "Trade with Troop 7150; money settled outside app", "trade", 2),
        ("adjustment", ADMIN, -1, "Gift to outgoing volunteer", "gift", 3),
        ("receipt", SECOND_ADMIN, 1, None, "casey", 4),
    ]
    evidence: List[Dict[str, Any]] = []
    for action, actor, quantity, reason, key, stamp in steps:
        if action == "receipt":
            record_receipt(
                lane.stock_admin,
                lane.butter,
                quantity,
                caller=actor,
                key=lane.key(key),
                occurred_at=lane.moment(stamp),
            )
        else:
            stock_adjust(
                lane.stock_admin,
                lane.butter,
                quantity,
                str(reason),
                caller=actor,
                key=lane.key(key),
                occurred_at=lane.moment(stamp),
            )
        evidence.append(
            {
                "step": stamp,
                "action": action,
                "actor": actor,
                "quantity": quantity,
                "reason": reason,
                "after": stock_picture(inventory_table, lane.stock_admin, lane.butter),
            }
        )
    return evidence


def setup_ss_sm_04(
    inventory_table: Any, orders_table: Any, fulfillments_table: Any, *, lane: SmokeLane = DEFAULT_LANE
) -> List[Dict[str, Any]]:
    """``Door to Door``: 10 received, issue 4, sale 3, sale 2, issue 2, return 1.

    The plan's numbers, step by step, because the whole point of the sequence is that a
    Kernel is decremented **once** per unit that left the Unit: sales consume custody, and a
    sale that also took Kernel physical would report stock the Unit still holds as stock it
    sold. Each step returns the balances and the sale bookkeeping the plan asserts at that
    step, so a scenario reads one table rather than re-deriving the arithmetic.
    """
    steps = [
        ("receipt", BUTTER_START_QTY),
        ("issue", 4),
        ("sale", 3),
        ("sale", 2),
        ("issue", 2),
        ("return", 1),
    ]
    evidence: List[Dict[str, Any]] = []
    for stamp, (action, quantity) in enumerate(steps, start=1):
        _run_ss_sm_04_step(action, quantity, stamp, inventory_table, orders_table, fulfillments_table, lane)
        evidence.append(_ss_sm_04_evidence(stamp, action, quantity, inventory_table, orders_table, lane))
    return evidence


def _run_ss_sm_04_step(
    action: str,
    quantity: int,
    stamp: int,
    inventory_table: Any,
    orders_table: Any,
    fulfillments_table: Any,
    lane: SmokeLane = DEFAULT_LANE,
) -> None:
    """One step of the SS-SM-04 sequence, driven by the operation the plan names.

    Every identity in it — campaign, product, idempotency key, Order suffix, line identity and
    stamp — comes from the lane, which is what lets a second attempt run the same sequence
    beside the first without replaying any of its writes.
    """
    when = lane.moment(stamp)
    if action == "receipt":
        record_receipt(lane.door_to_door, lane.butter, quantity, key=lane.key("receipt"), occurred_at=when)
    elif action == "issue":
        issue_to_scout(lane.door_to_door, ADMIN, lane.butter, quantity, key=lane.key(f"issue-{stamp}"), occurred_at=when)
    elif action == "sale":
        arrange_custody_sale(
            orders_table,
            inventory_table,
            fulfillments_table,
            scout=ADMIN,
            unit_campaign_id=lane.door_to_door,
            suffix=lane.order_suffix(f"door-{stamp}"),
            product_id=lane.butter,
            quantity=quantity,
            line_item_id=lane.line_id(f"door-{stamp}"),
            occurred_at=when,
            idempotency_key=lane.key(f"sale-{stamp}"),
            lane=lane,
        )
    else:
        return_from_scout(lane.door_to_door, ADMIN, [(lane.butter, quantity)], key=lane.key("return"), occurred_at=when)


def _ss_sm_04_evidence(
    stamp: int,
    action: str,
    quantity: int,
    inventory_table: Any,
    orders_table: Any,
    lane: SmokeLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """A step's balances next to the sale bookkeeping the plan asserts at the same step.

    The demand and sales are read through this campaign's originating scope, not through the
    Scout's Campaign: the Scout Campaign is shared with every other lane and with the canary
    campaign this lane seeds to prove cleanup is lane-scoped, and the plan's numbers are this
    campaign's alone.
    """
    return {
        "step": stamp,
        "action": action,
        "quantity": quantity,
        "after": stock_picture(inventory_table, lane.door_to_door, lane.butter),
        "demand": demand_counts(orders_table, [lane.door_to_door], lane.butter),
        "sales": sale_totals(orders_table, [lane.door_to_door]),
    }


def setup_ss_sm_10(inventory_table: Any, orders_table: Any, *, lane: SmokeLane = DEFAULT_LANE) -> Dict[str, Any]:
    """``Council Planning``'s starting state: demand 10, receipt 8, issue 2, assign 4, on order 3.

    Returns the Order and line the scenario then fulfills from each source, so a test can
    walk steps 5 and 6 and read the needs between them. The Order is written first: demand
    exists before the stock that answers it, and the plan's starting balances are stated
    against a demand that is already on the books.
    """
    order = _council_demand_order(orders_table, lane)
    record_receipt(lane.council_planning, lane.butter, 8, key=lane.key("receipt"), occurred_at=lane.moment(10))
    issue_to_scout(lane.council_planning, ADMIN, lane.butter, 2, key=lane.key("issue"), occurred_at=lane.moment(11))
    arrange_event_assignment(
        inventory_table,
        campaign=lane.council_planning,
        product_id=lane.butter,
        quantity=4,
        start_at=lane.moment(12),
        end_at=lane.moment(240),
        lane=lane,
    )
    council_on_order(
        lane.council_planning,
        lane.butter,
        3,
        "Council promised a case",
        key=lane.key("council"),
        occurred_at=lane.moment(13),
    )
    return {"orderId": str(order["orderId"]), "lineItemId": lane.council_line_id, "order": order}


def _council_demand_order(orders_table: Any, lane: SmokeLane = DEFAULT_LANE) -> Dict[str, Any]:
    """Council Customer's ten-unit Order, entirely unfulfilled (SS-SM-10's fixture state)."""
    order = smoke_order(
        SECOND_ADMIN,
        lane.order_suffix("council-10"),
        [smoke_line(lane.butter, 10, lane.council_line_id, lane=lane)],
        unit_campaign_id=lane.council_planning,
        customer_name=f"Council Customer {lane.data_id}",
        order_date=lane.moment(9),
        lane=lane,
    )
    orders_table.put_item(Item=order)
    return order


# ---------------------------------------------------------------------------
# Last-unit races: two plans built from one read.
# ---------------------------------------------------------------------------


def _custody_for(rows: Sequence[Mapping[str, Any]], profile_id: str) -> Optional[Dict[str, Any]]:
    """The one custody row of this product that belongs to one Scout."""
    for row in rows:
        if str(row.get(inv.PROFILE_ID_ATTRIBUTE)) == profile_id:
            return dict(row)
    return None


def _issue_plan(
    unit_campaign_id: str,
    product_id: str,
    scout: str,
    quantity: int,
    snapshot: Mapping[str, List[Dict[str, Any]]],
    occurred_at: str,
    key: str,
) -> WritePlan:
    """One issue's storage plan, staged from a snapshot the caller already holds.

    The caller, not the plan, does the reading: production re-reads before it stages, so a
    race can only be reproduced by handing both plans the same read and letting DynamoDB
    decide between them. The idempotency marker is left out on purpose — a marker answers a
    *replayed* key, and a race is two different keys against one row.
    """
    plan = WritePlan()
    balance = snapshot["balance"][0] if snapshot["balance"] else None
    if balance is None:
        raise AssertionError("a race for the last Kernel needs a balance to run out of")
    custody = _custody_for(snapshot["custody"], str(PROFILES[scout]["profileId"]))
    version = _qty(balance, inv.VERSION_ATTRIBUTE)
    plan.add(
        *inv.inventory_balance_delta_action(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            existing=balance,
            expected_version=version,
            kernel_physical_delta=-quantity,
            now_iso=occurred_at,
        )
    )
    plan.add(*_custody_change(unit_campaign_id, product_id, scout, custody, quantity, occurred_at))
    plan.add(*_custody_movement(unit_campaign_id, product_id, scout, -quantity, quantity, version + 1, occurred_at, key))
    return plan


def _custody_change(
    unit_campaign_id: str,
    product_id: str,
    scout: str,
    custody: Optional[Mapping[str, Any]],
    quantity: int,
    occurred_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """The custody half of a race plan: the same two shapes production uses."""
    profile_id = str(PROFILES[scout]["profileId"])
    if custody is None:
        return inv.put_scout_custody_action(
            inv.build_scout_custody_balance_item(
                unit_campaign_id=unit_campaign_id,
                product_id=product_id,
                profile_id=profile_id,
                campaign_id=str(PROFILES[scout]["campaignId"]),
                with_scout_qty=quantity,
                now_iso=occurred_at,
            )
        )
    return inv.scout_custody_delta_action(
        unit_campaign_id=unit_campaign_id,
        product_id=product_id,
        profile_id=profile_id,
        existing=custody,
        expected_version=_qty(custody, inv.VERSION_ATTRIBUTE),
        with_scout_delta=quantity,
        now_iso=occurred_at,
    )


def _custody_movement(
    unit_campaign_id: str,
    product_id: str,
    scout: str,
    kernel_delta: int,
    scout_delta: int,
    inventory_version: int,
    occurred_at: str,
    key: str,
    movement_type: str = inv.SCOUT_ISSUE,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row a custody write owes, so a lost race can be seen to have left none."""
    return inv.put_inventory_movement_action(
        inv.build_inventory_movement_item(
            movement_id=str(inv.new_inventory_movement_id()),
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            movement_type=movement_type,
            actor_account_id=account_id(ADMIN),
            occurred_at=occurred_at,
            idempotency_key=key,
            kernel_physical_delta=kernel_delta,
            with_scout_delta=scout_delta,
            profile_id=str(PROFILES[scout]["profileId"]),
            inventory_version=inventory_version,
        )
    )


def _return_plan(
    unit_campaign_id: str,
    product_id: str,
    scout: str,
    quantity: int,
    snapshot: Mapping[str, List[Dict[str, Any]]],
    occurred_at: str,
    key: str,
) -> WritePlan:
    """One return's storage plan, staged from a shared snapshot."""
    plan = WritePlan()
    balance = snapshot["balance"][0] if snapshot["balance"] else None
    custody = _custody_for(snapshot["custody"], str(PROFILES[scout]["profileId"]))
    if custody is None:
        raise AssertionError("a race for the last custody unit needs custody to be there")
    version = _qty(balance, inv.VERSION_ATTRIBUTE)
    plan.add(
        *inv.inventory_balance_delta_action(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            existing=balance,
            expected_version=version,
            kernel_physical_delta=quantity,
            now_iso=occurred_at,
        )
    )
    plan.add(
        *inv.scout_custody_delta_action(
            unit_campaign_id=unit_campaign_id,
            product_id=product_id,
            profile_id=str(PROFILES[scout]["profileId"]),
            existing=custody,
            expected_version=_qty(custody, inv.VERSION_ATTRIBUTE),
            with_scout_delta=-quantity,
            now_iso=occurred_at,
        )
    )
    plan.add(
        *_custody_movement(
            unit_campaign_id,
            product_id,
            scout,
            quantity,
            -quantity,
            version + 1,
            occurred_at,
            key,
            movement_type=inv.SCOUT_RETURN,
        )
    )
    return plan


def race_two_plans(plans: Sequence[WritePlan]) -> Dict[str, Any]:
    """Commit each plan and report which ones DynamoDB cancelled, without interpreting them.

    The order is the point: the first plan commits and the second's condition is written
    against a row it never read. A deployment interleaves them instead, and the outcome is
    the same, because the version pin makes the second plan's condition false rather than
    merely unlucky.
    """
    client = get_dynamodb_client()
    verdicts: List[Dict[str, Any]] = []
    for attempt, plan in enumerate(plans):
        try:
            client.transact_write_items(TransactItems=plan.transact_items())
            verdicts.append({"attempt": attempt, "committed": True, "code": None, "reasons": None})
        except ClientError as exc:
            verdicts.append(
                {
                    "attempt": attempt,
                    "committed": False,
                    "code": exc.response.get("Error", {}).get("Code"),
                    "reasons": exc.response.get("CancellationReasons"),
                }
            )
    return {"verdicts": verdicts, "committed": sum(1 for verdict in verdicts if verdict["committed"])}


def race_issue_last_kernel(
    inventory_table: Any,
    *,
    lane: SmokeLane = DEFAULT_LANE,
    campaign: Optional[str] = None,
    product_id: Optional[str] = None,
    scout: str = ADMIN,
    quantity: int = 1,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Two issues of the same last Kernels, both planned from one read (INV-M-04's race).

    ``inventory_table`` is there so the caller reads the aftermath from the same handle the
    race wrote through: the verdict to assert is not only that one transaction cancelled,
    but that the Kernels moved once, the custody moved once, and exactly one movement row
    exists.
    """
    campaign, product_id, when = _race_arguments(lane, campaign, product_id, occurred_at, 40)
    snapshot = inv.inventory_position_rows(campaign, product_id)
    plans = [
        _issue_plan(campaign, product_id, scout, quantity, snapshot, when, lane.key(f"race-issue-{attempt}"))
        for attempt in range(2)
    ]
    return race_two_plans(plans)


def _race_arguments(
    lane: SmokeLane, campaign: Optional[str], product_id: Optional[str], occurred_at: Optional[str], step: int
) -> Tuple[str, str, str]:
    """One race's campaign, product and stamp, defaulting to this lane's Door to Door Butter."""
    return campaign or lane.door_to_door, product_id or lane.butter, occurred_at or lane.moment(step)


def race_return_last_kernel(
    inventory_table: Any,
    *,
    lane: SmokeLane = DEFAULT_LANE,
    campaign: Optional[str] = None,
    product_id: Optional[str] = None,
    scout: str = ADMIN,
    quantity: int = 1,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Two returns of the same last custody unit, both planned from one read (CUST-04's race).

    The other side of the same question: With Scout can never go negative, and a Unit cannot
    be handed the same returned Kernel twice.
    """
    campaign, product_id, when = _race_arguments(lane, campaign, product_id, occurred_at, 41)
    snapshot = inv.inventory_position_rows(campaign, product_id)
    plans = [
        _return_plan(campaign, product_id, scout, quantity, snapshot, when, lane.key(f"race-return-{attempt}"))
        for attempt in range(2)
    ]
    return race_two_plans(plans)


# ---------------------------------------------------------------------------
# Lane cleanup (leaf 2.8.7).
# ---------------------------------------------------------------------------


def _marker_needle(order_id: str) -> str:
    """The form of an Order id inside an idempotency marker's partition key.

    ``src/utils/mutations.py`` escapes a ``#`` as ``%23`` inside a key segment, and this
    application's Order ids are full of ``#``, so searching for the raw id finds nothing
    while the marker sits right there.
    """
    return order_id.replace("#", "%23")


def _delete_markers(table: Any, needle: str) -> int:
    """Delete every idempotency marker whose partition key names this lane's scope.

    This finds the markers a Unit-tenant mutation wrote with the lane's own Unit Campaign as
    its resource scope, and the §2.4 fulfillment markers scoped to one Order. It cannot find a
    marker scoped by something else — which is why :func:`clean_stage2_lane` also deletes the
    custody-sale markers this lane recorded, by their exact address.
    """
    items = _paged(
        table,
        FilterExpression="begins_with(pk, :prefix) AND contains(pk, :needle)",
        ExpressionAttributeValues={":prefix": "IDEM#", ":needle": needle},
    )
    for item in items:
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return len(items)


RESULT_ID_ATTRIBUTE = "resultId"


def _delete_order_markers(fulfillments_table: Any, order_id: str) -> int:
    """Delete every replay marker that belongs to one Order, whichever key shape it uses.

    Two shapes reach this table. A §2.4 fulfillment marker carries the Order id in its own
    partition key, escaped, because the Order is the resource the mutation addresses. A custody
    sale's ``createOrder`` marker does not: its key is actor + operation + Scout Campaign, and
    the Order appears only in its ``resultId`` attribute (``lib/custody_sale.js:markerKeysFor``
    and ``saleMarkerAction``). Searching for the Order id alone therefore leaves a sale's marker
    behind, where it replays the next attempt's key, and a lane's Scout Campaign is shared with
    every other lane's sales, so a prefix sweep cannot be the answer either. The one fact both
    shapes agree on is which Order the marker answers, so the sweep asks that.
    """
    items = _paged(
        fulfillments_table,
        FilterExpression="contains(pk, :needle) OR #resultId = :order",
        ExpressionAttributeNames={"#resultId": RESULT_ID_ATTRIBUTE},
        ExpressionAttributeValues={":needle": _marker_needle(order_id), ":order": order_id},
    )
    for item in items:
        fulfillments_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return len(items)


def clean_stage2_lane(
    inventory_table: Any, orders_table: Any, fulfillments_table: Any, lane: SmokeLane
) -> Dict[str, int]:
    """Remove one lane's Stage 2 records and nothing else; report what was removed.

    Four sweeps, each keyed on the lane itself: the inventory partitions of its Unit Campaigns
    (balance, custody rows, allocations, and the whole movement trail), the fulfillment
    partitions of the Orders this lane sold, those Orders, and the idempotency markers on both
    tables. Markers live under their own ``IDEM#`` partition, so they survive every partition
    sweep that does not name them, and a custody sale's marker is keyed on actor, operation and
    Scout Campaign rather than on anything lane-scoped — hence the recorded addresses. Every
    read here pages to the end: DynamoDB answers at most 1 MB per call, and a sweep that stops
    at the first page reports a lane it left half behind.

    It deletes rows rather than undoing them: a Stage 2 history row is append-only by
    design, so a lane that wanted its audit trail gone through the product's own path would
    have to reverse every movement, and that is a correction, not cleanup.
    """
    removed = {"inventory": 0, "markers": 0, "orders": 0, "fulfillments": 0}
    campaign_ids = lane.stock_campaign_ids
    for campaign_id in campaign_ids:
        for row in lane_inventory_rows(inventory_table, campaign_id):
            inventory_table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
            removed["inventory"] += 1
        removed["markers"] += _delete_markers(inventory_table, campaign_id)

    for order in lane_orders(orders_table, campaign_ids):
        order_id = str(order["orderId"])
        for row in ful.fulfillment_rows(order_id):
            fulfillments_table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
            removed["fulfillments"] += 1
        removed["markers"] += _delete_order_markers(fulfillments_table, order_id)
        orders_table.delete_item(Key={"campaignId": order["campaignId"], "orderId": order["orderId"]})
        removed["orders"] += 1
    return removed
