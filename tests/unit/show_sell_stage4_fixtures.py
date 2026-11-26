"""Stage 4 sales fixtures: one deterministic lane for ``SS-SM-07``.

Checklist leaf 4.5.3. The smoke plan (``SHOW_AND_SELL_SMOKE_TEST_PLAN.md`` §5, scenario
``SS-SM-07``) is the source of every name, price, quantity, payment note and cash figure
here: ``Venmo <DATA_ID>`` with a PNG QR, a past ``Church on Elm <DATA_ID>`` in
``Sales Desk <DATA_ID>``, 3 Chocolate and 1 Butter received with 2 Chocolate and 1 Butter
assigned, three sales totalling ``$120``, a reservation, a two-source fulfillment, and the
``$25`` / ``+$10`` / ``$34`` / ``-$1`` cash trail. Those numbers are stated once, in this
module, so a scenario that disagrees with the plan disagrees with the fixture and the
mismatch is visible rather than argued about later.

**What goes through the product and what is arranged (FIX-AC-04).** Every event, stock,
assignment, work confirmation, sale, reservation and fulfillment below is driven through
``handle_unit_operation`` — the deployed resolver is the thing being evidenced. Two rows
are arranged from production builders because the state window excludes the normal path:
the past event's slots and signups (``require_slots_writable`` and
``require_signup_window`` accept ``SCHEDULED`` only, so a past event cannot use those
mutations), and the Unit's own metadata, campaigns and catalog (Stage 1 seed material).
No allocation, obligation, sale, movement or marker row is hand-built.

**Lane cleanup.** :func:`clean_sales_lane` deletes this lane's event partitions, idempotency
markers, Unit payment rows, QR objects and inventory rows in dependency order. Its canary
is a second Unit Campaign on the same Unit with its own marker: the sweep addresses only
the sales campaign and the event ids discovered from it, so the canary is proof that the
delete was scoped rather than account-wide.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.handlers.unit_operations import (
    ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
    CONFIRM_PAYMENT_QR_FIELD,
    CONFIRM_WORK_FIELD,
    CREATE_PAYMENT_METHOD_FIELD,
    CREATE_SALE_FIELD,
    CREATE_SHOW_AND_SELL_FIELD,
    FULFILL_WE_OWE_FIELD,
    RECORD_RECEIPT_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
    UPDATE_SHOW_AND_SELL_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from src.utils.boto import get_s3_client
from src.utils.dynamodb import tables
from tests.unit.show_sell_fixtures import (
    PROFILES,
    account_id,
    assert_is_error,
    catalog_item,
    grant_item,
    join_code_pointer_item,
    unit_campaign_item,
    unit_campaign_membership_item,
    unit_item,
    unit_operation_event,
)

_IDEMPOTENCY_KEY_LIMIT = 128

#: The bytes the browser says it uploaded, and the digest its upload key declares.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

#: The smoke plan's actors mapped onto the personas this repository already seeds.
ADMIN = "Avery"
SECOND_ADMIN = "Devon"
RECORDER = "Taylor"

#: The line input the browser presents for We Owe on the first sale line (§4.5.2).
SALE_LINE_WE_OWE_TEST_ID = "sale-line-weowe-0"

#: The cash reconciliation evidence the plan fixes, in exact integer cents.
CASH_ADJUSTMENT_REASON = "Cash portion of Sam Split Other payment"
CASH_ADJUSTMENT_CENTS = 1_000
ACTUAL_CASH_CENTS = 3_400
CASH_EXPLANATION = "$1 short at closeout"


def _new_run_id() -> str:
    """``RUN_ID`` as the plan spells it: UTC epoch seconds plus a short uuid4 tail."""
    return f"{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:6]}"


def _new_attempt_id() -> str:
    """``ATTEMPT_ID``: fresh for every attempt, including every retry of a failed one."""
    return uuid.uuid4().hex[:6]


@dataclass(frozen=True)
class SalesLane:
    """One SS-SM-07 attempt's identity, and everything derived from it.

    The Unit, campaigns, catalog, products, event, slots, payment method and every
    idempotency key carry ``data_id``. Two attempts therefore cannot replay each other's
    mutations or delete each other's rows; :data:`DEFAULT_LANE` keeps the plan's numbers
    reproducible for the fidelity tests.
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
        scenario_id: str = "SS-SM-07",
        *,
        run_id: Optional[str] = None,
        lane_id: str = "L01",
        attempt_id: Optional[str] = None,
        t0: Optional[datetime] = None,
    ) -> "SalesLane":
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
        """This lane's own Pack 3149 (never the shared Stage 1 Unit)."""
        return f"unit-{self.data_id}-pack-3149"

    @property
    def catalog_id(self) -> str:
        return f"CATALOG#sales-popcorn-{self.data_id}"

    @property
    def chocolate(self) -> str:
        return f"{self.catalog_id}#chocolate-popcorn"

    @property
    def butter(self) -> str:
        return f"{self.catalog_id}#butter-popcorn"

    @property
    def products(self) -> Dict[str, Tuple[str, Decimal]]:
        """``productId -> (productName, price)`` — the smoke plan's two products."""
        return {
            self.chocolate: (f"Chocolate Popcorn {self.data_id}", Decimal("25.00")),
            self.butter: (f"Butter Popcorn {self.data_id}", Decimal("20.00")),
        }

    @property
    def sales_campaign(self) -> str:
        """``Sales Desk <DATA_ID>``, the lane's written-to Unit Campaign."""
        return f"uc-{self.data_id}-sales-desk"

    @property
    def canary_campaign(self) -> str:
        """``Split Math <DATA_ID>``: same Unit, never written to; the cleanup survivor."""
        return f"uc-{self.data_id}-split-math"

    @property
    def unit_campaigns(self) -> Dict[str, str]:
        return {
            self.sales_campaign: f"Sales Desk {self.data_id}",
            self.canary_campaign: f"Split Math {self.data_id}",
        }

    @property
    def location_name(self) -> str:
        return f"Church on Elm {self.data_id}"

    @property
    def payment_method_name(self) -> str:
        return f"Venmo {self.data_id}"

    @property
    def slot_id(self) -> str:
        """The one past slot whose confirmed work feeds the EQUAL pool."""
        return f"slot-{self.data_id}-church-1"

    @property
    def attempt_key(self) -> str:
        """The short tail every id inside a shared partition carries."""
        return self.attempt_id or self.data_id

    # --- time and keys --------------------------------------------------------

    def moment(self, step: int) -> str:
        """``t0`` plus ``step`` minutes, in the ``+00:00`` spelling DynamoDB sorts."""
        return (self.t0 + timedelta(minutes=step)).isoformat()

    def key(self, label: str) -> str:
        """An idempotency key belonging to this attempt and to this one write."""
        return f"{self.data_id}-{label}"[:_IDEMPOTENCY_KEY_LIMIT]


#: The reproducible lane the plan-fidelity tests assert against.
DEFAULT_LANE = SalesLane(data_id="sales3149", t0=datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc))
DATA_ID = DEFAULT_LANE.data_id
SALES_PACK = DEFAULT_LANE.pack
SALES_CAMPAIGN = DEFAULT_LANE.sales_campaign
CANARY_CAMPAIGN = DEFAULT_LANE.canary_campaign
CHOCOLATE = DEFAULT_LANE.chocolate
BUTTER = DEFAULT_LANE.butter
SALES_PRODUCTS: Dict[str, Tuple[str, Decimal]] = DEFAULT_LANE.products
CHURCH_ON_ELM = DEFAULT_LANE.location_name
VENMO = DEFAULT_LANE.payment_method_name

#: The zero-based sale-line input the browser exposes for a We Owe quantity.
WE_OWE_LINE_TEST_ID = SALE_LINE_WE_OWE_TEST_ID


# --- Seed material --------------------------------------------------------------


def sales_unit_metadata_item(lane: SalesLane = DEFAULT_LANE) -> Dict[str, Any]:
    """The lane's Unit row: EQUAL split, two Unit Admins, no other tenant's data."""
    return unit_item(
        lane.pack,
        "Pack",
        3149,
        "Aurora",
        "CO",
        split_default=ssm.SPLIT_METHOD_EQUAL,
        display_name=f"Pack 3149 {lane.data_id}",
        created_by=account_id(ADMIN),
        admin_count=2,
    )


def sales_catalog_item(lane: SalesLane = DEFAULT_LANE) -> Dict[str, Any]:
    """The two-product catalog, with the plan's prices stated once."""
    products = [
        {
            "productId": product_id,
            "productName": name,
            "description": f"Sales catalog product {index} (one unit is one sale unit)",
            "price": price,
            "sortOrder": index,
        }
        for index, (product_id, (name, price)) in enumerate(lane.products.items(), start=1)
    ]
    return catalog_item(lane.catalog_id, f"Sales Catalog {lane.data_id}", owner=ADMIN, products=products)


def _join_code(campaign_id: str, lane: SalesLane) -> str:
    """The exactly-16-character code each campaign carries (§6.6)."""
    return f"{campaign_id[-8:]}{lane.data_id[-8:]}"


def seed_sales_lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    *,
    lane: SalesLane = DEFAULT_LANE,
) -> Dict[str, List[Dict[str, Any]]]:
    """Write this lane's Unit, two Unit Campaigns, rosters and catalog."""
    written: Dict[str, List[Dict[str, Any]]] = {"units": [], "unit_campaigns": [], "catalogs": []}
    metadata = sales_unit_metadata_item(lane)
    units_table.put_item(Item=metadata)
    written["units"].append(metadata)
    for admin in (ADMIN, SECOND_ADMIN):
        grant = grant_item(lane.pack, admin, created_by=ADMIN)
        units_table.put_item(Item=grant)
        written["units"].append(grant)

    for campaign_id, campaign_name in lane.unit_campaigns.items():
        code = _join_code(campaign_id, lane)
        item = unit_campaign_item(
            campaign_id,
            unit_id=lane.pack,
            campaign_name=campaign_name,
            campaign_year=2026,
            catalog_id=lane.catalog_id,
            join_code=code,
            created_by=ADMIN,
        )
        unit_campaigns_table.put_item(Item=item)
        written["unit_campaigns"].append(item)
        pointer = join_code_pointer_item(code, campaign_id)
        unit_campaigns_table.put_item(Item=pointer)
        written["unit_campaigns"].append(pointer)
        for scout in (ADMIN, "Blake"):
            membership = unit_campaign_membership_item(
                campaign_id,
                lane.pack,
                str(PROFILES[scout]["campaignId"]),
                str(PROFILES[scout]["profileId"]),
                joined_by=scout,
            )
            unit_campaigns_table.put_item(Item=membership)
            written["unit_campaigns"].append(membership)

    catalog = sales_catalog_item(lane)
    catalogs_table.put_item(Item=catalog)
    written["catalogs"].append(catalog)
    return written


# --- Resolver turns -------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """One resolver turn through the deployed entry point."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _idem(lane: SalesLane, label: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": lane.key(label)}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def event_version(event_id: str) -> int:
    """The event's current version, as a screen that just opened it would hold it."""
    row = ssm.load_show_and_sell_or_not_found(event_id)
    return int(row[ssm.VERSION_ATTRIBUTE])


def create_church_on_elm(lane: SalesLane = DEFAULT_LANE, *, caller: str = ADMIN) -> str:
    """``createShowAndSell`` for the lane's past event; returns its generated id."""
    mutation: Dict[str, Any] = {
        "unitCampaignId": lane.sales_campaign,
        "locationName": lane.location_name,
        "startAt": lane.moment(-120),
        "endAt": lane.moment(120),
        **_idem(lane, "event-create"),
    }
    answer = _ok(_call(CREATE_SHOW_AND_SELL_FIELD, caller, mutation=mutation))
    return str(answer["showAndSellId"])


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload


def enable_we_owe(event_id: str, lane: SalesLane = DEFAULT_LANE, *, caller: str = ADMIN) -> Dict[str, Any]:
    """``updateShowAndSell`` flipping ``weOweEnabled`` from its disabled start."""
    mutation = {
        "showAndSellId": event_id,
        "weOweEnabled": True,
        **_version(event_version(event_id)),
        **_idem(lane, "event-we-owe-on"),
    }
    return _ok(_call(UPDATE_SHOW_AND_SELL_FIELD, caller, mutation=mutation))


def record_stock(lane: SalesLane = DEFAULT_LANE, *, caller: str = ADMIN) -> Dict[str, str]:
    """3 Chocolate and 1 Butter received into the lane's campaign."""
    ids: Dict[str, str] = {}
    for label, product_id, quantity in (("chocolate", lane.chocolate, 3), ("butter", lane.butter, 1)):
        mutation = {
            "unitCampaignId": lane.sales_campaign,
            "productId": product_id,
            "quantity": quantity,
            **_idem(lane, f"receipt-{label}"),
        }
        _ok(_call(RECORD_RECEIPT_FIELD, caller, mutation=mutation))
        ids[label] = product_id
    return ids


def assign_stock(event_id: str, lane: SalesLane = DEFAULT_LANE, *, caller: str = ADMIN) -> Dict[str, Any]:
    """``assignShowAndSellInventory``: 2 Chocolate and 1 Butter on the ENDED event."""
    mutation = {
        "showAndSellId": event_id,
        "items": [
            {"productId": lane.chocolate, "quantity": 2},
            {"productId": lane.butter, "quantity": 1},
        ],
        **_version(event_version(event_id)),
        **_idem(lane, "event-assign"),
    }
    return _ok(_call(ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD, caller, mutation=mutation))


def attempt_sale(
    event_id: str,
    *,
    lane: SalesLane = DEFAULT_LANE,
    caller: str = ADMIN,
    key: str,
    buyer: Optional[str],
    lines: Sequence[Mapping[str, int]],
    method: str = "CASH",
    other_details: Optional[str] = None,
) -> Any:
    """One ``createShowAndSellSale`` turn, with the caller's event version pinned."""
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "saleAt": lane.moment(30),
        "lineItems": [
            {"productId": str(line["productId"]), "immediateQty": int(line["immediateQty"]), "weOweQty": int(line["weOweQty"])}
            for line in lines
        ],
        "paymentMethodCode": method,
        **_version(event_version(event_id)),
        **_idem(lane, key),
    }
    if buyer is not None:
        payload["buyerName"] = buyer
    if other_details is not None:
        payload["otherDetails"] = other_details
    return _call(CREATE_SALE_FIELD, caller, mutation=payload)


def blocked_sales(event_id: str, lane: SalesLane = DEFAULT_LANE) -> Dict[str, Any]:
    """Step 1's authorization denial and step 2's stock denial, with no partial effects.

    Morgan's attempt uses a sale that would otherwise succeed, so the refusal is about
    the caller and not about the numbers. Alex's attempt asks for 3 immediate Chocolate
    against an allocation of 2 while We Owe is off, so the refusal is about stock.
    """
    three_chocolate = [{"productId": lane.chocolate, "immediateQty": 1, "weOweQty": 0}]
    denied = assert_is_error(
        attempt_sale(
            event_id,
            lane=lane,
            caller=RECORDER,  # Morgan's Stage 2 persona: a signed-in non-admin
            key="sale-morgan-denied",
            buyer=None,
            lines=three_chocolate,
        ),
        # AUTH-U-05: a caller with no Unit grant is answered exactly like a caller
        # who named a Unit that does not exist, so the denial cannot confirm the
        # Unit exists — Morgan's "denied" reads as NOT_FOUND, not FORBIDDEN.
        "NOT_FOUND",
    )
    short = assert_is_error(
        attempt_sale(
            event_id,
            lane=lane,
            caller=ADMIN,
            key="sale-nora-blocked",
            buyer="Nora Cash",
            lines=[{"productId": lane.chocolate, "immediateQty": 3, "weOweQty": 0}],
        ),
        # The stock refusal surfaces as CONFLICT; its message carries the
        # allocation arithmetic ("3 asked for, but this event holds 2 to sell").
        "CONFLICT",
    )
    return {"morganDenied": denied, "stockRefused": short}


def arrange_payment_method(
    *, lane: SalesLane = DEFAULT_LANE, caller: str = ADMIN, s3_client: Any = None
) -> Dict[str, str]:
    """``Venmo <DATA_ID>`` with a real request/POST/confirm QR lifecycle.

    The upload target the resolver mints is written into S3 with the exact bytes whose
    SHA-256 it names, then confirmed; the attachment the row ends up referencing is a
    different key, as §4.1.2 requires.
    """
    created = _ok(
        _call(
            CREATE_PAYMENT_METHOD_FIELD,
            caller,
            mutation={
                "unitId": lane.pack,
                "displayName": lane.payment_method_name,
                **_idem(lane, "payment-method-create"),
            },
        )
    )
    payment_method_id = str(created["paymentMethodId"])
    requested = _ok(
        _call(
            REQUEST_PAYMENT_QR_FIELD,
            caller,
            mutation={
                "unitId": lane.pack,
                "paymentMethodId": payment_method_id,
                "contentType": "image/png",
                "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                **_idem(lane, "payment-qr-request"),
            },
        )
    )
    upload_key = str(requested["s3Key"])
    client = s3_client or get_s3_client()
    client.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=upload_key, Body=PNG_BYTES)
    confirmed = _ok(
        _call(
            CONFIRM_PAYMENT_QR_FIELD,
            caller,
            mutation={
                "unitId": lane.pack,
                "paymentMethodId": payment_method_id,
                "s3Key": upload_key,
                **_version(1),
                **_idem(lane, "payment-qr-confirm"),
            },
        )
    )
    return {
        "paymentMethodId": payment_method_id,
        "uploadKey": upload_key,
        "attachmentKey": str(confirmed["qrCodeS3Key"]),
    }


def arrange_work(
    event_id: str,
    *,
    lane: SalesLane = DEFAULT_LANE,
    show_and_sells_table: Any = None,
    caller: str = ADMIN,
) -> Dict[str, Any]:
    """One past slot and two signups written from production builders, work confirmed.

    The slot and signup mutations are ``SCHEDULED``-only, so a past event cannot reach
    them; the rows are written with the same builders those mutations use, and the
    confirmation — the part this scenario evidences — goes through its resolver.
    """
    table = show_and_sells_table or tables.show_and_sells
    event_row = ssm.load_show_and_sell_or_not_found(event_id)
    slot = ssm.build_show_and_sell_slot_item(
        event=event_row,
        slot_id=lane.slot_id,
        start_at=lane.moment(-60),
        end_at=lane.moment(60),
        capacity=2,
        now_iso=lane.moment(-115),
        label=f"Church on Elm morning {lane.data_id}",
    )
    table.put_item(Item=slot)
    signups: List[Dict[str, Any]] = []
    for scout in (ADMIN, "Blake"):
        row = ssm.build_show_and_sell_signup_item(
            event=event_row,
            slot_id=lane.slot_id,
            profile_id=PROFILES[scout]["profileId"],
            campaign_id=PROFILES[scout]["campaignId"],
            signed_up_by_account_id=account_id(RECORDER),
            now_iso=lane.moment(-110),
        )
        table.put_item(Item=row)
        signups.append(row)
    mutation = {
        "showAndSellId": event_id,
        "work": [
            {
                "slotId": lane.slot_id,
                "profileId": str(PROFILES[scout]["profileId"]),
                "actualMinutes": 60,
            }
            for scout in (ADMIN, "Blake")
        ],
        **_version(event_version(event_id)),
        **_idem(lane, "work-confirm"),
    }
    answer = _ok(_call(CONFIRM_WORK_FIELD, caller, mutation=mutation))
    return {"slot": slot, "signups": signups, "work": answer}


def _quinn_obligation_id(event_id: str, answer: Mapping[str, Any]) -> str:
    obligations = answer.get("obligations") or []
    assert len(obligations) == 1, f"one We Owe line owes one obligation: {answer!r}"
    return str(obligations[0][sm.WE_OWE_ID_ATTRIBUTE])


def reserve_we_owe(
    we_owe_id: str,
    *,
    lane: SalesLane = DEFAULT_LANE,
    caller: str = ADMIN,
    target: int = 1,
) -> Dict[str, Any]:
    """``setWeOweReservation`` with the obligation version read at the screen."""
    mutation = {
        "weOweId": we_owe_id,
        "targetReservedQty": target,
        **_version(int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])),
        **_idem(lane, "we-owe-reserve"),
    }
    return _ok(_call(SET_WE_OWE_RESERVATION_FIELD, caller, mutation=mutation))


def fulfill_we_owe(
    we_owe_id: str,
    source: str,
    *,
    lane: SalesLane = DEFAULT_LANE,
    caller: str = ADMIN,
    key: str,
    quantity: int = 1,
) -> Dict[str, Any]:
    """``fulfillWeOwe`` from one source, pinning the obligation version each time."""
    mutation = {
        "weOweId": we_owe_id,
        "quantity": quantity,
        "source": source,
        **_version(int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])),
        **_idem(lane, key),
    }
    return _ok(_call(FULFILL_WE_OWE_FIELD, caller, mutation=mutation))


def setup_ss_sm_07(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
    *,
    lane: SalesLane = DEFAULT_LANE,
    s3_client: Any = None,
) -> Dict[str, Any]:
    """The whole SS-SM-07 fixture, from seed to closed obligation, without finalizing.

    Every mutation runs in the plan's order: seed, create, receive, assign, attempt the two
    refusals, enable We Owe, enter three sales, attach the QR, confirm work, reserve one
    unassigned Chocolate, then fulfill the obligation from stock and from Council supply.
    """
    seed_sales_lane(units_table, unit_campaigns_table, catalogs_table, lane=lane)
    event_id = create_church_on_elm(lane)
    record_stock(lane)
    assign_stock(event_id, lane)
    blocked = blocked_sales(event_id, lane)
    enable_we_owe(event_id, lane)

    nora = _ok(
        attempt_sale(
            event_id,
            lane=lane,
            key="sale-nora",
            buyer="Nora Cash",
            lines=[{"productId": lane.chocolate, "immediateQty": 1, "weOweQty": 0}],
        )
    )
    quinn = _ok(
        attempt_sale(
            event_id,
            lane=lane,
            key="sale-quinn",
            buyer="Quinn WeOwe",
            lines=[{"productId": lane.chocolate, "immediateQty": 1, "weOweQty": 2}],
            method="OTHER",
            other_details="Apple Pay; Kernel reimbursed unit by Venmo",
        )
    )
    sam = _ok(
        attempt_sale(
            event_id,
            lane=lane,
            key="sale-sam",
            buyer="Sam Split",
            lines=[{"productId": lane.butter, "immediateQty": 1, "weOweQty": 0}],
            method="OTHER",
            other_details="$10 cash + $10 Venmo",
        )
    )
    payment = arrange_payment_method(lane=lane, s3_client=s3_client)
    work = arrange_work(event_id, lane=lane)

    obligation_id = _quinn_obligation_id(event_id, quinn)
    reservation = reserve_we_owe(obligation_id, lane=lane)
    kernel_fulfillment = fulfill_we_owe(
        obligation_id, sm.WE_OWE_SOURCE_KERNEL, lane=lane, key="we-owe-fulfill-kernel"
    )
    council_fulfillment = fulfill_we_owe(
        obligation_id, sm.WE_OWE_SOURCE_EXTERNAL, lane=lane, key="we-owe-fulfill-council"
    )
    return {
        "eventId": event_id,
        "blocked": blocked,
        "sales": {"nora": nora, "quinn": quinn, "sam": sam},
        "payment": payment,
        "work": work,
        "obligationId": obligation_id,
        "reservation": reservation,
        "fulfillments": {"kernel": kernel_fulfillment, "council": council_fulfillment},
    }


# --- Readers and evidence -------------------------------------------------------


def _paged(table: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Every item a Query or Scan answers, following ``LastEvaluatedKey`` to the end."""
    items: List[Dict[str, Any]] = []
    while True:
        page = table.query(**kwargs) if "KeyConditionExpression" in kwargs else table.scan(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if token is None:
            return items
        kwargs["ExclusiveStartKey"] = token


def discover_event_ids(show_and_sells_table: Any, unit_campaign_id: str) -> List[str]:
    """The lane's event ids, discovered from the rows rather than remembered by setup."""
    rows = _paged(
        show_and_sells_table,
        FilterExpression="#campaign = :campaign AND #type = :type",
        ExpressionAttributeNames={"#campaign": "unitCampaignId", "#type": "entityType"},
        ExpressionAttributeValues={":campaign": unit_campaign_id, ":type": ssm.ENTITY_TYPE_EVENT},
    )
    return sorted(str(row[ssm.SHOW_AND_SELL_ID_ATTRIBUTE]) for row in rows)


def _qty(row: Optional[Mapping[str, Any]], name: str) -> int:
    return 0 if row is None else int(row.get(name, 0) or 0)


def _of_type(rows: Iterable[Dict[str, Any]], entity_type: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row.get("entityType") == entity_type]


def product_rows(inventory_table: Any, unit_campaign_id: str, product_id: str) -> List[Dict[str, Any]]:
    """Every inventory row of one product in one Unit Campaign."""
    return _paged(
        inventory_table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": inv.inventory_pk(unit_campaign_id),
            ":prefix": inv.product_scope_prefix(product_id),
        },
    )


def stock_picture(inventory_table: Any, unit_campaign_id: str, product_id: str) -> Dict[str, Any]:
    """One product's stored rows plus every §7 quantity derived by production code."""
    rows = product_rows(inventory_table, unit_campaign_id, product_id)
    balance = next(iter(_of_type(rows, inv.BALANCE_ENTITY_TYPE)), None)
    allocations = _of_type(rows, inv.ALLOCATION_ENTITY_TYPE)
    custody = _of_type(rows, inv.CUSTODY_ENTITY_TYPE)
    picture: Dict[str, Any] = {
        "kernelPhysicalQty": _qty(balance, inv.KERNEL_PHYSICAL_QTY),
        "soldInPossessionQty": _qty(balance, inv.SOLD_IN_POSSESSION_QTY),
        "balanceVersion": _qty(balance, inv.VERSION_ATTRIBUTE),
    }
    picture.update(inv.derived_inventory_quantities(balance, allocations, custody))
    return picture


def movement_trail_violations(inventory_table: Any, unit_campaign_id: str, product_id: str) -> List[str]:
    """Reconcile every movement delta to its balance, including ``assignedDelta``.

    Stage 2 deliberately leaves the assigned column out because its ``EVENT_ASSIGN``
    writer did not exist then. Stage 4's lane is written entirely by production
    mutations, so the column has a history to explain: the sum of ``assignedDelta`` has
    to equal the open allocations' ``remainingQty``, exactly as the physical and custody
    columns do.
    """
    rows = product_rows(inventory_table, unit_campaign_id, product_id)
    movements = _of_type(rows, inv.MOVEMENT_ENTITY_TYPE)
    violations: List[str] = []
    for movement in movements:
        for text in inv.movement_row_violations(movement):
            violations.append(f"movement {movement.get(inv.MOVEMENT_ID_ATTRIBUTE)}: {text}")
    totals = {name: sum(_qty(row, name) for row in movements) for name in inv.MOVEMENT_DELTA_ATTRIBUTES}
    balance = next(iter(_of_type(rows, inv.BALANCE_ENTITY_TYPE)), None)
    allocations = _of_type(rows, inv.ALLOCATION_ENTITY_TYPE)
    custody = _of_type(rows, inv.CUSTODY_ENTITY_TYPE)
    pairs: Sequence[Tuple[str, int]] = (
        (inv.KERNEL_PHYSICAL_DELTA, _qty(balance, inv.KERNEL_PHYSICAL_QTY)),
        (inv.SOLD_POSSESSION_DELTA, _qty(balance, inv.SOLD_IN_POSSESSION_QTY)),
        (inv.COUNCIL_ON_ORDER_DELTA, _qty(balance, inv.COUNCIL_ON_ORDER_QTY)),
        (inv.ASSIGNED_DELTA, inv.assigned_open_qty(allocations)),
        (inv.WITH_SCOUT_DELTA, inv.with_scout_qty(custody)),
    )
    for delta_name, expected in pairs:
        if totals[delta_name] != expected:
            violations.append(f"sum({delta_name}) = {totals[delta_name]} but the derived quantity is {expected}")
    return violations


def sales_evidence(
    inventory_table: Any,
    show_and_sells_table: Any,
    event_id: str,
    *,
    lane: SalesLane = DEFAULT_LANE,
) -> Dict[str, Any]:
    """The plan's numbers, read back from stored rows and derived by production code."""
    event_row = ssm.load_show_and_sell_or_not_found(event_id)
    event = ssm.event_admin_payload(event_row)
    sales = [sm.sale_payload(row) for row in sm.event_sale_rows(event_id)]
    obligations = [sm.we_owe_payload(row) for row in ssm.event_we_owe_rows(event_id)]
    assert obligations, "the sales owe something"
    fulfillments = [
        sm.we_owe_fulfillment_payload(row)
        for obligation in ssm.event_we_owe_rows(event_id)
        for row in sm.we_owe_fulfillment_history(event_id, str(obligation[sm.WE_OWE_ID_ATTRIBUTE]))
    ]
    allocations = [
        ssm.allocation_payload(row)
        for row in inv.campaign_allocation_rows(lane.sales_campaign, show_and_sell_id=event_id)
    ]
    pool_cents = sum(int(row.get(sm.TOTAL_CENTS_ATTRIBUTE, 0) or 0) for row in sm.event_sale_rows(event_id))
    expected_cash_cents = sum(sm.sale_expected_cash_cents(row) for row in sm.event_sale_rows(event_id))
    adjusted_cents = expected_cash_cents + CASH_ADJUSTMENT_CENTS
    chocolate = stock_picture(inventory_table, lane.sales_campaign, lane.chocolate)
    butter = stock_picture(inventory_table, lane.sales_campaign, lane.butter)
    return {
        "event": {
            "id": event_id,
            "status": event["status"],
            "locationName": event["locationName"],
            "splitMethod": event["splitMethod"],
            "weOweEnabled": event["weOweEnabled"],
            "version": event["version"],
        },
        "sales": sales,
        "poolCents": pool_cents,
        "expectedCashCents": expected_cash_cents,
        "cashAdjustmentCents": CASH_ADJUSTMENT_CENTS,
        "cashAdjustmentReason": CASH_ADJUSTMENT_REASON,
        "adjustedExpectedCashCents": adjusted_cents,
        "actualCashCents": ACTUAL_CASH_CENTS,
        "discrepancyCents": ACTUAL_CASH_CENTS - adjusted_cents,
        "cashExplanation": CASH_EXPLANATION,
        "perScoutPendingCents": pool_cents // 2,
        "work": [ssm.signup_admin_payload(row) for row in ssm.event_signup_rows(event_id)],
        "slotRows": [ssm.slot_admin_payload(row) for row in ssm.event_slot_rows(event_id)],
        "obligations": obligations,
        "fulfillments": fulfillments,
        "allocationRemainingQty": sum(int(row["remainingQty"]) for row in allocations),
        "stock": {"chocolate": chocolate, "butter": butter},
        "movementViolations": movement_trail_violations(inventory_table, lane.sales_campaign, lane.chocolate)
        + movement_trail_violations(inventory_table, lane.sales_campaign, lane.butter),
        "saleLineWeOweTestId": SALE_LINE_WE_OWE_TEST_ID,
    }


# --- Lane cleanup (§7.1) --------------------------------------------------------


def _marker_needle(value: str) -> str:
    """The form of an id inside an idempotency marker's partition key."""
    return value.replace("#", "%23")


def _delete_markers(table: Any, needles: Sequence[str]) -> int:
    """Delete every ``IDEM#`` marker naming one of this lane's scopes."""
    deleted = 0
    for needle in needles:
        for row in _paged(
            table,
            FilterExpression="begins_with(pk, :prefix) AND contains(pk, :needle)",
            ExpressionAttributeValues={":prefix": "IDEM#", ":needle": _marker_needle(needle)},
        ):
            table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
            deleted += 1
    return deleted


def _event_rows(show_and_sells_table: Any, event_id: str) -> List[Dict[str, Any]]:
    return _paged(
        show_and_sells_table,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": ssm.show_and_sell_pk(event_id)},
    )


def _payment_rows(units_table: Any, lane: SalesLane) -> List[Dict[str, Any]]:
    return _paged(
        units_table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": f"UNIT#{lane.pack}", ":prefix": upm.PAYMENT_SK_PREFIX},
    )


def _delete_s3_objects(s3_client: Any, lane: SalesLane, payment_method_ids: Iterable[str]) -> int:
    """Delete both halves of every QR this lane's payment methods uploaded."""
    deleted = 0
    bucket = os.environ["EXPORTS_BUCKET"]
    for payment_method_id in payment_method_ids:
        prefix = upm.unit_qr_prefix(lane.pack, payment_method_id)
        token: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {"Bucket": bucket, "Prefix": f"{prefix}/"}
            if token is not None:
                kwargs["ContinuationToken"] = token
            page = s3_client.list_objects_v2(**kwargs)
            for item in page.get("Contents", []):
                s3_client.delete_object(Bucket=bucket, Key=str(item["Key"]))
                deleted += 1
            if not page.get("IsTruncated"):
                break
            token = str(page["NextContinuationToken"])
    return deleted


def clean_sales_lane(
    inventory_table: Any,
    show_and_sells_table: Any,
    units_table: Any,
    lane: SalesLane = DEFAULT_LANE,
    *,
    s3_client: Any = None,
) -> Dict[str, int]:
    """Remove one lane's Stage 4 records in §7.1 dependency order; report the counts.

    The sweeps follow the plan's numbering: §7.1 item 2 and 4 are the fulfillment,
    obligation, sale, work, signup, slot and event rows, and all of them live in one
    event partition, so that partition goes first, with the lane's ``IDEM#`` markers
    immediately after (item 4's writes are what made them). Item 5 is the inventory
    partition: allocations, custody, the movement trail and the balance. Item 8 is the
    Unit's named payment method, its capacity counter and the QR objects the row
    references; the payment rows are read before they are deleted because the QR prefix
    is keyed on the payment method id. Every read is paged, every address is derived from
    this lane, and nothing here reaches an account-wide range, so another lane's data and
    this lane's own canary campaign and marker survive the sweep.
    """
    client = s3_client or get_s3_client()
    event_ids = discover_event_ids(show_and_sells_table, lane.sales_campaign)
    removed = {"events": 0, "eventRows": 0, "markers": 0, "paymentMethods": 0, "qrObjects": 0, "inventory": 0}

    for event_id in event_ids:
        for row in _event_rows(show_and_sells_table, event_id):
            show_and_sells_table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
            removed["eventRows"] += 1
        removed["events"] += 1

    removed["markers"] += _delete_markers(show_and_sells_table, [lane.sales_campaign, *event_ids])

    for row in _paged(
        inventory_table,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": inv.inventory_pk(lane.sales_campaign)},
    ):
        inventory_table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
        removed["inventory"] += 1
    removed["markers"] += _delete_markers(inventory_table, [lane.sales_campaign])

    payment_rows = _payment_rows(units_table, lane)
    payment_method_ids = [str(row["paymentMethodId"]) for row in payment_rows if row.get("paymentMethodId")]
    for row in payment_rows:
        units_table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
        removed["paymentMethods"] += 1
    capacity_key = upm.payment_capacity_key(lane.pack)
    if units_table.get_item(Key=capacity_key).get("Item") is not None:
        units_table.delete_item(Key=capacity_key)
        removed["paymentMethods"] += 1
    # The method's own create/QR markers are scoped to the Unit, so they live in the
    # units table and name this lane's unitId. The lane's Unit-grant and Unit-creation
    # markers are not (their scope is the actor and ``BOOTSTRAP``), so they survive.
    removed["markers"] += _delete_markers(units_table, [lane.pack])

    removed["qrObjects"] += _delete_s3_objects(client, lane, payment_method_ids)
    return removed
