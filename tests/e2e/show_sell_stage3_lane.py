"""One Stage 3 acceptance lane, driven end to end on the deployed stack, with its cleanup record.

Checklist leaf §3.7.7 asks for "lane-scoped cleanup verification", and WORK-168's Amendment C says what
that means on shared ``dev``: everything a supported path can remove is removed and re-read absent, and
everything no supported path removes is enumerated, attributed and left.  This module is the pass that
produces that record.  It is a lane, not a unit test: every number it reports is read back from the
deployed stack through the product's own queries, and every deletion goes through a supported path —
the product's mutations for what the product can delete, and ``scripts/qa_fixture.py sweep`` for what it
cannot.

Run it against the stack the fixture identities live on::

    uv run python -m tests.e2e.show_sell_stage3_lane --out ../lane-records

It needs the environment the acceptance journeys need — ``TEST_QA_SHOW_SELL_BASE_URL`` (or
``E2E_BASE_URL``), ``TEST_USER_POOL_CLIENT_ID`` and the four ``TEST_QA_SHOW_SELL_*`` identity pairs that
``scripts/qa_fixture.py up`` writes.  Beyond those it uses the ambient AWS identity only the way the
sanctioned sweeper does — ``Scan``, a keyed ``Query``, and a strongly consistent ``GetItem`` of one exact key,
on the tables ``kernelworx-qa-ue1-dev`` can already open, with every refused read named in the record rather
than counted as empty — to count the residue a sweep report never names.  It never writes to a table: every
deletion is a product mutation or a ``scripts/qa_fixture.py sweep`` call, and the guard pass names below
makes no delete call at all.

What the lane does, in order:

1. Builds two lanes, not one: the lane under test and an **independent canary lane** with its own Unit,
   Unit Campaign, Scout Campaign and roster join.  A canary inside the lane proves nothing — the sweep is
   free to define its own rows out of the set, and an earlier lane named its canary ``<data_id>-can`` and
   its own sweep took the canary down.
2. Writes Stage 3 rows on the lane under test: one event, one inventory assignment, two slots, one Scout
   signup in a slot.
3. Takes the **residue census**
   (:func:`tests.e2e.utils.show_sell_stage3_support.stage_three_residue_census`) *before* any teardown,
   because the sweep deletes the Unit and Unit Campaign rows every one of those reads is keyed on, and
   afterwards ``NOT_FOUND`` proves the Campaign is gone and says nothing at all about the append-only
   movement rows that share its partition key.
4. Reads its own retained class back through the product: event status, allocation rows, slot rows,
   signup rows.
5. Tears the lane down in a ``finally`` — the run that fails halfway is the run that still cleans up —
   reporting one verdict per step, then runs the sanctioned sweeper over the typed lane tokens, naming
   each roster membership's Scout Campaign exactly (the active-join guard rule needs that id: one profile
   holds a guard per Campaign, so a ``profile`` token cannot say which Campaign is joined, and an unnamed
   guard comes back ``UNKNOWN`` and fails the sweep closed).  What is torn down and swept is whatever ids
   this run captured, not whether the lane reached its Stage 3 writes: a run refused after ``createUnit``
   still owes its Unit row and its marker to the sweep.
6. Gives back an ACTIVE ``ScoutCommitment`` an earlier attempt of **this lane id, or of a lane id named on
   the command line** left standing, and only one written on that lane's own event location
   (:func:`event_location`).  The card-wide prefix is not the gate: every lane this card runs signs in as
   the same four fixture identities, so a prefix match would let one checkout cancel the place another
   checkout is holding, and a cancelled signup cannot be re-created in its slot.  This pass runs inside the
   canary's protection window, after the canary exists and is snapshotted, with the canary's own event
   location excluded from it.
7. Re-reads the canary and fails if that sweep disturbed it, then takes the canary down with its own
   tokens so the record also shows the sweeper removing a lane it is pointed at.  Its removal has to be
   *read* absent, and read twice: a Campaign read that refuses is decided by the identity's own Unit list,
   and that list only counts because it answered the Unit before the sweep ran.
8. Counts the residue that survives all of it, per physical table, by read: Amendment C requires the
   retained class with counts and key shapes, and a sweep report cannot supply that count for a key shape
   no rule describes — such a row is neither deleted nor reported, so a record quoting only sweep lines
   would read as if nothing were left.
9. Exits on :func:`lane_failures`, never on the absence of a traceback: a blocked step fails under
   ``SS_STRICT_CLEANUP=1``, a canary that was never compared or never read back fails, and a run that was
   interrupted exits 130 because it has no verdict to report.

``--verify-guards`` runs one more thing on its own, and it is read-only by design: the membership-guard
disposition (:func:`verify_guard_residue`).  A ``campaign=`` token handed to the sweeper deletes scoped rows
on several tables on the strength of one id, and a guard row carries no lane id, so a pass that mutated
could take another lane's live join on a name match.  This pass therefore only reads: a strongly consistent
``GetItem`` of each exact key proves absence, and every key that is answered gets a state and a reason —
ownership settled by the sweeper's own fixture allowlist before any name match, and liveness decided by the
two rows the product itself reads.  Where the read that would settle the question is not granted to this
identity, the record names the table and the action instead of guessing.

The lane stops with words rather than a false pass when the stack cannot carry it: an API that answers no
Stage 3 endpoint raises with ``MISSING_ENDPOINT_NOTE``, and a catalog with no product to assign says so.
The exit status is :func:`lane_failures`, which applies the shared cleanup gate — so ``SS_STRICT_CLEANUP=1``
turns an environment-blocked step red, the one-step reversal Amendment C promises — plus the canary's
identity and its affirmative read-back.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import importlib.util
import json
import re
import secrets
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.e2e.utils import show_sell_graphql as api
from tests.e2e.utils import show_sell_stage2_support as stage2
from tests.e2e.utils import show_sell_stage3_support as stage3

#: The lane's Unit: the shape every Show & Sell lane uses, so the sweeper's Unit rules apply to it.
UNIT_TYPE = "Pack"
UNIT_CITY = "Denver"
UNIT_STATE = "CO"
CAMPAIGN_YEAR = 2026

#: Products the lane prefers when the Unit Campaign's catalog carries them.  Never invented: the id comes
#: from that catalog, and these names only decide which product the lane picks, so two runs of the record
#: read the same way.
PREFERRED_PRODUCTS = ("Caramel Corn", "Cheese Popcorn")

#: How far ahead of the clock the lane sits.  Cancellation is legal only before ``startAt``
#: (``src/utils/show_and_sell_models.py``: an event under way is finished by finalizing it), so a lane
#: that wants its own teardown to finish through the product starts in the future.  A lane that needs an
#: ``ACTIVE`` event — the work-confirmation probe — is a different lane, and it keeps its started event by
#: design: that is the retained class Amendment C enumerates rather than removes.
LEAD_DAYS = 3

#: Kernels the lane puts on its own shelf before it allocates any.  ``assignShowAndSellInventory`` is
#: checked against sellable stock at every instant the plan overlaps
#: (``src/utils/allocation_models.py``: "PRODUCT#… cannot be assigned this way: N Kernels are committed to
#: overlapping events…, against 0 sellable"), so a lane that allocates from an empty Unit Campaign is
#: refused before it writes anything, and the stock has to arrive through the shipped receipt path.
#: Six per product covers this lane's two Kernels per product with room for the overage warning to be the
#: only thing a reader could misread.
STOCK_PER_PRODUCT = 6

#: A uuid in any of the spellings this stack stores it in, masked out of a key the record reports.
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

#: The name every event this module writes carries.  It is a label, not the recovery gate: every lane this
#: card runs signs in as the same four fixture identities, so "this Scout holds it" is not attribution and
#: "this event's name starts with the card's prefix" is not either — it names every lane this card has ever
#: started, including one running on another checkout right now.  The gate is the exact location
#: :func:`event_location` mints for a lane id this run was told about, because a cancelled signup can never
#: be re-created in the same slot (``src/handlers/unit_operations.py``: "a cancelled signup stays history.
#: Choose another slot."), so a row cancelled on a guess is a row nobody can put back.
LANE_EVENT_PREFIX = "Stage 3 lane w168"

#: The Stage 1 setup calls this lane needs.  Stage 1 ships no acceptance-support document map, so the lane
#: carries its own four and keeps each narrow: it selects only the fields it then reads.
SETUP_DOCUMENTS: dict[str, str] = {
    "createUnit": """
mutation Stage3LaneCreateUnit($input: CreateUnitInput!) {
  createUnit(input: $input) {
    unit { unitId unitType unitNumber city state displayName timezone version updatedAt }
  }
}
""".strip(),
    "unitMetadata": """
query Stage3LaneUnit($unitId: ID!) {
  unit(unitId: $unitId) {
    unitId unitType unitNumber city state displayName timezone splitDefault
    councilNeedBasis version createdAt updatedAt
  }
}
""".strip(),
    "createUnitCampaign": """
mutation Stage3LaneCreateUnitCampaign($input: CreateUnitCampaignInput!) {
  createUnitCampaign(input: $input) {
    unitCampaignId unitId campaignName campaignYear catalogId isActive version
  }
}
""".strip(),
    "createScoutCampaign": """
mutation Stage3LaneCreateCampaign($input: CreateCampaignInput!) {
  createCampaign(input: $input) {
    campaignId profileId campaignName campaignYear catalogId isActive
  }
}
""".strip(),
    "joinUnitCampaign": """
mutation Stage3LaneJoinUnitCampaign($input: JoinUnitCampaignInput!) {
  joinUnitCampaign(input: $input) {
    unitCampaignId unitId campaignId profileId scoutName campaignName status version
  }
}
""".strip(),
}

#: One cleanup row, in the vocabulary the checklist quotes.
Row = dict[str, str]


def lane_names(data_id: str, *, unit_number: int) -> dict[str, str]:
    """The name set for one lane id: its Unit, Unit Campaign and Scout Campaign names.

    A canary's id must not contain the lane's id as a substring — see the module docstring.  The caller
    keeps the two ids disjoint; this only spells the names.
    """
    return {
        "dataId": data_id,
        "unitDisplayName": f"Stage 3 Lane {data_id}",
        "unitNumber": str(unit_number),
        "campaignName": f"Stage 3 Show & Sell {data_id}",
        "scoutCampaignName": f"Stage 3 Scout {data_id}",
    }


def event_location(data_id: str) -> str:
    """The exact ``locationName`` the event of one lane id carries.

    One function writes it and one gate reads it, which is the whole difference between "an event this card
    wrote" and "an event *this run* is allowed to cancel a place on".  The location is not a key the product
    matches on, so it stays stable for a lane id: :func:`write_stage_three_rows` sends it once, and
    :func:`recover_standing_commitments` compares it exactly rather than by prefix.
    """
    return f"{LANE_EVENT_PREFIX}{data_id.removeprefix('w168')}"


def authorized_lane_ids(current: str, prior: Sequence[str]) -> tuple[str, ...]:
    """The lane ids this run may write against: itself, plus the earlier attempts named for it.

    A prior lane is named on the command line (``--sweep-prior``) precisely so a later run can take that
    lane's rows back.  Nothing else is authorized: another card's lane, or this card's lane that is mid-flight
    somewhere else, is not residue this run owns.
    """
    return tuple(dict.fromkeys([value for value in (current, *prior) if value]))


def cancellable_locations(current: str, prior: Sequence[str], protected: Sequence[str] = ()) -> dict[str, str]:
    """Exact event location -> lane id, for the only lanes this run may cancel a signup on.

    ``protected`` names a lane whose location is removed even if it is also authorized.  The canary is the
    case: it is a lane of this card, its rows are this run's, and its Unit Campaign is still the one thing the
    record must be able to read unchanged on both sides of the sweep.
    """
    locations = {event_location(lane_id): lane_id for lane_id in authorized_lane_ids(current, prior)}
    for lane_id in protected:
        locations.pop(event_location(lane_id), None)
    return locations


def new_data_id(prefix: str = "w168lane") -> str:
    """A lane id the sweeper's ``data-id`` shape accepts, unique to the attempt.

    Both halves of the id are load-bearing.  An idempotency key is scoped by the lane id, so a lane that
    reuses an id reuses those keys, and a second attempt that sends different content under one key is
    refused with "This idempotencyKey was already used with different request content"; and the digits are
    also the Unit number, which the product matches on type + number + city + state and validates as a
    positive 32-bit integer — a month-to-second stamp is inside that range, a year-prefixed one is not.
    """
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%m%d%H%M%S")  # noqa: DTZ005 - a label, not a claim about the clock
    return f"{prefix}-{stamp}-{secrets.token_hex(2)}"


def sign_in(persona: str) -> str:
    """An ID token for one fixture persona, through the same public auth a browser user takes."""
    identities = api.qa_identities()
    return api.sign_in(identities[persona]["email"], identities[persona]["password"], api.client_id(), api.region())


def _one(body: Mapping[str, Any]) -> Any:
    """The single answer one GraphQL operation returned, by construction of these documents."""
    return next(iter(body.values()), None)


def _items(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``items`` of a paged answer, whatever field carried it."""
    payload = _one(body)
    return [dict(row) for row in (payload or {}).get("items") or []]


def _key(idempotency_key: str) -> dict[str, str]:
    """The ``IdempotencyInput`` the SDL declares: one key, nothing else."""
    return {"idempotencyKey": idempotency_key}


def _bare(value: Any) -> str:
    """One id in the spelling a sweep token wants.

    The API answers ``PROFILE#<uuid>`` and ``CAMPAIGN#<uuid>``, while ``scripts/qa_fixture.py`` matches a
    token against the stored key field and refuses anything that is not the bare id of that kind.
    """
    head, sep, rest = str(value or "").partition("#")
    return rest if sep else head


def build_lane(
    admin: str,
    scout: str,
    names: Mapping[str, str],
    catalog_id: str,
    progress: dict[str, Any],
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one lane's Unit, Unit Campaign, Scout Campaign and roster join, reading back what it made.

    Every id the lane later names to the sweeper is an id it was *answered*, never one it guessed at, and
    each one is recorded in the caller's dict the moment it is answered: the run that is refused at the join
    step still knows the Unit, Unit Campaign and Scout Campaign it created, which is what lets its sweep
    name those rows instead of leaving them unattributed for the next lane to trip over.

    A duplicate Unit is not papered over with ``duplicateConfirmed``.  The lane's Unit number comes from its
    own clock, so an exact type + number + city + state match means this lane is not unique on a shared
    stack, and taking the second intent silently would put two lanes' rows on one Unit.
    """
    data_id = str(names["dataId"])
    progress["dataId"] = data_id
    unit = _one(
        api.gql(
            admin,
            SETUP_DOCUMENTS["createUnit"],
            {
                "input": {
                    "unitType": UNIT_TYPE,
                    "unitNumber": int(names["unitNumber"]),
                    "city": UNIT_CITY,
                    "state": UNIT_STATE,
                    "displayName": names["unitDisplayName"],
                    "timezone": stage3.UNIT_TIMEZONE,
                    "idempotency": _key(stage3.idempotency_key_for("createUnit", data_id, "unit")),
                }
            },
        )
    )["unit"]
    progress["unitId"] = str(unit["unitId"])
    campaign = _one(
        api.gql(
            admin,
            SETUP_DOCUMENTS["createUnitCampaign"],
            {
                "input": {
                    "unitId": unit["unitId"],
                    "campaignName": names["campaignName"],
                    "campaignYear": CAMPAIGN_YEAR,
                    "catalogId": catalog_id,
                    "idempotency": _key(stage3.idempotency_key_for("createUnitCampaign", data_id, "campaign")),
                }
            },
        )
    )
    progress["unitCampaignId"] = str(campaign["unitCampaignId"])
    join_code = next(
        (
            str(row.get("joinCode") or "")
            for row in _items(
                api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": unit["unitId"]})
            )
            if row.get("unitCampaignId") == campaign["unitCampaignId"]
        ),
        "",
    )
    if not join_code:
        raise AssertionError(f"Unit Campaign {campaign['unitCampaignId']} answers no join code to its own Unit Admin")
    profile = profile or api.my_profiles(scout)[0]
    progress["profileId"] = str(profile["profileId"])
    scout_campaign = _one(
        api.gql(
            scout,
            SETUP_DOCUMENTS["createScoutCampaign"],
            {
                "input": {
                    "profileId": profile["profileId"],
                    "campaignName": names["scoutCampaignName"],
                    "campaignYear": CAMPAIGN_YEAR,
                    "catalogId": catalog_id,
                }
            },
        )
    )
    progress["scoutCampaignId"] = str(scout_campaign["campaignId"])
    _one(
        api.gql(
            scout,
            SETUP_DOCUMENTS["joinUnitCampaign"],
            {
                "input": {
                    "joinCode": join_code,
                    "campaignId": scout_campaign["campaignId"],
                    "idempotency": _key(stage3.idempotency_key_for("joinUnitCampaign", data_id, "join")),
                }
            },
        )
    )
    membership = next(
        (
            row
            for row in _items(
                api.gql(
                    admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": campaign["unitCampaignId"]}
                )
            )
            if row.get("campaignId") == scout_campaign["campaignId"]
        ),
        None,
    )
    if membership is None:
        raise AssertionError(f"the roster of {campaign['unitCampaignId']} does not answer the lane's own join")
    return {
        "dataId": data_id,
        "unitId": str(unit["unitId"]),
        "unitCampaignId": str(campaign["unitCampaignId"]),
        "profileId": str(profile["profileId"]),
        "scoutCampaignId": str(scout_campaign["campaignId"]),
        "membershipStatus": str(membership.get("status") or ""),
    }


def stage3_steps(written: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The Stage 3 (and Stage 2 stock) writes one lane actually sent, as ``(operation, step)`` pairs.

    This is derived from what the lane recorded, never from a count: the teardown and the sweep tokens are
    both built from this list, so an idempotency marker is only ever named by a lane that actually sent the
    write that minted it, and a run that was refused halfway names only the markers it really wrote.
    """
    slots = [str(slot["slotId"]) for slot in written.get("slots") or []]
    pairs: list[tuple[str, str]] = []
    if written.get("showAndSellId"):
        pairs.append(("createShowAndSell", "event"))
    pairs += [
        ("recordInventoryReceipt", f"receipt-{index}") for index in range(1, len(written.get("receipts") or []) + 1)
    ]
    if written.get("assignedProducts"):
        pairs.append(("assignShowAndSellInventory", "assign"))
    pairs += [("upsertShowAndSellSlot", f"slot-{index}") for index in range(1, len(slots) + 1)]
    if written.get("signup"):
        pairs.append(("signupScoutForShowAndSellSlot", "signup-1"))
        pairs.append(("cancelShowAndSellSignup", "cancel-signup"))
    pairs += [("deleteShowAndSellSlot", f"delete-slot-{index}") for index in range(1, len(slots) + 1)]
    if written.get("showAndSellId"):
        pairs.append(("cancelShowAndSell", "cancel"))
    return pairs


def write_stage_three_rows(
    admin: str, scout: str, lane: Mapping[str, Any], products: Sequence[str], progress: dict[str, Any]
) -> dict[str, Any]:
    """The Stage 3 writes this lane owns: one event, one assignment, two slots, one signup.

    Each write uses the shipped builder for that field, so the marker rows the sweeper later names are the
    markers these writes actually produced.  Progress is recorded in the caller's dict as each write lands,
    because the run that is refused halfway still has to cancel the event it did manage to create: a lane
    that loses the event id on the way to its own teardown leaves a row no supported path can take back.
    """
    data_id = str(lane["dataId"])
    progress.setdefault("slots", [])
    progress.setdefault("assignedProducts", [])
    progress.setdefault("warnings", [])

    def key(operation: str, step: str) -> str:
        return stage3.idempotency_key_for(operation, data_id, step)

    clock = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=LEAD_DAYS)
    created = _one(
        api.gql(
            admin,
            stage3.STAGE_THREE_DOCUMENTS["createShowAndSell"],
            {
                "input": stage3.create_event_input(
                    str(lane["unitCampaignId"]),
                    event_location(data_id),
                    clock.isoformat(),
                    (clock + dt.timedelta(hours=4)).isoformat(),
                    idempotency_key=key("createShowAndSell", "event"),
                )
            },
        )
    )
    event_id = str(created["showAndSellId"])
    progress["showAndSellId"] = event_id
    progress["createdStatus"] = str(created.get("status") or "")
    progress["startAt"] = clock.isoformat()
    progress["receipts"] = [
        _one(
            api.gql(
                admin,
                stage2.STAGE_TWO_DOCUMENTS["recordInventoryReceipt"],
                {
                    "input": stage2.receipt_input(
                        str(lane["unitCampaignId"]),
                        product,
                        STOCK_PER_PRODUCT,
                        idempotency_key=key("recordInventoryReceipt", f"receipt-{index}"),
                    )
                },
            )
        )
        for index, product in enumerate(products, start=1)
    ]
    assigned = _one(
        api.gql(
            admin,
            stage3.STAGE_THREE_DOCUMENTS["assignShowAndSellInventory"],
            {
                "input": stage3.assign_inventory_input(
                    event_id,
                    [(product, 2) for product in products],
                    _event_version(admin, event_id),
                    idempotency_key=key("assignShowAndSellInventory", "assign"),
                )
            },
        )
    )
    progress["assignedProducts"] = list(products)
    progress["warnings"] = [
        str(row.get("message") or row.get("code") or "") for row in (assigned or {}).get("warnings") or []
    ]
    for index in (1, 2):
        slot = _one(
            api.gql(
                admin,
                stage3.STAGE_THREE_DOCUMENTS["upsertShowAndSellSlot"],
                {
                    "input": stage3.upsert_slot_input(
                        event_id,
                        _event_version(admin, event_id),
                        (clock + dt.timedelta(hours=index - 1)).isoformat(),
                        (clock + dt.timedelta(hours=index)).isoformat(),
                        2,
                        label=f"Shift {index}",
                        idempotency_key=key("upsertShowAndSellSlot", f"slot-{index}"),
                    )
                },
            )
        )
        progress["slots"].append({"slotId": str(slot["slotId"]), "label": f"Shift {index}"})
    signup = _one(
        api.gql(
            scout,
            stage3.STAGE_THREE_DOCUMENTS["signupScoutForShowAndSellSlot"],
            {
                "input": stage3.signup_input(
                    event_id,
                    str(progress["slots"][0]["slotId"]),
                    str(lane["scoutCampaignId"]),
                    str(lane["profileId"]),
                    idempotency_key=key("signupScoutForShowAndSellSlot", "signup-1"),
                )
            },
        )
    )
    progress["signup"] = {
        "slotId": str(progress["slots"][0]["slotId"]),
        "status": str((signup or {}).get("status") or ""),
    }
    return progress


def _event_version(admin: str, event_id: str) -> int:
    detail = _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id}))
    return int(detail["version"])


def lane_reads(admin: str, unit_campaign_id: str) -> dict[str, Any]:
    """What the product answers for one Unit Campaign right now: stock, allocations, events, signups.

    These are the counts the record enumerates as residue, read through the same documents the acceptance
    assertions use, so a number in the record is a number the API gave rather than one the lane remembers
    writing.
    """
    positions = _items(
        api.gql(admin, stage2.STAGE_TWO_DOCUMENTS["inventoryPositions"], {"unitCampaignId": unit_campaign_id})
    )
    movements = _items(
        api.gql(admin, stage2.STAGE_TWO_DOCUMENTS["inventoryMovements"], {"unitCampaignId": unit_campaign_id})
    )
    allocations = _items(
        api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["eventInventoryAllocations"], {"unitCampaignId": unit_campaign_id})
    )
    events = _items(
        api.gql(
            admin,
            stage3.STAGE_THREE_DOCUMENTS["showAndSells"],
            {"unitCampaignId": unit_campaign_id, "page": {"limit": 50}},
        )
    )
    signups = [
        row
        for event in events
        for row in _items(
            api.gql(
                admin,
                stage3.STAGE_THREE_DOCUMENTS["showAndSellSignups"],
                {"showAndSellId": str(event["showAndSellId"])},
            )
        )
    ]
    return {
        "positionRows": [
            {
                "productId": str(row.get("productId")),
                "kernelPhysicalQty": row.get("kernelPhysicalQty"),
                "assignedOpenQty": row.get("assignedOpenQty"),
                "version": row.get("version"),
            }
            for row in positions
        ],
        "movementRows": len(movements),
        "movementTypes": sorted({str(row.get("movementType")) for row in movements}),
        "allocationRows": [
            {
                "productId": str(row.get("productId")),
                "status": str(row.get("status")),
                "allocatedQty": row.get("allocatedQty"),
                "releasedQty": row.get("releasedQty"),
            }
            for row in allocations
        ],
        "events": [
            {
                "showAndSellId": str(row.get("showAndSellId")),
                "status": str(row.get("status")),
                "startAt": str(row.get("startAt")),
                "version": row.get("version"),
            }
            for row in events
        ],
        "signups": [
            {
                "slotId": str(row.get("slotId")),
                "status": str(row.get("status")),
                "signupVersion": row.get("signupVersion"),
            }
            for row in signups
        ],
    }


def canary_snapshot(admin: str, canary: Mapping[str, Any]) -> dict[str, Any]:
    """The canary lane's rows, exactly as the API answered them, for a byte-for-byte before/after compare.

    Two things keep that compare worth reading.  The join code is masked on the way in — the same masking the
    residue census applies to a join-code partition key — because the snapshot goes into the lane record, and
    a record quoted into a PR would otherwise publish a live code.  And a snapshot that answers no Unit, no
    Unit Campaign or no roster row is refused rather than returned: an empty snapshot compares equal to an
    empty one, which would report the canary untouched on the strength of having read nothing.
    """
    snapshot = {
        "unit": _one(api.gql(admin, SETUP_DOCUMENTS["unitMetadata"], {"unitId": canary["unitId"]})),
        "unitCampaigns": _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": canary["unitId"]})
        ),
        "roster": _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": canary["unitCampaignId"]})
        ),
    }
    for row in snapshot["unitCampaigns"]:
        if row.get("joinCode"):
            row["joinCode"] = "*" * len(str(row["joinCode"]))
    missing = [name for name, value in snapshot.items() if not value]
    if missing:
        raise AssertionError(
            f"the canary snapshot for lane {canary.get('dataId')} answered no "
            f"{'/'.join(missing)} row, so a before/after compare on it would be vacuous"
        )
    return snapshot


def teardown(admin: str, scout: str, lane: Mapping[str, Any], written: Mapping[str, Any]) -> list[Row]:
    """Take the lane's own rows back through the product, one verdict per step.

    Signup, then slots, then the event: a slot cannot go while it holds a signup (the server refuses with
    "This slot has N active signup(s)") and the event is what releases the allocation.  Every step is
    wrapped by :func:`tests.e2e.utils.show_sell_stage3_support.run_cleanup_step`, so a refusal is a
    ``failed`` row and an impossible step is a ``blocked`` row naming why — never a removal.
    """
    rows: list[Row] = []
    event_id = str(written.get("showAndSellId") or "")
    data_id = str(lane["dataId"])
    signup = written.get("signup") or {}
    if event_id:
        if signup.get("slotId"):
            rows.append(
                stage3.run_cleanup_step(
                    "§3.7.7 cancel the lane's signup",
                    lambda: _cancel_signup(
                        scout, admin, data_id, event_id, str(signup["slotId"]), str(lane["profileId"])
                    ),
                )
            )
        for index, slot in enumerate(written.get("slots") or [], start=1):
            slot_id = str(slot["slotId"])
            rows.append(
                stage3.run_cleanup_step(
                    "§3.7.7 delete the lane's slot",
                    lambda slot_id=slot_id, index=index, data_id=data_id: _delete_slot(
                        admin, data_id, event_id, slot_id, index
                    ),
                )
            )
        rows.append(
            stage3.run_cleanup_step(
                "§3.7.7 cancel the lane's event",
                lambda: _cancel_event(admin, data_id, event_id, f"Stage 3 lane cleanup {data_id}"),
            )
        )
    if lane.get("scoutCampaignId"):
        rows.append(
            stage3.run_cleanup_step(
                "§3.7.7 remove the lane's roster join",
                lambda: _remove_join(admin, data_id, lane),
            )
        )
        rows.append(
            stage3.run_cleanup_step(
                "§3.7.7 delete the lane's Scout Campaign",
                lambda: _remove_scout_campaign(scout, lane),
            )
        )
    return rows


def _delete_scout_campaign(scout: str, campaign_id: str) -> bool:
    """``deleteCampaign`` is the shipped path for a Scout Campaign row, so the lane uses it on its own.

    The mutation deletes the Campaign and its Orders; it does not touch the active-join guard, which is why
    the sweep still names that row by its exact Campaign id afterwards.  A Campaign that is already gone is
    reported rather than raised, because this path runs again for a lane an earlier attempt left behind, and
    a second delete of an absent row is the wanted state, not a failure.
    """
    try:
        api.gql(scout, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["deleteCampaign"], {"campaignId": campaign_id})
    except api.GraphQLError as exc:
        if "NOT_FOUND" in (getattr(exc, "codes", None) or []):
            return False
        raise
    answer = api.gql_raw(scout, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["scoutCampaign"], {"campaignId": campaign_id})
    if (answer.get("data") or {}).get("getCampaign"):
        raise AssertionError(f"{campaign_id} is still answered by getCampaign after deleteCampaign")
    return True


def _remove_scout_campaign(scout: str, lane: Mapping[str, Any]) -> str:
    """One teardown step's wording for :func:`_delete_scout_campaign`."""
    campaign_id = str(lane["scoutCampaignId"])
    if not _delete_scout_campaign(scout, campaign_id):
        return f"{campaign_id} answers NOT_FOUND — this lane's Scout Campaign row is already gone"
    return (
        "the Scout Campaign row is no longer answered by getCampaign; its guard row stays and the sweep "
        "names it by Campaign id"
    )


def _remove_join(admin: str, data_id: str, lane: Mapping[str, Any]) -> str:
    """The shipped removal path for a roster row: ``removeUnitCampaignMembership``, then read it back.

    The product's own step is the supported path, and it is what the checklist's cleanup criterion means
    by "removed": the roster row goes to ``REMOVED`` and the active-join guard's ``activeUnitCampaignId``
    is cleared.  Neither row disappears — ``guard_release_action`` leaves the guard row, and the membership
    row is history — so the sweeper takes the guard by its exact Campaign id and the membership row is
    enumerated as a retained row rather than claimed removed.
    """
    roster = _items(
        api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": lane["unitCampaignId"]})
    )
    row = next((item for item in roster if str(item.get("campaignId")) == str(lane["scoutCampaignId"])), None)
    if row is None:
        return "nothing to remove — the roster answers no join for the lane's own Scout Campaign"
    _one(
        api.gql(
            admin,
            stage2.STAGE_TWO_SUPPORT_DOCUMENTS["removeMembership"],
            {
                "input": stage2.remove_membership_input(
                    str(lane["unitCampaignId"]),
                    str(lane["scoutCampaignId"]),
                    int(row.get("version") or 1),
                    int(row.get("guardVersion") or 1),
                    idempotency_key=stage3.idempotency_key_for("removeUnitCampaignMembership", data_id, "remove-join"),
                )
            },
        )
    )
    again = _items(
        api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": lane["unitCampaignId"]})
    )
    status = next(
        (str(item.get("status")) for item in again if str(item.get("campaignId")) == str(lane["scoutCampaignId"])),
        "absent",
    )
    if status not in {"REMOVED", "absent"}:
        raise AssertionError(f"the roster still answers this join as {status} after removeUnitCampaignMembership")
    return f"roster join answered {status} on re-read; the guard row itself stays and the sweep names it by Campaign id"


def _standing_commitments(scout: str) -> list[dict[str, Any]]:
    """Every ``ScoutCommitment`` the fixture Scout holds, including cancelled ones, read from her own list.

    This is the read that finds a commitment a lane orphaned: the signup's projection is keyed by the Scout's
    own ``profileId``, so it answers even after the sweeper took the Unit and Unit Campaign rows every other
    Stage 3 read is keyed on — while the Unit-based board read (``showAndSellSignups``) answers
    ``Unit not found`` for that same row.
    """
    rows: list[dict[str, Any]] = []
    for profile in api.my_profiles(scout):
        body = api.gql(
            scout,
            stage3.STAGE_THREE_DOCUMENTS["myScoutCommitments"],
            {"profileId": str(profile["profileId"]), "includeCancelled": True, "page": {"limit": 50}},
        )
        rows += [{**dict(row), "profileId": str(profile["profileId"])} for row in _items(body)]
    return rows


def _active_commitments(scout: str) -> list[dict[str, Any]]:
    """The ``ScoutCommitment`` rows still answering ``ACTIVE`` — the set that makes a profile unavailable.

    The overlap guard is per profile, so this is the read that decides which profile a lane may sign its
    Scout up on without touching anyone else's place, and the read-back that says whether a recovery pass
    actually cleared the orphans it was authorized to clear.
    """
    return [row for row in _standing_commitments(scout) if str(row.get("status") or "") == "ACTIVE"]


def _event_detail(admin: str, event_id: str) -> Mapping[str, Any]:
    """One event aggregate as the product answers it.

    This is the read every recovery decision is taken from — status, slots, and the ``locationName`` that
    attributes an event to one lane id — so an event whose read is refused is reported, never assumed.
    """
    return _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id})) or {}


def _cancel_signup(
    scout: str,
    admin: str,
    data_id: str,
    event_id: str,
    slot_id: str,
    profile_id: str,
    step: str = "cancel-signup",
    version: int | None = None,
) -> str:
    """Cancel one signup through the shipped mutation, then read the release back.

    The cancellation is sent with the Scout's token; the row's version comes from the Kernel's board read
    when that read still answers, and from the Scout's own commitment projection when it does not.  Both
    halves are measured, not stylistic: on ``dev`` at ``da90fad6`` ``showAndSellSignups`` is refused to a
    joined Scout with ``Unit not found``, while ``cancelShowAndSellSignup`` deliberately asks nothing about
    the roster (``src/handlers/unit_operations.py``: a Scout removed from membership still has a place to
    give back, and a caller who is not the Unit's Kernel is authorized by profile access alone), so the Scout
    is the entitled canceller while the Kernel is the only one of the two who can read the board.  A version
    is not optional — ``_require_read_version`` refuses a number that disagrees with the row — so a lane
    whose Unit is gone takes its number from ``myScoutCommitments``, which the product keeps in step with the
    signup for exactly this reason.  The read-back uses the same Scout-side read either way.
    """
    board_error = ""
    try:
        board = _items(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSellSignups"], {"showAndSellId": event_id}))
    except api.GraphQLError as exc:
        # The board is keyed on rows the sweeper deletes, so an orphaned signup has no board read left.
        board, board_error = [], f"{exc.args[0] if exc.args else exc}"
    row = next((item for item in board if str(item.get("slotId")) == slot_id), None)
    if row is not None:
        # ``ShowAndSellSignup.version`` is the field the cancellation conditions on (SDL 1996-1997); the
        # ScoutCommitment projection calls the same number ``signupVersion``, and reading the wrong name
        # silently sends a stale number and earns a CONFLICT.
        version, source = int(row.get("version") or row.get("signupVersion") or 1), "the Kernel's signup board"
    elif version is not None:
        source = f"the Scout's own ScoutCommitment projection, the board read having answered {board_error!r}"
    else:
        return "nothing to remove — the event answers no signup row for that slot"
    _one(
        api.gql(
            scout,
            stage3.STAGE_THREE_DOCUMENTS["cancelShowAndSellSignup"],
            {
                "input": stage3.cancel_signup_input(
                    event_id,
                    slot_id,
                    profile_id,
                    version,
                    idempotency_key=stage3.idempotency_key_for("cancelShowAndSellSignup", data_id, step),
                )
            },
        )
    )
    if row is not None:
        again = _items(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSellSignups"], {"showAndSellId": event_id}))
        status = next((str(item.get("status")) for item in again if str(item.get("slotId")) == slot_id), "absent")
    else:
        commitment = next(
            (
                item
                for item in _standing_commitments(scout)
                if str(item.get("showAndSellId")) == event_id and str(item.get("slotId")) == slot_id
            ),
            None,
        )
        status = str(commitment.get("status")) if commitment else "absent"
    if status == "ACTIVE":
        raise AssertionError(f"the signup still answers as {status} after cancelShowAndSellSignup")
    return (
        f"signup of {profile_id} in slot {slot_id} answered {status} on re-read of {source}; "
        f"the version sent was {version} and the signup row itself stays as history"
    )


def _delete_slot(admin: str, data_id: str, event_id: str, slot_id: str, index: int) -> str:
    _one(
        api.gql(
            admin,
            stage3.STAGE_THREE_DOCUMENTS["deleteShowAndSellSlot"],
            {
                "input": stage3.delete_slot_input(
                    event_id,
                    slot_id,
                    _event_version(admin, event_id),
                    idempotency_key=stage3.idempotency_key_for(
                        "deleteShowAndSellSlot", data_id, f"delete-slot-{index}"
                    ),
                )
            },
        )
    )
    remaining = [
        str(slot.get("slotId"))
        for slot in (
            _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id})) or {}
        ).get("slots")
        or []
    ]
    if slot_id in remaining:
        raise AssertionError(f"slot {slot_id} is still answered after the delete")
    return f"slot {slot_id} is no longer answered by the event ({len(remaining)} slot(s) left)"


def _cancel_event(admin: str, data_id: str, event_id: str, reason: str) -> str:
    _one(
        api.gql(
            admin,
            stage3.STAGE_THREE_DOCUMENTS["cancelShowAndSell"],
            {
                "input": stage3.cancel_event_input(
                    event_id,
                    _event_version(admin, event_id),
                    reason,
                    idempotency_key=stage3.idempotency_key_for("cancelShowAndSell", data_id, "cancel"),
                )
            },
        )
    )
    detail = _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id}))
    return f"event answered {detail.get('status')} with reason {detail.get('cancellationReason')!r}"


def sweep_tokens(
    lane: Mapping[str, Any], written: Mapping[str, Any] | None, extra_steps: Sequence[str] = ()
) -> list[str]:
    """The typed lane tokens for one finished lane: every id it was answered, by kind.

    ``scripts/qa_fixture.py sweep`` compares a token only to the field its kind names, and refuses a value
    that does not match that field's stored shape, so each id is handed over bare: the API answers
    ``CAMPAIGN#<uuid>`` for a Scout Campaign and ``UNIT#<uuid>`` is only ever a key prefix in DynamoDB.
    The Scout Campaign id is what resolves the active-join guard — the guard row carries the Campaign, and
    one profile holds a guard per Campaign, so naming the profile cannot say which Campaign is joined, and
    an unnamed guard comes back ``UNKNOWN`` and fails the sweep closed.

    No ``profile`` token is sent, and that is deliberate.  The four fixture identities are shared by every
    lane on this stack, so a ``profile`` token selects every Campaign that Scout has ever joined: it would
    turn another lane's guard into ``UNKNOWN`` (which fails this sweep closed) and it buys nothing, because
    the only row a profile token could take for this lane is the roster membership, and the product's own
    removal path soft-removes that while the sweeper's rule deletes it only with a profile token.
    """
    data_id = str(lane["dataId"])
    tokens = [
        f"{kind}={_bare(lane[field])}"
        for kind, field in (("unit", "unitId"), ("unit-campaign", "unitCampaignId"), ("campaign", "scoutCampaignId"))
        if lane.get(field)
    ]
    # A setup marker is named only for a write whose answer the lane holds, because the marker and the id
    # are written by the same mutation: a token for a write that never landed would be a claim with no row.
    # ``createCampaign`` is Stage 1 and takes no ``IdempotencyInput``, so it mints no marker at all.
    for operation, step, field in (
        ("createUnit", "unit", "unitId"),
        ("createUnitCampaign", "campaign", "unitCampaignId"),
        ("joinUnitCampaign", "join", "scoutCampaignId"),
    ):
        if lane.get(field):
            tokens.append(f"idem={stage3.idempotency_key_for(operation, data_id, step)}")
    steps = stage3_steps(written) if written else []
    tokens += [f"idem={stage3.idempotency_key_for(operation, data_id, step)}" for operation, step in steps]
    tokens += [f"idem={stage3.idempotency_key_for('cancelShowAndSellSignup', data_id, step)}" for step in extra_steps]
    if lane.get("scoutCampaignId"):
        tokens.append(f"idem={stage3.idempotency_key_for('removeUnitCampaignMembership', data_id, 'remove-join')}")
    return list(dict.fromkeys(tokens))


def classify_sweep(lines: Sequence[str]) -> dict[str, list[str]]:
    """Split a sweeper report into the classes :func:`tests.e2e.utils.show_sell_stage2_support.sweep_verdict` judges."""
    classes: dict[str, list[str]] = {"left": [], "failed": [], "unknown": [], "history": [], "kept": [], "blocked": []}
    for line in lines:
        text = line.strip()
        for word, bucket in (
            ("LEFT", "left"),
            ("FAILED", "failed"),
            ("UNKNOWN", "unknown"),
            ("HISTORY", "history"),
            ("kept", "kept"),
            ("BLOCKED", "blocked"),
        ):
            if text.startswith(word):
                classes[bucket].append(text)
                break
    return classes


@functools.lru_cache(maxsize=1)
def _fixture_tool() -> Any:
    """``scripts/qa_fixture.py`` as a module, for its table map, its region and its scan client.

    Imported rather than re-implemented: a residue census keyed by *physical* table name is only comparable
    with the sweep's own report when both read the same ``SWEEP_TABLES`` map, and re-declaring the six names
    is how a census drifts onto a table the sweeper never opens.  Nothing here writes: the only DynamoDB
    calls this module makes are ``Scan`` and a keyed ``Query``, on the tables the fixture identity can already
    read, and every deletion stays a product mutation or a ``qa_fixture.py sweep`` call.
    """
    path = Path(__file__).resolve().parents[2] / "scripts" / "qa_fixture.py"
    spec = importlib.util.spec_from_file_location("qa_fixture_lane_tool", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load the sanctioned fixture tool at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key_shape(pk: str, sk: str) -> str:
    """One row's key in reporting shape: prefixes kept, ids masked, join codes never reproduced."""
    if pk.startswith("JOIN_CODE#"):
        pk = "JOIN_CODE/****************"
    return f"{_UUID.sub('<id>', pk)}/{_UUID.sub('<id>', sk)}"


def residue_census(lane_ids: Sequence[str], own_ids: Sequence[str]) -> tuple[list[Row], dict[str, Any]]:
    """Count, read-only, every row a readable swept table still answers for this card's lane ids.

    Amendment C requires the retained class "enumerated with counts, key shapes and the reason no shipped
    path removes it".  A sweep report cannot supply that count for this class: ``_lane_rule`` in
    ``scripts/qa_fixture.py`` answers "not this sweep's business" (``None``) for a key shape it does not
    describe, so a row outside the rule table is neither deleted, nor ``kept``, nor ``UNKNOWN`` — it is
    simply never named, and a record that quoted only sweep lines would read as if nothing were left.
    ``kernelworx-units-ue1-dev`` holds exactly that shape: ``createUnit`` mints its idempotency marker under
    pk ``IDEM#<actor>#createUnit#BOOTSTRAP``, and the ``units`` rule describes only ``UNIT#<id>/METADATA``
    and ``UNIT#<id>/GRANT#<sub>``, so a lane that had its Unit row taken back still leaves its marker behind,
    unreported.  The application offers no mutation that deletes an idempotency marker either.

    So the census is a read, and a deliberately narrow one: the same fixture identity the sweeper already
    uses (``kernelworx-qa-ue1-dev``), ``Scan`` only, and only the three tables that identity can already
    open — the three it cannot open stay answered by the product-read census, which is the whole point of
    Amendment C's second part.  A row is counted when one of this card's lane ids appears in it, which is
    attribution by construction rather than inference: those ids are this module's naming templates.

    ``own_ids`` is the gate inside the census.  This run's own Unit, Unit Campaign and Scout Campaign ids
    must come back with zero rows: a row this run wrote and no path removed is a failure, while an older
    lane's marker is residue the record enumerates.
    """
    tool = _fixture_tool()
    client = tool.ddb()
    wanted = [value for value in lane_ids if value]
    mine = [value for value in own_ids if value]
    detail: dict[str, Any] = {}
    rows: list[Row] = []
    survivors: list[str] = []
    for _label, (table, _keys, _owner) in tool.SWEEP_TABLES.items():
        try:
            shapes, hits, scanned = _scan_for_ids(client, table, wanted, tool)
        except Exception as exc:  # noqa: BLE001 - a denied scan is reported, never read as empty
            detail[table] = {"blocked": f"{type(exc).__name__}: {str(exc)[:200]}"}
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 enumerate the residue a sweep report never names",
                    f"{table}: blocked — this identity cannot open the table, so its residue is answered by the "
                    "product read census above rather than by a scan",
                )
            )
            continue
        detail[table] = {"rows": scanned, "shapes": shapes, "examples": [masked for masked, _ in hits][:6]}
        for shape, count in shapes.items():
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 enumerate the residue a sweep report never names",
                    f"{table}: {count} row(s) of shape {shape} still answer this card's lane ids "
                    f"({', '.join(sorted(wanted)[:3])}…); no sweep rule describes that key shape, so the "
                    "sweeper neither takes it nor reports it, and no shipped mutation deletes it",
                )
            )
        for masked, raw_key in hits:
            if any(value in raw_key for value in mine):
                survivors.append(f"{table} {masked}")
    rows.append(
        stage3.cleanup_row(
            "§3.7.7 re-read this run's own ids in every readable swept table",
            f"{'this run left 0 row(s): ' + ', '.join(mine) + ' answer nothing in any readable swept table'}"
            if not survivors
            else f"this run still answers {len(survivors)} row(s): {'; '.join(survivors[:6])}",
            stage2.CLEANUP_OBSERVED if not survivors else stage2.CLEANUP_FAILED,
        )
    )
    return rows, detail


def _scan_for_ids(
    client: Any, table: str, wanted: Sequence[str], tool: Any
) -> tuple[dict[str, int], list[tuple[str, str]], int]:
    """Scan one table once and bucket the rows naming any of ``wanted`` by key shape.

    Each hit comes back twice: the masked key shape the record reports, and the raw key the caller matches
    its own ids against.  The raw form never reaches the record, because a join-code partition key is a live
    fixture code and a record read into a PR would publish it.
    """
    shapes: dict[str, int] = {}
    hits: list[tuple[str, str]] = []
    scanned = 0
    scan_kw: dict[str, Any] = {"TableName": table, "ConsistentRead": False}
    while True:
        page = client.scan(**scan_kw)
        for item in page.get("Items", []):
            flat = tool._strings(item)
            pk, sk = flat.get("pk", ""), flat.get("sk", "")
            if not any(any(who in value for who in wanted) for value in (pk, sk)):
                continue
            shape = _key_shape(pk, sk)
            shapes[shape] = shapes.get(shape, 0) + 1
            hits.append((shape, f"{pk}/{sk}"))
            scanned += 1
        if "LastEvaluatedKey" not in page:
            return shapes, hits, scanned
        scan_kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def sweep_row(tokens: Sequence[str], census: Mapping[str, str]) -> tuple[Row, dict[str, Any]]:
    """Run the sanctioned sweeper and turn its report into one cleanup row plus the raw detail.

    A ``BLOCKED`` table is accepted residue only where the record names the product read that counted this
    lane's rows in its place — the census taken before the teardown.  Without that answer the table is
    ``unproven`` and the step stays non-clean, which is the difference between "we could not read it" and
    "we proved what is in it".
    """
    exit_code, _blocked, lines = stage2.fixture_sweep(tokens)
    classes = classify_sweep(lines)
    unproven = [line for line in classes["blocked"] if not stage3.is_census_statement(census.get(_table_of(line), ""))]
    verdict = stage2.sweep_verdict(
        left=classes["left"],
        failed=classes["failed"],
        unknown=classes["unknown"],
        history=classes["history"],
        blocked=classes["blocked"],
        unproven=unproven,
        exit_code=exit_code,
    )
    summary = (
        f"sweep over {len(tokens)} typed lane token(s): exit {exit_code}; "
        f"{len(classes['kept'])} row(s) kept as another tenant's or a soft-removed roster row, "
        f"{len(classes['unknown'])} unresolved, {len(classes['left'])} left, {len(classes['failed'])} failed, "
        f"{len(classes['history'])} history row(s) retained, {len(classes['blocked'])} table(s) unreadable, "
        f"{len(unproven)} of them unproven"
    ) + "".join(f"; residue census: {census.get(_table_of(line), '')}" for line in classes["blocked"])
    detail = {"exitCode": exit_code, "tokens": list(tokens), "unproven": unproven, "report": lines, **classes}
    return {"acceptance": "§3.7.7 lane sweep", "summary": summary, "result": verdict}, detail


def _table_of(blocked_line: str) -> str:
    """The physical table one ``BLOCKED`` line names."""
    _word, _space, rest = blocked_line.partition(" ")
    table, _colon, _reason = rest.partition(":")
    return table.strip()


def _shared_catalog(admin: str) -> tuple[str, list[str]]:
    """The dev stack's shared catalog and the product ids it offers."""
    body = api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["managedCatalogs"], {})
    rows = [dict(row) for row in (_one(body) or [])]
    chosen = next((row for row in rows if str(row.get("catalogType")) == "ADMIN_MANAGED"), {})
    return str(chosen.get("catalogId") or ""), [str(row.get("productId")) for row in chosen.get("products") or []]


#: The idempotency keys this lane can ever mint, as ``(operation, step)`` pairs.  A key is deterministic in
#: the lane id (``stage3-<DATA_ID>-<op>[-step]``, see
#: :func:`tests.e2e.utils.show_sell_stage3_support.idempotency_key_for`), so a later run can name the markers
#: an earlier attempt of the same lane left even when that attempt wrote no record.  A token that matches no
#: row deletes nothing, and the sweeper still deletes a marker only when a fixture identity authored it, so
#: naming the full set is safe where guessing at one id would not be.
LANE_MARKER_KEYS: tuple[tuple[str, str], ...] = (
    ("createUnit", "unit"),
    ("createUnitCampaign", "campaign"),
    ("joinUnitCampaign", "join"),
    ("removeUnitCampaignMembership", "remove-join"),
    ("createShowAndSell", "event"),
    ("recordInventoryReceipt", "receipt-1"),
    ("recordInventoryReceipt", "receipt-2"),
    ("assignShowAndSellInventory", "assign"),
    ("upsertShowAndSellSlot", "slot-1"),
    ("upsertShowAndSellSlot", "slot-2"),
    ("signupScoutForShowAndSellSlot", "signup-1"),
    ("cancelShowAndSellSignup", "cancel-signup"),
    ("deleteShowAndSellSlot", "delete-slot-1"),
    ("deleteShowAndSellSlot", "delete-slot-2"),
    ("cancelShowAndSell", "cancel"),
)


def _lane_units(admin: str) -> list[dict[str, Any]]:
    """Every Unit this identity can see, paging the connection to its end.

    ``show_sell_graphql.my_units`` asks for one page of 50, which is enough for a fresh tenant and not enough
    for the shared fixture admin after a dozen lanes.  A prior lane whose Unit is never read would be reported
    as gone, so the page has to be walked.
    """
    units: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body = _one(
            api.gql(
                admin,
                """
query Stage3LaneUnits($limit: Int, $cursor: String) {
  myUnits(page: {limit: $limit, cursor: $cursor}) {
    items { unitId unitType unitNumber city state displayName }
    pageInfo { endCursor hasNextPage }
  }
}
""".strip(),
                {"limit": 50, "cursor": cursor},
            )
        )
        units += [dict(row) for row in (body or {}).get("items") or []]
        page_info = (body or {}).get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            return units
        cursor = str(page_info["endCursor"])


def prior_lane(admin: str, scout: str, data_id: str) -> dict[str, Any]:
    """One earlier lane's ids, read back through the product from its ``DATA_ID`` alone.

    A lane that died halfway leaves its Unit, Unit Campaign, roster join and Scout Campaign behind, and its
    own record may never have been written — the only thing that survives is the ``DATA_ID`` its rows are
    named with.  This recovers the ids by the names :func:`lane_names` mints, so a later run of this lane
    can hand the sweeper the exact tokens for rows it did not write in this process.  Nothing here guesses
    at an id: a name that answers nothing is reported as gone.

    The roster read supplies the Scout Campaign ids while a join still stands, and those are what the
    active-join guard rule needs named exactly — a guard is deleted only with its own Campaign id, never by
    profile.  A lane whose Unit row is already gone has no roster read left, so the Scout's own
    ``listCampaignsByProfile`` is the read that recovers its Campaign: the naming template is this lane's, so
    a match is attribution, not a guess.
    """
    scout_campaigns = _lane_scout_campaigns(scout, data_id)
    unit = next(
        (row for row in _lane_units(admin) if str(row.get("displayName") or "") == f"Stage 3 Lane {data_id}"),
        None,
    )
    if unit is None:
        return {
            "dataId": data_id,
            "found": "no Unit answered this lane's display name",
            "scoutCampaignIds": scout_campaigns,
        }
    unit_id = str(unit["unitId"])
    campaigns = _items(api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": unit_id}))
    named = [
        _bare(row["unitCampaignId"])
        for row in campaigns
        if str(row.get("campaignName") or "") == f"Stage 3 Show & Sell {data_id}"
    ]
    joins = [
        _bare(row.get("campaignId"))
        for campaign in named
        for row in _items(api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": campaign}))
        if row.get("campaignId")
    ]
    return {
        "dataId": data_id,
        "unitId": _bare(unit_id),
        "unitCampaignIds": named,
        "scoutCampaignIds": sorted({join for join in joins + scout_campaigns if join}),
    }


def _lane_scout_campaigns(scout: str, data_id: str) -> list[str]:
    """The Scout Campaign ids one lane id names, read from the Scout's own campaign list."""
    return [
        _bare(row.get("campaignId"))
        for profile in api.my_profiles(scout)
        for row in (
            (
                _one(
                    api.gql(
                        scout,
                        stage2.STAGE_TWO_SUPPORT_DOCUMENTS["scoutCampaigns"],
                        {"profileId": str(profile["profileId"])},
                    )
                )
                or {}
            ).get("campaigns")
            or []
        )
        if str(row.get("campaignName") or "") == f"Stage 3 Scout {data_id}"
    ]


def _recover_standing_events(
    admin: str, scout: str, data_id: str, unit_campaign_ids: Sequence[str]
) -> tuple[list[Row], list[str]]:
    """Take back the Show & Sell rows one named earlier attempt left, through the shipped mutations.

    The sweeper never opens the Show & Sell table, so an event an earlier attempt wrote would survive every
    lane token — and while its signup row stays ``ACTIVE``, its ``ScoutCommitment`` projection stays ACTIVE
    too, which is what refuses the next lane's signup with "This Scout is already committed to another Show &
    Sell at these hours".  So a prior lane is torn down through the product first: signup, then slots, then
    the event, in the order the server's own guards require.

    The scope is exact on purpose.  ``data_id`` is a lane the operator named on the command line, and the only
    events this writes against are the ones whose ``locationName`` answers :func:`event_location` of that id —
    every id in the write set comes from that read, so an event merely sharing a Unit Campaign with a prior
    lane, or an event of another card, is enumerated and left rather than cancelled: a cancelled signup cannot
    be re-created in its slot.  Cancellation is legal only before ``startAt``, so an event that is already past
    that line is enumerated as retained rather than forced through a path the product refuses.  A signup whose
    row names a profile outside the fixture pool is left alone: it is not this lane's to cancel.
    """
    rows: list[Row] = []
    steps: list[str] = []
    fixture = {_bare(profile["profileId"]) for profile in api.my_profiles(scout)}
    for campaign in unit_campaign_ids:
        events = _items(
            api.gql(
                admin,
                stage3.STAGE_THREE_DOCUMENTS["showAndSells"],
                {"unitCampaignId": campaign, "page": {"limit": 50}},
            )
        )
        for event in events:
            event_id = str(event["showAndSellId"])
            status = str(event.get("status") or "")
            location = str(event.get("locationName") or "")
            if location != event_location(data_id):
                rows.append(
                    stage3.cleanup_row(
                        "§3.7.7 cancel an event an earlier attempt left",
                        f"{event_id} on Unit Campaign {campaign} answers location {location!r}, which is not lane "
                        f"{data_id}'s own event ({event_location(data_id)!r}): left standing, because a signup "
                        "cancelled on a near match cannot be re-created in its slot",
                        stage2.CLEANUP_BLOCKED,
                    )
                )
                continue
            if status not in {"DRAFT", "SCHEDULED"}:
                rows.append(
                    stage3.cleanup_row(
                        "§3.7.7 cancel an event an earlier attempt left",
                        f"{event_id} answers {status}: cancellation is legal only before the event starts, so this "
                        "row is enumerated as retained rather than removed",
                        stage2.CLEANUP_BLOCKED,
                    )
                )
                continue
            detail = _event_detail(admin, event_id)
            board = _items(
                api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSellSignups"], {"showAndSellId": event_id})
            )
            for index, slot in enumerate(detail.get("slots") or [], start=1):
                slot_id = str(slot["slotId"])
                signup = next(
                    (
                        row
                        for row in board
                        if str(row.get("slotId")) == slot_id
                        and str(row.get("status")) == "ACTIVE"
                        and _bare(row.get("profileId", "")) in fixture
                    ),
                    None,
                )
                if signup is not None:
                    step = f"cancel-signup-{slot_id}"
                    steps.append(step)
                    rows.append(
                        stage3.run_cleanup_step(
                            "§3.7.7 cancel a signup an earlier attempt left",
                            lambda slot_id=slot_id, step=step, event_id=event_id, profile=str(signup["profileId"]): (
                                _cancel_signup(scout, admin, data_id, event_id, slot_id, profile, step)
                            ),
                        )
                    )
                rows.append(
                    stage3.run_cleanup_step(
                        "§3.7.7 delete a slot an earlier attempt left",
                        lambda slot_id=slot_id, index=index, event_id=event_id: _delete_slot(
                            admin, data_id, event_id, slot_id, index
                        ),
                    )
                )
            rows.append(
                stage3.run_cleanup_step(
                    "§3.7.7 cancel an event an earlier attempt left",
                    lambda event_id=event_id: _cancel_event(
                        admin, data_id, event_id, f"Stage 3 lane cleanup {data_id}"
                    ),
                )
            )
    return rows, steps


def recover_standing_commitments(
    admin: str,
    scout: str,
    data_id: str,
    prior: Sequence[str] = (),
    protected: Sequence[str] = (),
) -> tuple[list[Row], list[str], list[dict[str, Any]]]:
    """Give back the ACTIVE ``ScoutCommitment`` rows this run is authorized to clear, before it signs up.

    The order is not a preference, it is the product's guard: while a signup row is ``ACTIVE`` its
    ``ScoutCommitment`` projection is ACTIVE too, and ``signupScoutForShowAndSellSlot`` refuses the next lane
    with "This Scout is already committed to another Show & Sell at these hours".  A lane whose Unit row the
    sweeper already took cannot be reached through its Unit Campaign — ``showAndSells`` and
    ``showAndSellSignups`` are keyed on rows that no longer exist — so the read that finds the orphan is the
    Scout's own ``myScoutCommitments``, and the write that clears it is ``cancelShowAndSellSignup``, which
    authorizes a non-Kernel caller by profile access alone and asks nothing about the Unit or the roster.
    Both are shipped paths: nothing here reaches for the table.

    The gate is authorization, and it is exact.  Every lane on this stack signs in as the same four fixture
    identities, and two lanes of this card can be in flight at once on different checkouts, so an ACTIVE
    commitment is never automatically this run's to cancel and neither is one whose event merely starts with
    this card's prefix.  Each commitment is read through ``showAndSell`` and cancelled only when its
    ``locationName`` is exactly :func:`event_location` of this lane's id or of an id named with
    ``--sweep-prior``; :func:`cancellable_locations` also drops the ``protected`` ids — the canary — so the
    lane this record exists to protect cannot be written against either.  Anything else is enumerated and
    left: a cancelled signup can never be created again in the same slot
    (``src/handlers/unit_operations.py``: "a cancelled signup stays history. Choose another slot."), so
    cancelling another run's place is not a cleanup, it is a row nobody can put back.

    Cancellation markers this pass mints carry *this* lane's id, so they go back to the sweeper as this
    lane's own tokens.
    """
    rows: list[Row] = []
    steps: list[str] = []
    locations = cancellable_locations(data_id, prior, protected)
    allowed = ", ".join(sorted(locations.values())) or "none"
    for position, commitment in enumerate(_standing_commitments(scout), start=1):
        event_id = str(commitment.get("showAndSellId") or "")
        slot_id = str(commitment.get("slotId") or "")
        if str(commitment.get("status") or "") != "ACTIVE":
            continue
        where = f"event {event_id} slot {slot_id} profile {commitment.get('profileId')}"
        try:
            detail = _event_detail(admin, event_id)
        except api.GraphQLError as exc:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read back the Scout's ACTIVE commitments",
                    f"{where}: the event read answered {exc.args[:1]!r}, so this row cannot be attributed to a "
                    f"lane this run may write against ({allowed}) and nothing is written against it",
                    stage2.CLEANUP_BLOCKED,
                )
            )
            continue
        location = str(detail.get("locationName") or "")
        owner = locations.get(location)
        if owner is None:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read back the Scout's ACTIVE commitments",
                    f"{where} answers ACTIVE on an event named {location!r}, the event of no lane this run is "
                    f"authorized to write against ({allowed}): left standing, because a cancelled signup cannot "
                    "be re-created in the same slot",
                )
            )
            continue
        step = f"recover-commitment-{position}"
        steps.append(step)
        row = stage3.run_cleanup_step(
            "§3.7.7 give back a commitment an earlier attempt of a named lane left",
            lambda event_id=event_id, slot_id=slot_id, step=step, commitment=commitment: _cancel_signup(
                scout,
                admin,
                data_id,
                event_id,
                slot_id,
                str(commitment["profileId"]),
                step,
            ),
        )
        row["summary"] = (
            f"lane {owner}'s event {event_id} ({location!r}) slot {slot_id}: commitment answered ACTIVE at "
            f"{commitment.get('startAt')}..{commitment.get('endAt')} — {row['summary']}"
        )
        rows.append(row)
    still_active = _active_commitments(scout)
    ours: list[str] = []
    for row in still_active:
        try:
            location = str(_event_detail(admin, str(row.get("showAndSellId") or "")).get("locationName") or "")
        except api.GraphQLError as exc:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read back the Scout's commitment set",
                    f"event {row.get('showAndSellId')} slot {row.get('slotId')} answers ACTIVE and its event read "
                    f"answered {exc.args[:1]!r}, so it cannot be attributed and nothing is written against it",
                    stage2.CLEANUP_BLOCKED,
                )
            )
            continue
        if location in locations:
            ours.append(f"lane {locations[location]}: {row.get('showAndSellId')}/{row.get('slotId')}")
    rows.append(
        stage3.cleanup_row(
            "§3.7.7 read back the Scout's commitment set",
            f"myScoutCommitments answers {len(still_active)} ACTIVE commitment(s) after this pass "
            f"({len(steps)} cancellation(s) sent): "
            + "; ".join(
                f"{row.get('showAndSellId')}/{row.get('slotId')} on {row.get('startAt')} (profile {row.get('profileId')})"
                for row in still_active
            )
            + f"; {len(ours)} of them belong to a lane this run is authorized to clear"
            + (
                f" ({'; '.join(ours)}) — its signup is still standing, so this run did not finish the job"
                if ours
                else ""
            ),
            stage2.CLEANUP_OBSERVED if not ours else stage2.CLEANUP_BLOCKED,
        )
    )
    return rows, steps, still_active


def _lane_profile(scout: str, busy: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The profile this lane signs its Scout up on: the first one holding no ACTIVE commitment.

    The overlap guard is per profile, and other cards' lanes run against the same fixture identity on other
    profiles of that identity.  Moving this lane to a free profile is the whole answer to that collision: the
    other run's place is not this lane's to cancel, and a cancelled signup cannot be re-created in its slot.
    """
    taken = {str(row.get("profileId")) for row in busy}
    profiles = api.my_profiles(scout)
    return next((row for row in profiles if str(row["profileId"]) not in taken), profiles[0])


def sweep_prior(
    admin: str,
    scout: str,
    data_ids: Sequence[str],
    transport: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
) -> list[Row]:
    """Take back what an earlier attempt of this lane left, through the same sanctioned sweeper.

    Each prior lane is censused before it is swept, for the same reason the lane under test is: after the
    sweeper deletes the Unit and Unit Campaign rows, the product reads that stand in for the three unreadable
    tables answer ``NOT_FOUND`` and count nothing.  Its Show & Sell rows go through the product first, because
    no sweeper rule reaches the Show & Sell table at all.
    """
    rows: list[Row] = []
    for data_id in data_ids:
        found = prior_lane(admin, scout, data_id)
        standing = found.get("unitId") or found.get("unitCampaignIds") or found.get("scoutCampaignIds")
        if not standing:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 sweep an earlier attempt",
                    f"{data_id}: nothing to remove — {found.get('found', 'no row answered this naming template')}",
                )
            )
            continue
        recovery, steps = _recover_standing_events(admin, scout, data_id, found.get("unitCampaignIds") or [])
        rows += recovery
        # A Scout Campaign row lives in the ``campaigns`` table, which the sweeper never opens, so the
        # shipped mutation is the only supported path for it.  Taking it through the product also means the
        # sweep's ``campaign`` token names a Campaign whose guard row is the last thing of this lane's still
        # standing, which is the case the guard rule was written for.
        removed = [
            campaign for campaign in found.get("scoutCampaignIds") or [] if _delete_scout_campaign(scout, campaign)
        ]
        tokens = [
            *([f"unit={found['unitId']}"] if found.get("unitId") else []),
            *(f"unit-campaign={campaign}" for campaign in found.get("unitCampaignIds") or []),
            *(f"campaign={campaign}" for campaign in found.get("scoutCampaignIds") or []),
            *(f"idem={stage3.idempotency_key_for(operation, data_id, step)}" for operation, step in LANE_MARKER_KEYS),
            *(f"idem={stage3.idempotency_key_for('cancelShowAndSellSignup', data_id, step)}" for step in steps),
        ]
        census = stage3.stage_three_residue_census(
            transport, found.get("unitCampaignIds") or [], found.get("scoutCampaignIds") or []
        )
        row, _detail = sweep_row(tokens, census)
        row["summary"] = (
            f"{data_id} ({len(tokens)} token(s); {len(removed)} Scout Campaign row(s) taken by deleteCampaign first): "
            f"{row['summary']}"
        )
        rows.append(row)
    return rows


def show_and_sell_residue(admin: str, lane: Mapping[str, Any], written: Mapping[str, Any]) -> dict[str, Any]:
    """What this lane leaves on the Show & Sell table, read in the window where that read still answers.

    Amendment C requires the retained class enumerated with counts and key shapes, and this is the one table
    the residue census cannot answer: ``scripts/qa_fixture.py`` never opens ``show_and_sells`` (its
    ``SWEEP_TABLES`` map stops at the six lane tables), so no sweep line will ever name a row here.  The read
    has to run before the sweep the same way the three blocked tables' census does, because the sweep deletes
    the Unit and the Unit Admin's grant, and a Kernel-scoped read of an event whose Unit is gone answers
    nothing at all.

    The key shapes are the model's own (``src/utils/show_and_sell_models.py``): the event aggregate at
    ``SHOW_AND_SELL#<showAndSellId>/METADATA``, a signup at ``SHOW_AND_SELL#<showAndSellId>/SIGNUP#<slotId>#<profileId>``
    and a slot at ``SHOW_AND_SELL#<showAndSellId>/SLOT#<slotId>``.  Slots are reported as the teardown
    removed them, so the residue is the event row and the signup row, and this function counts them rather
    than asserting them.
    """
    table = stage3.show_and_sells_table()
    event_id = str(written.get("showAndSellId") or "")
    if not event_id:
        return {
            "table": table,
            "eventRows": [],
            "signupRows": [],
            "note": f"{table}: this lane wrote no event, so it leaves no aggregate or signup row of these shapes",
        }
    detail = _event_detail(admin, event_id)
    signups = _items(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSellSignups"], {"showAndSellId": event_id}))
    return {
        "table": table,
        "partitionKey": f"SHOW_AND_SELL#{event_id}",
        "eventRows": [
            {
                "sk": "METADATA",
                "status": str(detail.get("status") or ""),
                "startAt": str(detail.get("startAt") or ""),
                "version": detail.get("version"),
            }
        ],
        "signupRows": [
            {"sk": f"SIGNUP#{row.get('slotId')}#{row.get('profileId')}", "status": str(row.get("status") or "")}
            for row in signups
        ],
        "slotRows": [str(slot.get("slotId")) for slot in detail.get("slots") or []],
        "note": (
            f"{table}: {len(signups) + 1} row(s) under {event_id} answer this lane — one METADATA row and "
            f"{len(signups)} SIGNUP row(s); no shipped path deletes either, and the sweeper's table list "
            "never opens this table, so they are enumerated here rather than reported clean"
        ),
    }


def retained_commitment_rows(scout: str, event_ids: Sequence[str]) -> tuple[list[Row], int]:
    """The signup projections of this lane's events that still answer once every sweep has run.

    This is the post-teardown half of the same count.  ``myScoutCommitments`` is keyed on the Scout's own
    profile, so it answers after the sweeper took the Unit and Unit Campaign rows every Kernel-side read
    needs — which is what makes it the read that proves the signup row is still standing instead of merely
    assumed to be.
    """
    named = {str(value) for value in event_ids if value}
    rows: list[Row] = []
    if not named:
        return rows, 0
    for commitment in _standing_commitments(scout):
        event_id = str(commitment.get("showAndSellId") or "")
        if event_id in named:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read the retained Show & Sell rows back after every sweep",
                    f"myScoutCommitments still answers {stage3.show_and_sells_table()} "
                    f"SIGNUP#{commitment.get('slotId')}#{commitment.get('profileId')} of event {event_id} as "
                    f"{commitment.get('status')}, after the teardown and both sweeps ran",
                )
            )
    return rows, len(rows)


GUARD_SORT_KEY = "MEMBERSHIP_GUARD"
METADATA_SORT_KEY = "METADATA"

#: The one disposition a guard key can end with, and every one of them is a read rather than a guess.  This
#: pass removes nothing, so the only thing it can decide is what the table answers for that key and whose row
#: it is when a row is there.
GUARD_ABSENT = "verified-absent"
GUARD_LIVE_JOIN = "live-join"
GUARD_LIVE_SCOUT_CAMPAIGN = "live-scout-campaign"
GUARD_OTHER_TENANT = "other-tenant"
GUARD_NOT_THIS_CARD = "not-this-card"
GUARD_CARD_RESIDUE = "card-residue"
GUARD_UNPROVEN = "unproven-dead"
GUARD_OWNER_UNPROVEN = "unproven-owner"
GUARD_UNREADABLE = "unreadable"

#: A key this card's run named cannot pass on these four answers: residue this card owns that still stands, a
#: row nobody can prove dead, a standing row whose owner nobody can confirm, and a read that was refused
#: outright.  ``other-tenant`` is not on this list because it is now a proven answer: the base-table read that
#: names the owner succeeded and that owner is not fixture data, which disposes of the key independently of
#: anything this card did.
GUARD_NAMED_FAILURES = (GUARD_CARD_RESIDUE, GUARD_UNPROVEN, GUARD_OWNER_UNPROVEN, GUARD_UNREADABLE)

#: The name templates this card's own runs write into the records they create.  A membership-guard row
#: carries no lane id, so an already-orphaned guard is attributed through the product's own Profile row for
#: the guarded Scout: that row's ``sellerName`` names the run that made it ("Avery w168qa"), and these are
#: the labels this card's runners mint.  ``--claim-label`` extends the set for a run whose template is not
#: listed here, and the label that matched is recorded with every key the pass names.  A label is never
#: sufficient on its own: :func:`guard_disposition` asks who owns the Profile first.
CARD_CLAIM_LABELS: tuple[str, ...] = ("w168qa", "w168qb", "w168lane", "w168can", "w168probe")


def _table_named(tool: Any, label: str) -> str:
    """The dev physical name of one of this stack's tables, derived from the sweeper's own map.

    ``scripts/qa_fixture.py`` is the only place the lane reads physical names from, and
    ``tofu/application/modules/dynamodb/main.tf`` builds every one of them the same way
    (``${var.name_prefix}-<table>${local.table_suffix}``); re-declaring a name here is how a read drifts onto
    a table that does not exist, so the suffix comes off a name the sweeper already publishes.
    """
    unit_table = tool.SWEEP_TABLES["units"][0]
    name = unit_table.replace("-units-", f"-{label}-")
    if name == unit_table:
        raise AssertionError(f"the sweeper's table map cannot name {label!r}: it answers {unit_table}")
    return name


def _refusal(table: str, exc: BaseException) -> str:
    """A read this identity was not allowed to make, in the shape a record and a reviewer can both use.

    A raw botocore message is two sentences of ARN; what the record has to carry is the table, the action and
    the fact that it is an authorization answer rather than an empty result.  "No rows" and "no permission"
    are different findings, and collapsing them is how a blocked table comes to look clean.
    """
    text = " ".join(str(exc).split())
    called = re.search(r"when calling the (\w+) operation", text)
    perform = re.search(r"not authorized to perform: ([\w:]+)", text)
    if called and perform:
        return f"{table}: {called.group(1)} is not granted to this identity ({perform.group(1)} denied)"
    return f"{table}: {type(exc).__name__}: {text}"


def _read_item(client: Any, tool: Any, table: str, key: Mapping[str, str]) -> tuple[dict[str, str], str]:
    """One item by its exact key, strongly consistent: the whole of what this pass asks of DynamoDB.

    ``GetItem`` with ``ConsistentRead`` is the only write-adjacent shape that cannot reach a row the caller
    did not name — a ``Query`` or ``Scan`` on a prefix, or the sweeper's token-matched delete, can.  The pair
    ``(item, error)`` keeps the two answers that look identical apart: an empty item with no error means the
    table says that key is not answered, and an empty item with an error means this identity was not allowed
    to know.  Every guard read in this module goes through here.
    """
    try:
        page = client.get_item(
            TableName=table,
            Key={name: {"S": value} for name, value in key.items()},
            ConsistentRead=True,
        )
    except Exception as exc:  # noqa: BLE001 - a refused read is a finding, not a crash
        return {}, _refusal(table, exc)
    item = page.get("Item")
    return (tool._strings(item), "") if item else ({}, "")


def _guard_population(client: Any, tool: Any, table: str) -> list[str]:
    """Every membership-guard row on the Unit Campaign table, as the bare Scout Campaign id it guards.

    The population, not a hand-written list: the three guards this card's first cleanup report left
    ``UNKNOWN`` were found because a ``profile=`` token happened to reach them, and the same profile token
    cannot say which Scout Campaign is joined (``scripts/qa_fixture.py``: "one profile holds a guard per
    Campaign").  Reading the shape out of the table is what makes the disposition complete — and it finds the
    guards no report ever named.  This is a read of a table ``kernelworx-qa-ue1-dev`` is granted
    ``dynamodb:Scan`` on; the five keys the card has to answer for are still verified one at a time by
    :func:`_read_item`, and this scan only enumerates what is left standing around them.
    """
    found: list[str] = []
    scan_kw: dict[str, Any] = {
        "TableName": table,
        "FilterExpression": "sk = :sk",
        "ExpressionAttributeValues": {":sk": {"S": GUARD_SORT_KEY}},
    }
    while True:
        page = client.scan(**scan_kw)
        for item in page.get("Items", []):
            flat = tool._strings(item)
            campaign = flat.get("campaignId") or flat.get("pk", "")
            found.append(_bare(campaign).removeprefix("CAMPAIGN#"))
        token = page.get("LastEvaluatedKey")
        if not token:
            return sorted(set(found))
        scan_kw["ExclusiveStartKey"] = token


def _unproven_profile(why: str) -> dict[str, Any]:
    """The Profile lookup's answer when nothing on it can name an owner."""
    return {
        "profileRow": {},
        "profileLocated": 0,
        "profileConfirmed": False,
        "profileUnprovenWhy": why,
        "profileError": "",
    }


def _profile_row(client: Any, tool: Any, table: str, profile_key: str) -> dict[str, Any]:
    """The Profile row one exact ``profileId`` belongs to, located the way the product locates it.

    ``profiles`` is keyed ``ownerAccountId``/``profileId``, so a profile id on its own is only reachable
    through ``profileId-index`` — the same index ``unit_campaign_models.seller_display_name`` uses to answer
    this one question — and an index is eventually consistent, so the row is read again from the base table by
    the pair the index names.  Both reads are keyed by the id the guard itself carries: this never enumerates
    the table.

    What comes back is the lookup's evidence, not just a row, because the projection alone cannot answer who
    owns a Profile: ``src/handlers/public_orders_offer.py`` returns its profile only when
    ``_consistent_profile`` — a strongly consistent ``GetItem`` of ``{ownerAccountId, profileId}`` — answers an
    item, and reports the offer unavailable when the index projects a row the base table no longer answers.
    That same rule is what ``profileConfirmed`` records here: an owner counts only when the base-table read
    confirms it, so a transferred or deleted Profile whose index entry has not caught up can never be the
    evidence an attribution rests on.  The four ways no owner is provable are kept apart by
    ``profileUnprovenWhy``, and a refused read is kept apart from all four by ``profileError``.
    """
    evidence = _unproven_profile("")
    try:
        page = client.query(
            TableName=table,
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :profile_id",
            ExpressionAttributeValues={":profile_id": {"S": profile_key}},
        )
    except Exception as exc:  # noqa: BLE001 - a refused attribution read refuses the attribution
        evidence["profileError"] = _refusal(table, exc)
        return evidence
    located = [tool._strings(item) for item in page.get("Items", [])]
    evidence["profileLocated"] = len(located)
    if not located:
        evidence["profileUnprovenWhy"] = "the profileId-index projection answers no row for it"
        return evidence
    owners = list(dict.fromkeys(str(item.get("ownerAccountId", "")) for item in located if item.get("ownerAccountId")))
    if not owners:
        evidence["profileUnprovenWhy"] = (
            f"the {len(located)} projection(s) carry no ownerAccountId, so the base-table key that would "
            "confirm the row cannot be built from them"
        )
        return evidence
    confirmed: list[dict[str, str]] = []
    for owner in owners:
        item, error = _read_item(client, tool, table, {"ownerAccountId": owner, "profileId": profile_key})
        if error:
            evidence["profileError"] = error
            return evidence
        if item:
            confirmed.append(item)
    if not confirmed:
        evidence["profileUnprovenWhy"] = (
            f"the index still projects {len(located)} row(s) for it and none of the base-table keys they name "
            "answers an item, which is the stale projection a transfer or delete leaves behind"
        )
        return evidence
    if len(confirmed) > 1:
        evidence["profileUnprovenWhy"] = (
            f"{len(confirmed)} base-table rows answer the same profileId, so which account owns it is genuinely "
            "ambiguous — the same ambiguity public_orders_offer refuses to guess at"
        )
        return evidence
    evidence["profileRow"] = confirmed[0]
    evidence["profileConfirmed"] = True
    return evidence


def _fixture_allowlist(tool: Any) -> dict[str, str]:
    """``sub`` -> address for the identities ``scripts/qa_fixture.py`` treats as its own, and nobody else's.

    This is the sweeper's own narrowing, line for line: it takes the four configured fixture addresses from
    ``emails()`` and keeps only the ``sub`` each one has on the pool (``qa_fixture.py``, the ``sweep``
    branch).  Reading the user pool instead would be wrong in the dangerous direction — the dev pool answers
    26 users on this identity while the fixture allowlist names 4, so every ordinary dev account would read
    as "fixture data" and a Profile owned by a real tenant would qualify for a lane's cleanup.
    """
    have = tool.pool_users(tool.cip())
    identities: dict[str, str] = {}
    for address in tool.emails().values():
        user = have.get(address)
        sub = tool._attrs(user).get("sub") if user else ""
        if sub:
            identities[sub] = address
    return identities


def guard_facts(
    client: Any,
    tool: Any,
    table: str,
    campaigns_table: str,
    profiles_table: str,
    campaign_id: str,
    identities: Mapping[str, str],
    labels: Sequence[str],
) -> dict[str, Any]:
    """What one guard key answers right now, each read by its exact key and none of them a write.

    Four aggregates decide everything that follows, and each is the product's own read:

    * the guard row itself, by ``{pk, sk}`` on the Unit Campaign table, strongly consistent;
    * the Unit Campaign the guard declares ``ACTIVE``, by its ``METADATA`` row — the same row a sale's
      origin reads before it trusts a join;
    * the Scout Campaign, on ``campaigns`` by ``{profileId, campaignId}``, which is the base-row key
      ``unit_campaign_models.campaign_latest_link_action`` writes and ``roster_display`` batch-reads.  The
      ``METADATA`` row the earlier revision of this pass looked for beside the guard is not a Scout Campaign:
      that table holds Unit Campaign aggregates, and no Scout Campaign partition there carries one, so that
      test was true of every guard on the table and pruned nothing;
    * the Profile row the guard names, which is the only thing on the row that says who made it — and only when
      the strongly consistent base-table read confirms it, because an ``profileId-index`` projection can keep
      naming an owner a transfer or a delete has already taken away.
    """
    key = {"pk": f"SCOUT_CAMPAIGN#CAMPAIGN#{campaign_id}", "sk": GUARD_SORT_KEY}
    guard, guard_error = _read_item(client, tool, table, key)
    profile_key = guard.get("profileId", "")
    evidence = (
        _profile_row(client, tool, profiles_table, profile_key)
        if profile_key
        else _unproven_profile("the guard row carries no profileId, so no Profile row can be named for it")
    )
    profile = evidence["profileRow"]
    owner = _bare(profile.get("ownerAccountId", ""))
    active = _bare(guard.get("activeUnitCampaignId", ""))
    standing, standing_error = (
        _read_item(client, tool, table, {"pk": f"UNIT_CAMPAIGN#{active}", "sk": METADATA_SORT_KEY})
        if active
        else ({}, "")
    )
    scout, scout_error = ({}, "")
    if guard:
        if profile_key:
            scout, scout_error = _read_item(
                client,
                tool,
                campaigns_table,
                {"profileId": profile_key, "campaignId": guard.get("campaignId") or f"CAMPAIGN#{campaign_id}"},
            )
        else:
            scout_error = f"{campaigns_table}: the guard row carries no profileId, so the base-row key cannot be built"
    return {
        "campaignId": campaign_id,
        "guardKey": f"{key['pk']}/{key['sk']}",
        "guardPresent": bool(guard),
        "guardError": guard_error,
        "profileId": _bare(profile_key),
        "sellerName": str(profile.get("sellerName", "")),
        "ownerAddress": identities.get(owner, ""),
        "ownerInFixtureAllowlist": bool(owner) and owner in identities,
        "profileLocated": int(evidence["profileLocated"]),
        "profileConfirmed": bool(evidence["profileConfirmed"]),
        "profileUnprovenWhy": str(evidence["profileUnprovenWhy"]),
        "profileError": str(evidence["profileError"]),
        "activeUnitCampaignId": active,
        "activeUnitCampaignName": str(standing.get("campaignName", "")),
        "activeJoinStands": bool(standing),
        "activeJoinError": standing_error,
        "scoutCampaignStands": bool(scout),
        "scoutCampaignError": scout_error,
        "claimLabel": next((name for name in labels if name and name in str(profile.get("sellerName", ""))), ""),
        "updatedAt": str(guard.get("updatedAt", "")),
    }


def guard_disposition(fact: Mapping[str, Any]) -> tuple[str, str]:
    """What this card may say about one guard key, and in which order the facts have to be asked.

    Ownership is settled before anything is attributed to this card, and the fixture allowlist is what
    settles it: a Scout whose Profile belongs to an account the sanctioned sweeper does not recognize is a
    real tenant's row whatever its ``sellerName`` happens to contain, so the label test runs *after* it and
    can never be the only reason a row is called this card's.  Nothing here decides a delete, so a state that
    cannot be proved is reported as unproven instead of being taken on the strength of a substring.  Ownership
    counts only when the base-table read confirms it, for the reason the product gives at
    ``src/handlers/public_orders_offer.py:_consistent_profile`` — an eventually consistent index projection
    cannot show who owns a Profile right now — so "not this card's" is never inferred from an owner nobody can
    name.

    * :data:`GUARD_UNREADABLE` — the read of the key itself was refused, so the key has no answer.
    * :data:`GUARD_ABSENT` — a strongly consistent ``GetItem`` of the exact key answers no item, which is the
      read-back the disposition asks for.
    * :data:`GUARD_OWNER_UNPROVEN` — no confirmed owner for the Profile this guard names: the Profile read was
      refused, the index answers no row, the row the index names no longer answers the base table, several base
      rows answer one ``profileId``, or the guard carries no ``profileId`` at all.  Nothing may be attributed to
      such a row in either direction.
    * :data:`GUARD_OTHER_TENANT` — a Profile the base table confirms, owned by an account that is not a fixture
      identity.
    * :data:`GUARD_LIVE_JOIN` — the guard declares an ACTIVE join whose Unit Campaign still answers its
      metadata row: a live membership, and deleting the row behind it would leave an ``ACTIVE`` roster row
      with nothing enforcing it.
    * :data:`GUARD_NOT_THIS_CARD` — a fixture Scout's row whose confirmed Profile names another run's label, or
      no label at all.
    * :data:`GUARD_LIVE_SCOUT_CAMPAIGN` — the Scout Campaign stands on the product's own base-row read, so the
      guard is the lock of a live Campaign, not residue.
    * :data:`GUARD_UNPROVEN` — every other read says dead, and the one read that would prove it is denied to
      this identity, so the row cannot be certified dead by anyone holding these credentials.
    * :data:`GUARD_CARD_RESIDUE` — fixture-owned, this card's label, no live join and no Scout Campaign:
      this card's own residue, which it must dispose of through the sanctioned sweeper rather than here.
    """
    if fact["guardError"]:
        return GUARD_UNREADABLE, f"the read of {fact['guardKey']} was refused — {fact['guardError']}"
    if not fact["guardPresent"]:
        return GUARD_ABSENT, f"a strongly consistent GetItem of {fact['guardKey']} answers no item"
    named_profile = fact["profileId"] or "none on the guard"
    if fact["profileError"]:
        return GUARD_OWNER_UNPROVEN, (
            f"the Profile {named_profile} could not be read — {fact['profileError']}; an owner this identity was "
            "refused is not an owner, and a row with no owner is not another tenant's"
        )
    if not fact["profileConfirmed"]:
        return GUARD_OWNER_UNPROVEN, (
            f"no base-table row answers the Profile {named_profile} — {fact['profileUnprovenWhy']} — so this "
            "guard has no proven owner in either direction, and the pass has no evidence with which to call it "
            "another tenant's or this card's"
        )
    if not fact["ownerInFixtureAllowlist"]:
        return GUARD_OTHER_TENANT, (
            f"the Profile row {fact['profileId']} names {fact['sellerName'] or 'no sellerName'} and the base table "
            f"confirms it as {fact['ownerAddress'] or 'an account that is not on the fixture allowlist'}, which "
            "scripts/qa_fixture.py does not treat as fixture data"
        )
    if fact["activeJoinStands"]:
        return GUARD_LIVE_JOIN, (
            f"the guard declares an ACTIVE join on Unit Campaign {fact['activeUnitCampaignId']} "
            f"({fact['activeUnitCampaignName'] or 'unnamed'}), which still answers its {METADATA_SORT_KEY} row"
        )
    if fact["activeJoinError"]:
        return GUARD_UNPROVEN, (
            f"the ACTIVE join on {fact['activeUnitCampaignId']} could not be read — {fact['activeJoinError']}"
        )
    if not fact["claimLabel"]:
        return GUARD_NOT_THIS_CARD, (
            f"the Profile row for {fact['ownerAddress']} names {fact['sellerName'] or 'no sellerName at all'}, "
            f"which is not one of this card's lane labels ({', '.join(CARD_CLAIM_LABELS)})"
        )
    if fact["scoutCampaignStands"]:
        return GUARD_LIVE_SCOUT_CAMPAIGN, (
            f"the Scout Campaign {fact['campaignId']} still answers the base-row read the product makes on its "
            "Campaigns table, so this guard is a live Campaign's lock"
        )
    if fact["scoutCampaignError"]:
        return GUARD_UNPROVEN, (
            f"the Scout Campaign read the product makes could not run — {fact['scoutCampaignError']}, so no "
            "credential this pass holds can prove this Campaign is gone"
        )
    return GUARD_CARD_RESIDUE, (
        f"owned by the fixture identity {fact['ownerAddress']} on label {fact['claimLabel']!r}, with no ACTIVE "
        f"join standing ({fact['activeUnitCampaignId'] or 'none named'}) and no Scout Campaign row at "
        f"{fact['campaignId']}: this card's residue, to be taken by scripts/qa_fixture.py sweep with "
        f"campaign={fact['campaignId']} named, not by this pass"
    )


def verify_guard_residue(
    campaign_ids: Sequence[str] = (), labels: Sequence[str] = CARD_CLAIM_LABELS
) -> tuple[list[Row], dict[str, Any]]:
    """Say, key by key, what every membership-guard row on the table is — and remove none of them.

    The card's first cleanup report left three guard rows ``UNKNOWN``: the sweep reached them with a
    ``profile=`` token, and a profile token cannot say which of a Scout's Scout Campaigns is joined, so the
    sweeper refused to attribute them and failed closed.  This pass is the keyed answer to that, and it is
    read-only on purpose.  Pointing the sweeper at a ``campaign=`` id deletes scoped rows on three tables and
    the guard on a fourth, on the strength of the id alone, and a guard row carries no lane id — so a pass
    that mutated could take another lane's live join on a name match, and nothing it deleted would come back.
    What it does instead:

    * reads the guard population, so the residue is enumerated rather than recalled from a report;
    * for every key, and for each id named on the command line, does a strongly consistent ``GetItem`` of
      that exact key — the five ids this card owes are proven absent by a read, not by a sweep line;
    * for a key that is answered, decides ownership from the fixture allowlist before any label match, and only
      off a Profile row the base table confirms — a refused Profile read, a missing Profile, or an index
      projection whose base row is gone settles nothing and is reported as unproven;
    * reports every key's state with the reason, and fails a named key that is still this card's residue, whose
      owner cannot be confirmed, whose deadness cannot be proved, or whose read was refused, rather than passing
      it on the strength of an owner nobody can name.
    """
    tool = _fixture_tool()
    client = tool.ddb()
    table = _table_named(tool, "unit-campaigns")
    campaigns_table = _table_named(tool, "campaigns")
    profiles_table = _table_named(tool, "profiles")
    identities = _fixture_allowlist(tool)
    named = sorted({_bare(value) for value in campaign_ids if _bare(value)})
    keys = sorted({*_guard_population(client, tool, table), *named})
    facts = [guard_facts(client, tool, table, campaigns_table, profiles_table, key, identities, labels) for key in keys]
    dispositions = {str(fact["campaignId"]): guard_disposition(fact) for fact in facts}
    states = {key: state for key, (state, _reason) in dispositions.items()}
    answered = sum(1 for fact in facts if fact["guardPresent"])
    detail: dict[str, Any] = {
        "table": table,
        "campaignsTable": campaigns_table,
        "profilesTable": profiles_table,
        "guards": len(facts),
        "guardRows": answered,
        "claimLabels": list(labels),
        "fixtureAllowlist": sorted(identities.values()),
        "namedKeys": named,
        "verifiedAbsent": sorted(key for key, state in states.items() if state == GUARD_ABSENT),
        "namedAbsent": [key for key in named if states.get(key) == GUARD_ABSENT],
        "byState": {
            state: sorted(key for key, found in states.items() if found == state)
            for state in sorted(set(states.values()))
        },
        "keys": [
            {
                "campaignId": fact["campaignId"],
                "guardKey": fact["guardKey"],
                "state": states[fact["campaignId"]],
                "reason": dispositions[fact["campaignId"]][1],
                "named": fact["campaignId"] in named,
                **{
                    name: fact[name]
                    for name in (
                        "guardPresent",
                        "guardError",
                        "profileId",
                        "sellerName",
                        "ownerAddress",
                        "ownerInFixtureAllowlist",
                        "profileLocated",
                        "profileConfirmed",
                        "profileUnprovenWhy",
                        "profileError",
                        "claimLabel",
                        "activeUnitCampaignId",
                        "activeJoinStands",
                        "activeJoinError",
                        "scoutCampaignStands",
                        "scoutCampaignError",
                        "updatedAt",
                    )
                },
            }
            for fact in facts
        ],
    }

    rows: list[Row] = []
    acceptance = "§3.7.7 verify by key that every membership guard this card named is gone"
    for key in named:
        state, reason = dispositions.get(key, ("missing-key", "no read answered this key at all"))
        result = (
            stage2.CLEANUP_FAILED
            if state in GUARD_NAMED_FAILURES or state == "missing-key"
            else stage2.CLEANUP_OBSERVED
        )
        rows.append(stage3.cleanup_row(acceptance, f"{GUARD_SORT_KEY} {key}: {state} — {reason}", result))

    def count_of(state: str) -> int:
        return sum(1 for found in states.values() if found == state)

    rows.append(
        stage3.cleanup_row(
            "§3.7.7 enumerate the guard rows that are still standing, with the reason for each",
            f"{table} answers {answered} {GUARD_SORT_KEY} row(s) across {len(facts)} key(s) examined; of the "
            f"{len(named)} key(s) this card named, {len(detail['namedAbsent'])} answer no row at all and "
            f"{len(named) - len(detail['namedAbsent'])} are answered — the standing rows are "
            f"{count_of(GUARD_LIVE_JOIN)} guarding a live ACTIVE join, "
            f"{count_of(GUARD_OTHER_TENANT)} with a confirmed owner outside the fixture "
            f"allowlist, {count_of(GUARD_NOT_THIS_CARD)} written by "
            f"another run, {count_of(GUARD_LIVE_SCOUT_CAMPAIGN)} on a "
            f"Scout Campaign that still stands, {count_of(GUARD_OWNER_UNPROVEN)} whose owner no base-table read "
            f"confirms, {count_of(GUARD_UNPROVEN)} "
            f"nobody here can prove dead, and "
            f"{count_of(GUARD_CARD_RESIDUE)} this card's own residue",
            stage2.CLEANUP_OBSERVED,
        )
    )
    unproven = [str(fact["scoutCampaignError"]) for fact in facts if fact["scoutCampaignError"]]
    if unproven:
        rows.append(
            stage3.cleanup_row(
                "§3.7.7 read the Scout Campaign the way the product reads it",
                f"the base-row read this disposition needs on {campaigns_table} is refused: {unproven[0]}; it was "
                f"attempted on {len(unproven)} key(s) and decides "
                f"{sum(1 for state in states.values() if state == GUARD_UNPROVEN)} key(s) as unproven rather "
                "than dead, and it is the second reason this pass removes nothing — a row nobody can prove dead "
                "is a row nobody should delete",
                stage2.CLEANUP_BLOCKED,
            )
        )
    return rows, detail


def verify_guards(
    out_dir: Path, campaign_ids: Sequence[str] = (), labels: Sequence[str] = CARD_CLAIM_LABELS
) -> dict[str, Any]:
    """Run the read-only guard verification on its own, and write a record that carries it.

    A separate mode rather than a step of the lane, because this pass creates nothing and tears nothing down:
    it answers a question about rows earlier attempts of this card left behind, and re-running the whole lane
    to answer it would write more residue.  The record is written from a ``finally`` for the same reason the
    lane writes its own: a pass that was refused partway still has to say which keys it touched and which
    reads it was not allowed to make.
    """
    lane_id = new_data_id("w168guards")
    record: dict[str, Any] = {
        "dataId": lane_id,
        "mode": "guard-verify",
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    cleanup: list[Row] = []
    try:
        rows, detail = verify_guard_residue(campaign_ids, labels)
        record["guardResidue"] = detail
        cleanup.extend(rows)
    except Exception as exc:  # noqa: BLE001 - the record has to survive a failing pass to report one
        record["error"] = f"{type(exc).__name__}: {exc}"
        cleanup.append(
            stage3.cleanup_row(
                "§3.7.7 verify by key that every membership guard this card named is gone",
                record["error"],
                stage2.CLEANUP_FAILED,
            )
        )
    finally:
        write_record(out_dir, lane_id, record, cleanup)
    return record


def write_record(out_dir: Path, lane_id: str, record: dict[str, Any], cleanup: list[Row]) -> Path:
    """Put the lane record on disk exactly as far as the run got.

    The record is the deliverable, so it is written from a ``finally`` rather than only on the success path:
    a run that was interrupted, refused at setup, or lost its sweep still leaves the census, the cleanup rows
    and the ids it captured, which is what the next run of this lane needs to name those rows to the sweeper.
    """
    record["cleanup"] = cleanup
    record["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{lane_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return path


def run(out_dir: Path, data_id: str = "", prior: Sequence[str] = ()) -> dict[str, Any]:
    """Run the lane, write the record where asked, and return it."""
    api.publish_base_url()
    admin, scout = sign_in("admin"), sign_in("scout")
    schema = api.gql(
        admin,
        "query { __schema { queryType { fields { name } } mutationType { fields { name } } } }",
    )
    answered = stage3.stage_three_fields_in_schema(schema)
    missing = [field for field in (*stage3.STAGE_THREE_WRITES, *stage3.STAGE_THREE_READS) if field not in answered]
    if answered and missing:
        raise AssertionError(f"{stage3.MISSING_ENDPOINT_NOTE}: this API answers {answered} and is missing {missing}")
    lane_id = data_id or new_data_id()
    digits = int(lane_id.split("-")[1])
    canary_id = f"w168can-{digits}"
    catalog_id, products = _shared_catalog(admin)
    chosen = [
        next(pid for pid, row in zip(products, _shared_products(admin), strict=False) if row.get("productName") == name)
        for name in PREFERRED_PRODUCTS
        if any(row.get("productName") == name for row in _shared_products(admin))
    ]
    if not catalog_id or not chosen:
        raise AssertionError(
            f"the shared catalog answers no product to assign: catalog={catalog_id!r}, products={products}"
        )

    record: dict[str, Any] = {
        "stack": api.base_url(),
        "dataId": lane_id,
        "canaryDataId": canary_id,
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "catalogId": catalog_id,
        "products": chosen,
        "canary": {"lane": {}, "before": {}, "after": {}, "identical": False},
    }
    cleanup: list[Row] = []
    canary: dict[str, Any] = {}
    lane: dict[str, Any] = {}
    written: dict[str, Any] = {}
    canary_before: dict[str, Any] = {}
    recovery_steps: list[str] = []

    def transport(document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        """One census read, sent as the product answers it, with the whole body returned.

        The document map is the two shipped halves merged: the census reads the swept tables answer
        are Stage 2 documents except ``showAndSells``, which the Show & Sell table joined to the sweep
        needs and only the Stage 3 documents mint. A name that resolves in neither is a lookup bug,
        so it raises here rather than being swallowed into an unproven table.
        """
        census_documents = {**stage2.STAGE_TWO_DOCUMENTS, **stage3.STAGE_THREE_DOCUMENTS}
        return api.gql_raw(admin, census_documents[document], dict(variables))

    # The canary is built and snapshotted before anything is given back, so the recovery pass below sits
    # inside the window the canary exists to watch: a cancellation that reached a row it should not have
    # reaches the canary's own before/after compare instead of being filed as a cleanup.  Its profile is
    # picked from the commitments that are already ACTIVE, so the canary does not land on a busy profile
    # either.
    try:
        profile = _lane_profile(scout, _active_commitments(scout))
        if prior:
            # An earlier attempt of a named lane goes first: its rows are the residue this card owns, and its
            # Show & Sell rows can only be taken through the product while its Unit Campaign still answers.
            record["priorSweep"] = sweep_prior(admin, scout, prior, transport)
            cleanup += record["priorSweep"]
        try:
            build_lane(admin, scout, lane_names(canary_id, unit_number=digits + 1), catalog_id, canary, profile)
            canary_before = canary_snapshot(admin, canary)
            # A commitment an earlier attempt of an authorized lane left ACTIVE refuses this lane's signup before
            # the lane writes anything, so it is given back now, through the Scout's own projection rather than any
            # table read, and only for the lane ids this run was told about.
            recovery, recovery_steps, busy_commitments = recover_standing_commitments(
                admin, scout, lane_id, prior, [canary_id]
            )
            record["commitmentRecovery"] = recovery
            cleanup += recovery
            profile = _lane_profile(scout, busy_commitments)
            record["scoutProfileId"] = str(profile["profileId"])
            build_lane(admin, scout, lane_names(lane_id, unit_number=digits), catalog_id, lane, profile)
            write_stage_three_rows(admin, scout, lane, chosen[:2], written)
            record["readWithLaneStanding"] = lane_reads(admin, lane["unitCampaignId"])
            # Counted in the same pre-teardown window as the blocked-table census: once the sweep takes the
            # Unit and the Kernel's grant, no Kernel-side read of this lane's event answers anything at all.
            record["showAndSellResidue"] = show_and_sell_residue(admin, lane, written)
            record["residueCensus"] = stage3.stage_three_residue_census(
                transport, [lane["unitCampaignId"]], [lane["scoutCampaignId"]]
            )
            # The canary is swept too, and a blocked table is only accepted where a read stands in for the
            # scan: the lane's census says nothing about the canary's Unit Campaign, so the canary takes its
            # own.  It wrote no Stage 3 row, and a census that answers zero rows is still an answer.
            record["canaryResidueCensus"] = stage3.stage_three_residue_census(
                transport, [canary["unitCampaignId"]], [canary["scoutCampaignId"]]
            )
        except Exception as exc:  # noqa: BLE001 - a half-finished lane still owes its cleanup and its record
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["errorTrace"] = traceback.format_exc().splitlines()[-8:]
        except BaseException as exc:  # noqa: BLE001 - an interrupted run still owes its record what it knew
            # Re-raised, because this is the one exception the lane must not swallow.  Recorded, because the
            # teardown and sweep that follow it produce a record that otherwise reads like a finished run.
            record["error"] = (
                f"{type(exc).__name__}: {exc} — this run was interrupted; its teardown, sweeps and record still ran"
            )
            record["errorTrace"] = traceback.format_exc().splitlines()[-8:]
            raise
        finally:
            # ``finally``, not a follow-on statement: the run that is interrupted or refused halfway still owes
            # every row it captured to a teardown and a sweep, and what it captured is decided by the ids it
            # recorded, not by whether it reached its Stage 3 writes.
            record["canary"]["lane"] = canary
            record["lane"] = lane
            record["writes"] = written
            run_cleanup_steps(admin, scout, lane, written, canary, canary_before, recovery_steps, record, cleanup)
    finally:
        # The retained class is counted last, after every teardown and sweep this run can run, and it is
        # counted by read: what is left is enumerated with its counts and key shapes instead of being reported
        # as cleaned.  And the record is written in a ``finally``: the run that was interrupted or refused
        # halfway still owes the evidence of what it left, so a record only ever missing its tail is a record
        # a reader can still act on.
        try:
            retained_rows, record["retainedResidue"] = residue_census(
                [lane_id, canary_id, *prior],
                [
                    str(lane.get("unitId") or ""),
                    str(lane.get("unitCampaignId") or ""),
                    _bare(lane.get("scoutCampaignId") or ""),
                    str(canary.get("unitId") or ""),
                    str(canary.get("unitCampaignId") or ""),
                    _bare(canary.get("scoutCampaignId") or ""),
                ],
            )
            cleanup += retained_rows
        except Exception as exc:  # noqa: BLE001 - a census that cannot run is reported, never passed off as absent
            record["censusError"] = f"{type(exc).__name__}: {exc}"
        write_record(out_dir, lane_id, record, cleanup)
    return record


def _canary_compare(admin: str, canary: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """One side of the canary compare, returned with the reason it could not be read rather than raised.

    A partial canary is refused rather than read.  ``canary_snapshot`` needs the Unit, the Unit Campaign and
    the roster row of a *whole* lane, so a canary whose setup stopped at ``createUnit`` would answer a
    ``KeyError`` where a reason belongs, and a compare against half a lane would prove something that never
    happened.  ``GraphQLError`` is a ``RuntimeError``, and a shared stack throttles and refuses as a matter of
    course, so both it and the assertion that refuses a vacuous snapshot are collected here: an evidence read
    that cannot run is a fact the record reports, and it is never a reason to skip the teardown and the sweep
    that are the whole point of the step.
    """
    parts = {name: bool(canary.get(name)) for name in ("unitId", "unitCampaignId", "scoutCampaignId")}
    if not all(parts.values()):
        return {}, (
            f"the canary lane {canary.get('dataId') or '(unnamed)'} stopped before it held a whole lane "
            f"(unitId={parts['unitId']}, unitCampaignId={parts['unitCampaignId']}, "
            f"scoutCampaignId={parts['scoutCampaignId']}), so there is no complete snapshot to compare"
        )
    try:
        return canary_snapshot(admin, canary), ""
    except Exception as exc:  # noqa: BLE001 - a failed proof belongs in the record, not in a traceback
        return {}, f"{type(exc).__name__}: {exc}"


def _cleanup_pass(label: str, step: Callable[[], Sequence[Row]], cleanup: list[Row]) -> bool:
    """Run one teardown or sweep pass, and keep going when it raises.

    These are the passes that give rows back, so no later pass may depend on an earlier one succeeding: a lane
    whose product teardown is refused still owes its rows to the sweeper, and a canary whose sweep is refused
    still owes its Unit to the read-back that would have proved it gone.  A pass that raises is recorded as a
    ``failed`` row of its own, which is what the shared cleanup gate and the exit status both read.
    """
    try:
        result = step()
    except Exception as exc:  # noqa: BLE001 - a refused pass is reported as one, and the rest still runs
        cleanup.append(
            stage3.cleanup_row(
                label,
                f"{type(exc).__name__}: {exc} — this pass did not complete; the passes after it still ran",
                stage2.CLEANUP_FAILED,
            )
        )
        return False
    cleanup += list(result)
    return True


def run_cleanup_steps(
    admin: str,
    scout: str,
    lane: Mapping[str, Any],
    written: Mapping[str, Any],
    canary: Mapping[str, Any],
    canary_before: Mapping[str, Any],
    recovery_steps: Sequence[str],
    record: dict[str, Any],
    cleanup: list[Row],
) -> None:
    """The teardown, both sweeps and the canary read-back, for every id this run actually captured.

    Nothing here waits for the lane to have finished.  Each id was recorded the moment the product answered
    it, so a run refused after ``createUnit`` still hands that Unit and its ``createUnit`` marker to the
    sweep, and a run whose join was refused still takes its Scout Campaign back through ``deleteCampaign``.
    The gate is therefore the token list: ``sweep_tokens`` builds it from the ids that exist, and a lane that
    captured nothing produces no sweep, because a token for a row that was never written is a claim with no
    row behind it.  ``teardown`` walks only the resources it is handed, so the same call serves a finished
    lane and an abandoned one.

    The canary's removal has to be *read* absent.  ``_gone`` reports a failed read as a failed read-back
    rather than as absence, and its Unit-list half only counts once the same read is shown to have answered
    that Unit before the sweep ran: a removal nobody read back, and a silence the reader never proved it
    could hear, are not cleanups.

    Every step here is isolated from every other one, because the steps do different jobs.  A census or
    compare read that refuses, or a canary that never became a whole lane, is a failed proof and nothing more:
    it never cancels the teardown or the sweep that follow it, which are the steps that take rows back.  A
    lane abandoned at ``createUnit`` therefore still leaves its Unit, its marker and its canary's Unit on a
    sweep rather than in the shared stack.
    """
    lane_tokens = sweep_tokens(lane, written, recovery_steps) if lane.get("dataId") else []
    canary_tokens = sweep_tokens(canary, None) if canary.get("dataId") else []
    try:
        if canary.get("dataId") and not canary_before:
            # A snapshot this run never got to take is taken here rather than skipped: the compare still
            # brackets the canary's teardown and its own sweep, and what it no longer covers is said so in the
            # record.  A snapshot that refuses, or that has no whole lane in front of it, is recorded and the
            # identical check below then fails — and the sweep still runs.
            record["canary"]["snapshotTakenLate"] = True
            snapshot, refused = _canary_compare(admin, canary)
            if refused:
                record["canary"]["snapshotError"] = refused
                cleanup.append(
                    stage3.cleanup_row(
                        "§3.7.7 snapshot the canary before any teardown", refused, stage2.CLEANUP_BLOCKED
                    )
                )
            else:
                canary_before = snapshot
        if lane.get("dataId"):
            _cleanup_pass(
                "§3.7.7 product teardown of the lane under test",
                lambda: teardown(admin, scout, lane, written),
                cleanup,
            )
        if not written:
            cleanup.append(
                stage3.cleanup_row(
                    "§3.7.7 product teardown",
                    "the lane wrote no Stage 3 row, so there was no event, slot or signup to take back; its "
                    "setup rows are the sweep's to take",
                )
            )
        if canary_tokens:
            record["canarySweepTokens"] = canary_tokens
        if lane_tokens:

            def _sweep_lane() -> list[Row]:
                row, detail = sweep_row(lane_tokens, record.get("residueCensus", {}))
                record["sweep"] = detail
                return [row]

            _cleanup_pass("§3.7.7 lane sweep", _sweep_lane, cleanup)
        if canary_tokens:
            snapshot_after, refused = _canary_compare(admin, canary)
            if refused:
                # A canary this record cannot read is a failed read-back, not an untouched lane: the compare
                # is what proves this lane's sweep left an independent lane alone, and it did not run.
                record["canary"]["snapshotError"] = f"the after-sweep read refused: {refused}"
                cleanup.append(
                    stage3.cleanup_row(
                        "§3.7.7 re-read the canary after this lane's sweep", refused, stage2.CLEANUP_FAILED
                    )
                )
            record["canary"]["before"] = canary_before
            record["canary"]["after"] = snapshot_after
            # ``and canary_before and snapshot_after`` is what keeps the compare from being vacuous: two
            # snapshots that both read nothing are equal, and that equality would be reported as a canary
            # left untouched.
            record["canary"]["identical"] = (
                bool(canary_before)
                and bool(snapshot_after)
                and json.dumps(canary_before, sort_keys=True) == json.dumps(snapshot_after, sort_keys=True)
            )
            _cleanup_pass(
                "§3.7.7 product teardown of the canary lane", lambda: teardown(admin, scout, canary, {}), cleanup
            )
            # The control has to be taken while the row is still there: the sweep that works deletes the Unit,
            # and a Unit list that never named the row cannot be evidence that it later stopped naming it.  A
            # control read that fails is recorded as failing rather than skipped, because the read-back below
            # has to say which kind of silence it is reporting — and the canary's sweep runs either way.
            try:
                answered_before = _unit_answers(admin, str(canary["unitId"]))
                control_error = ""
            except Exception as exc:  # noqa: BLE001 - a failed control read is reported, and the sweep follows
                answered_before, control_error = False, f"{type(exc).__name__}: {exc}"
                record["canary"]["controlReadError"] = control_error
            record["canary"]["unitAnsweredBeforeSweep"] = answered_before

            def _sweep_canary() -> list[Row]:
                row, detail = sweep_row(canary_tokens, record.get("canaryResidueCensus", {}))
                record["canarySweep"] = detail
                return [row]

            _cleanup_pass("§3.7.7 canary sweep", _sweep_canary, cleanup)
            gone = _gone(admin, canary, answered_before=answered_before, control_error=control_error)
            record["canary"]["removed"] = gone["removed"]
            record["canary"]["goneReads"] = gone["reads"]
            if gone["readError"]:
                record["canary"]["goneReadError"] = gone["readError"]
            cleanup.append(
                stage3.cleanup_row(
                    "§3.7.7 read the canary back as gone",
                    "the canary's own Unit answers no Unit Campaign and myUnits no longer answers that Unit, "
                    "the read that named it while it stood: "
                    + "; ".join(f"{name} {answer}" for name, answer in gone["reads"].items())
                    if gone["removed"]
                    else "the canary was not affirmatively read back as gone: "
                    f"{gone['readError'] or 'its Unit Campaign rows are still answered'} — "
                    + "; ".join(f"{name} {answer}" for name, answer in gone["reads"].items()),
                    stage2.CLEANUP_OBSERVED if gone["removed"] else stage2.CLEANUP_FAILED,
                )
            )
        if lane.get("unitCampaignId"):
            record["readAfterTeardown"] = _safe_reads(admin, lane["unitCampaignId"])
        # The Show & Sell rows are the one part of the retained class the sweeper can neither take nor
        # report, so they are read back here: the counts come from the pre-teardown read, and their standing
        # after the sweep comes from a read the sweep cannot stale out.  A projection read that fails says that
        # the standing is unproven; it does not reach past itself into the census that follows.
        event_id = str(written.get("showAndSellId") or "")
        try:
            rows, standing = retained_commitment_rows(scout, [event_id])
        except Exception as exc:  # noqa: BLE001 - a failed read leaves the standing unproven, and says so
            rows, standing = [], 0
            cleanup.append(
                stage3.cleanup_row(
                    "§3.7.7 read the retained Show & Sell rows back after every sweep",
                    f"{type(exc).__name__}: {exc} — myScoutCommitments never answered, so the standing of this "
                    f"lane's rows in {stage3.show_and_sells_table()} after the sweeps is not proven by a read",
                    stage2.CLEANUP_FAILED,
                )
            )
        record["retainedCommitmentRows"] = standing
        cleanup += rows
        if event_id and not standing:
            cleanup.append(
                stage3.cleanup_row(
                    "§3.7.7 read the retained Show & Sell rows back after every sweep",
                    f"myScoutCommitments answers no projection of event {event_id}, so the standing of this "
                    f"lane's {stage3.show_and_sells_table()} rows is not proven by a read",
                    stage2.CLEANUP_BLOCKED,
                )
            )
    except Exception as exc:  # noqa: BLE001 - the record has to survive a failing step to report one
        record["sweepError"] = (
            f"{type(exc).__name__}: {exc} — a step outside the guarded teardown and sweep passes failed, so the "
            "passes it did not reach are named by the rows above rather than by this record"
        )


def _shared_products(admin: str) -> list[dict[str, Any]]:
    body = api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["managedCatalogs"], {})
    chosen = next((dict(row) for row in (_one(body) or []) if str(row.get("catalogType")) == "ADMIN_MANAGED"), {})
    return [dict(row) for row in chosen.get("products") or []]


def _safe_reads(admin: str, unit_campaign_id: str) -> dict[str, Any]:
    """The post-teardown read, reported as the API answered it rather than raised."""
    try:
        return lane_reads(admin, unit_campaign_id)
    except api.GraphQLError as exc:
        return {"error": str(exc)}


def _unit_answers(admin: str, unit_id: str) -> bool:
    """Whether this identity's own Unit list answers one Unit id — the read a sweep can stale out.

    ``myUnits`` is the read that found the canary's Unit while it stood (the same read
    :func:`prior_lane` walks for an earlier attempt), which is what makes its silence afterwards a fact about
    the row rather than about the caller.
    """
    return any(str(row.get("unitId")) == str(unit_id) for row in _lane_units(admin))


def _gone(
    admin: str,
    canary: Mapping[str, Any],
    *,
    answered_before: bool = False,
    control_error: str = "",
) -> dict[str, Any]:
    """Whether the canary's rows are gone, and the reads that say so.

    Two reads, because neither one settles it alone.  A sweep that works deletes the Unit row, and afterwards
    ``unitCampaigns`` answers ``Unit not found`` — a refusal, not an empty list — while a Unit that is still
    there can also answer no Campaigns.  So the Campaign read decides only when it answers rows; otherwise
    the Unit list decides, and it decides only against its own earlier answer: a list that never named this
    Unit proves nothing when it goes on not naming it.  Reporting absence on a single error, or on a read that
    could not have seen the row, would let the record claim the one thing it exists to prove — a lane swept
    clean while an independent lane stood untouched — on the strength of not having looked.

    ``control_error`` names the case where the control read itself was refused rather than never taken, which
    is the difference between a silence that proves nothing and a proof this run was not allowed to make.
    """
    reads: dict[str, str] = {}
    campaign_error = ""
    try:
        items = _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": canary["unitId"]})
        )
        reads["unitCampaigns"] = f"answers {len(items)} Unit Campaign row(s) for Unit {canary['unitId']}"
        if items:
            return {"removed": False, "readError": "its Unit still answers its Unit Campaign rows", "reads": reads}
    except Exception as exc:  # noqa: BLE001 - a Campaign read that cannot answer is a fact, not an absence
        campaign_error = f"{type(exc).__name__}: {exc.args[0] if exc.args else exc}"
        reads["unitCampaigns"] = f"answered {campaign_error!r} for Unit {canary['unitId']}"
    try:
        listed = _unit_answers(admin, str(canary["unitId"]))
    except Exception as exc:  # noqa: BLE001 - a read that cannot answer is a failed read-back, not an absence
        error = f"{type(exc).__name__}: {exc.args[0] if exc.args else exc}"
        reads["myUnits"] = f"answered {error!r}"
        return {
            "removed": False,
            "readError": f"the Unit read that would confirm the row is gone answered {error!r}",
            "reads": reads,
        }
    reads["myUnits"] = f"{'still answers' if listed else 'no longer answers'} Unit {canary['unitId']}"
    if listed:
        return {
            "removed": False,
            "readError": f"the Unit row is still answered by myUnits ({campaign_error or reads['unitCampaigns']})",
            "reads": reads,
        }
    if not answered_before:
        return {
            "removed": False,
            "readError": (
                f"the control read that would have named this Unit failed ({control_error}), so the Unit "
                "list's silence proves nothing"
                if control_error
                else "the Unit read never answered this Unit while the canary stood, so its silence proves nothing"
            ),
            "reads": reads,
        }
    return {"removed": True, "readError": "", "reads": reads}


def lane_failures(record: Mapping[str, Any]) -> list[str]:
    """Every reason this record does not pass its own gate, as data the exit status and the tests read.

    This is the lane's whole verdict in one place: the shared cleanup gate decides the cleanup rows, so
    ``SS_STRICT_CLEANUP=1`` turns an environment-blocked step into a failure the same way it does in the
    Stage 2 lane — the one-step reversal Amendment C promises, wired to the exit status and not only to the
    printed summary.  A canary that changed, or whose removal was never affirmatively read back, costs the
    run the same way: a removal nobody read back is not a cleanup.
    """
    failures: list[str] = []
    try:
        stage3.assert_stage_three_cleanup_clean(list(record.get("cleanup") or []))
    except stage3.StageThreeCleanupError as exc:
        failures.append(str(exc))
    canary = record.get("canary") or {}
    if canary.get("lane"):
        if not canary.get("before"):
            failures.append(
                "the canary was never snapshotted, so nothing proves this lane's sweep left it alone"
                + (f": {canary['snapshotError']}" if canary.get("snapshotError") else "")
            )
        elif not canary.get("after"):
            # The compare needs both sides, and a missing right-hand side is not a canary that stayed put.
            failures.append(
                "the canary was never re-read after this lane's sweep, so the compare that proves the sweep "
                "left it alone never ran" + (f": {canary['snapshotError']}" if canary.get("snapshotError") else "")
            )
        elif not canary.get("identical"):
            failures.append("the canary lane changed across this lane's sweep")
        if not canary.get("removed"):
            failures.append(
                "the canary's removal was not affirmatively read back: "
                + str(
                    canary.get("goneReadError")
                    or "the read after its own sweep still answered Unit Campaign rows for that Unit"
                )
            )
    residue = record.get("guardResidue") or {}
    if residue:
        entries = residue.get("keys") or []
        if residue.get("guards") is not None and len(entries) != residue["guards"]:
            failures.append(
                f"the guard census examined {residue['guards']} key(s) but only {len(entries)} carry a "
                "disposition, so a guard key is unaccounted for"
            )
        unexplained = sorted(set(residue.get("namedKeys") or []) - {str(entry.get("campaignId")) for entry in entries})
        if unexplained:
            failures.append(
                f"the guard key(s) {', '.join(unexplained)} were named on the command line and no read of them "
                "is in this record, so it cannot say what became of them"
            )
    for key in ("error", "sweepError", "censusError"):
        if record.get(key):
            failures.append(f"{key}: {record[key]}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lane and print its verdict."""
    parser = argparse.ArgumentParser(
        prog="tests.e2e.show_sell_stage3_lane", description="Run one Stage 3 lane and write its cleanup record."
    )
    parser.add_argument("--out", default="../lane-records", type=Path, help="where to write the lane record")
    parser.add_argument("--data-id", default="", help="pin the lane id, to re-run one the earlier pass left behind")
    parser.add_argument(
        "--sweep-prior",
        default="",
        help="comma-separated DATA_IDs of earlier attempts of this lane whose rows are still standing",
    )
    parser.add_argument(
        "--verify-guards",
        action="store_true",
        help="run only the read-only membership-guard pass: enumerate the guard rows, read every key named "
        "by its exact key, and report each key's disposition — this pass never deletes anything",
    )
    parser.add_argument(
        "--guard-campaign",
        action="append",
        default=[],
        help="Scout Campaign id of one guard key this card owes a disposition for, on top of the ones the table "
        "answers; repeatable, for a key an earlier sweep report named and the table no longer explains",
    )
    parser.add_argument(
        "--claim-label",
        action="append",
        default=[],
        help=f"a lane label this card's own runs write into a Profile name; repeatable, extends "
        f"{', '.join(CARD_CLAIM_LABELS)}",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    prior = [item.strip() for item in args.sweep_prior.split(",") if item.strip()]
    labels = (*CARD_CLAIM_LABELS, *(label.strip() for label in args.claim_label if label.strip()))

    if args.verify_guards or args.guard_campaign:
        record = verify_guards(args.out, args.guard_campaign, labels)
        residue = record.get("guardResidue") or {}
        print(
            json.dumps(
                {
                    "guards": residue.get("guards"),
                    "guardRows": residue.get("guardRows"),
                    "table": residue.get("table"),
                    "campaignsTable": residue.get("campaignsTable"),
                    "fixtureAllowlist": residue.get("fixtureAllowlist"),
                    "namedKeys": residue.get("namedKeys"),
                    "namedAbsent": residue.get("namedAbsent"),
                    "byState": residue.get("byState"),
                    "cleanup": record["cleanup"],
                },
                indent=2,
            )
        )
        failures = lane_failures(record)
        print(f"strict cleanup (SS_STRICT_CLEANUP): {stage3.STRICT_CLEANUP}")
        print(f"cleanup failures: {failures or 'none'}")
        print(f"record: {record['dataId']}")
        return 1 if failures else 0

    record = run(args.out, args.data_id, prior)
    keys = (
        "dataId",
        "error",
        "sweepError",
        "censusError",
        "commitmentRecovery",
        "priorSweep",
        "residueCensus",
        "showAndSellResidue",
        "retainedCommitmentRows",
        "sweep",
        "canarySweep",
        "canary",
        "retainedResidue",
        "cleanup",
    )
    print(json.dumps({key: record.get(key) for key in keys}, indent=2))
    failures = lane_failures(record)
    blocked = stage3.cleanup_blocked(record.get("cleanup") or [])
    print(f"strict cleanup (SS_STRICT_CLEANUP): {stage3.STRICT_CLEANUP}")
    print(f"cleanup failures: {failures or 'none'}; blocked: {blocked or 'none'}")
    print(f"record: {record['dataId']}")
    return 1 if failures else 0


def cli(argv: Sequence[str] | None = None) -> int:
    """The module's exit status, including for a run that was cut short.

    ``run`` re-raises a ``KeyboardInterrupt`` on purpose, because the alternative is a record that reads like
    a finished run.  Suppressing it here instead used to make that honest re-raise leave through the back
    door: the interrupt skipped ``main``'s call to :func:`lane_failures`, and the command fell off the end
    with exit status 0.  The one outcome this runner must never produce is a green exit for a run it did not
    finish.  By the time an interrupt reaches this frame the teardown, both sweeps and the record have run;
    what is missing is the verdict, so the exit status is what says so.
    """
    try:
        return main(argv)
    except KeyboardInterrupt:
        print(
            "interrupted: the teardown, both sweeps and the lane record ran, and no verdict was reached — exit 130",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(cli())
