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
sanctioned sweeper does — ``Scan``, and only on the three tables ``kernelworx-qa-ue1-dev`` can already
open — to count the residue a sweep report never names.  It never writes to a table: every deletion is a
product mutation or a ``scripts/qa_fixture.py sweep`` call.

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
   guard comes back ``UNKNOWN`` and fails the sweep closed).
6. Re-reads the canary and fails if that sweep disturbed it, then takes the canary down with its own
   tokens so the record also shows the sweeper removing a lane it is pointed at.
7. Counts the residue that survives all of it, per physical table, by read: Amendment C requires the
   retained class with counts and key shapes, and a sweep report cannot supply that count for a key shape
   no rule describes — such a row is neither deleted nor reported, so a record quoting only sweep lines
   would read as if nothing were left.

The lane stops with words rather than a false pass when the stack cannot carry it: an API that answers no
Stage 3 endpoint raises with ``MISSING_ENDPOINT_NOTE``, and a catalog with no product to assign says so.
"""

from __future__ import annotations

import argparse
import contextlib
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

#: The name every event this module writes carries, and the only fact that makes a standing signup this
#: card's to cancel.  The four fixture identities are shared by every lane on this stack, so "this Scout
#: holds it" is not attribution: :func:`recover_standing_commitments` reads the event and acts only when its
#: own ``locationName`` answers this prefix.  The reason is final, not stylistic — a cancelled signup can
#: never be re-created in the same slot (``src/handlers/unit_operations.py``: "a cancelled signup stays
#: history. Choose another slot."), so a row cancelled on a guess is a row nobody can put back.
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
                    f"{LANE_EVENT_PREFIX}{data_id.removeprefix('w168')}",
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
    """The canary lane's rows, exactly as the API answered them, for a byte-for-byte before/after compare."""
    return {
        "unit": _one(api.gql(admin, SETUP_DOCUMENTS["unitMetadata"], {"unitId": canary["unitId"]})),
        "unitCampaigns": _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": canary["unitId"]})
        ),
        "roster": _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": canary["unitCampaignId"]})
        ),
    }


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
    call this module makes is ``Scan``, on the three tables the fixture identity can already read, and every
    deletion stays a product mutation or a ``qa_fixture.py sweep`` call.
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
    """Take back the Show & Sell rows an earlier attempt left, through the shipped mutations.

    The sweeper never opens the Show & Sell table, so an event an earlier attempt wrote would survive every
    lane token — and while its signup row stays ``ACTIVE``, its ``ScoutCommitment`` projection stays ACTIVE
    too, which is what refuses the next lane's signup with "This Scout is already committed to another Show &
    Sell at these hours".  So a prior lane is torn down through the product first: signup, then slots, then
    the event, in the order the server's own guards require.

    Cancellation is legal only before ``startAt``, so an event that is already past that line is enumerated as
    retained rather than forced through a path the product refuses.  A signup whose row names a profile outside
    the fixture pool is left alone: it is not this lane's to cancel.
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
            detail = (
                _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id})) or {}
            )
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
    admin: str, scout: str, data_id: str
) -> tuple[list[Row], list[str], list[dict[str, Any]]]:
    """Give back this lane family's own ACTIVE ``ScoutCommitment`` rows, before the lane signs up again.

    The order is not a preference, it is the product's guard: while a signup row is ``ACTIVE`` its
    ``ScoutCommitment`` projection is ACTIVE too, and ``signupScoutForShowAndSellSlot`` refuses the next lane
    with "This Scout is already committed to another Show & Sell at these hours".  A lane whose Unit row the
    sweeper already took cannot be reached through its Unit Campaign — ``showAndSells`` and
    ``showAndSellSignups`` are keyed on rows that no longer exist — so the read that finds the orphan is the
    Scout's own ``myScoutCommitments``, and the write that clears it is ``cancelShowAndSellSignup``, which
    authorizes a non-Kernel caller by profile access alone and asks nothing about the Unit or the roster.
    Both are shipped paths: nothing here reaches for the table.

    The gate is attribution, and it is not optional.  Every lane on this stack signs in as the same four
    fixture identities, so an ACTIVE commitment is not automatically this lane's to cancel: each one is read
    through ``showAndSell`` and cancelled only when that event's own ``locationName`` answers the
    :data:`LANE_EVENT_PREFIX` this module mints.  A row whose event names anything else, or whose event read
    is refused, is enumerated and left: a cancelled signup can never be created again in the same slot
    (``src/handlers/unit_operations.py``: "a cancelled signup stays history. Choose another slot."), so
    cancelling another run's place is not a cleanup, it is a row nobody can put back.

    Cancellation markers this pass mints carry *this* lane's id, so they go back to the sweeper as this
    lane's own tokens.
    """
    rows: list[Row] = []
    steps: list[str] = []
    for position, commitment in enumerate(_standing_commitments(scout), start=1):
        event_id = str(commitment.get("showAndSellId") or "")
        slot_id = str(commitment.get("slotId") or "")
        if str(commitment.get("status") or "") != "ACTIVE":
            continue
        where = f"event {event_id} slot {slot_id} profile {commitment.get('profileId')}"
        try:
            detail = (
                _one(api.gql(admin, stage3.STAGE_THREE_DOCUMENTS["showAndSell"], {"showAndSellId": event_id})) or {}
            )
        except api.GraphQLError as exc:
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read back the Scout's ACTIVE commitments",
                    f"{where}: the event read answered {exc.args[:1]!r}, so this row cannot be attributed to "
                    f"a {LANE_EVENT_PREFIX}* lane and nothing is written against it",
                    stage2.CLEANUP_BLOCKED,
                )
            )
            continue
        location = str(detail.get("locationName") or "")
        if not location.startswith(LANE_EVENT_PREFIX):
            rows.append(
                stage3.cleanup_row(
                    "§3.7.7 read back the Scout's ACTIVE commitments",
                    f"{where} answers ACTIVE on an event named {location!r}, which no lane of this card wrote: "
                    "left standing, because a cancelled signup cannot be re-created in the same slot",
                )
            )
            continue
        step = f"recover-commitment-{position}"
        steps.append(step)
        row = stage3.run_cleanup_step(
            "§3.7.7 give back a commitment this card's own earlier attempt left",
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
            f"event {event_id} ({location!r}) slot {slot_id}: commitment answered ACTIVE at "
            f"{commitment.get('startAt')}..{commitment.get('endAt')} — {row['summary']}"
        )
        rows.append(row)
    still_active = [row for row in _standing_commitments(scout) if str(row.get("status") or "") == "ACTIVE"]
    ours = [
        row
        for row in still_active
        if str(
            (
                _one(
                    api.gql(
                        admin,
                        stage3.STAGE_THREE_DOCUMENTS["showAndSell"],
                        {"showAndSellId": str(row.get("showAndSellId"))},
                    )
                )
                or {}
            ).get("locationName")
            or ""
        ).startswith(LANE_EVENT_PREFIX)
    ]
    rows.append(
        stage3.cleanup_row(
            "§3.7.7 read back the Scout's commitment set",
            f"myScoutCommitments answers {len(still_active)} ACTIVE commitment(s) after this pass "
            f"({len(steps)} cancellation(s) sent): "
            + "; ".join(
                f"{row.get('showAndSellId')}/{row.get('slotId')} on {row.get('startAt')} (profile {row.get('profileId')})"
                for row in still_active
            )
            + f", {len(ours)} of them on an event this card's naming template wrote",
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

    def transport(document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        """One census read, sent as the product answers it, with the whole body returned."""
        return api.gql_raw(admin, stage2.STAGE_TWO_DOCUMENTS[document], dict(variables))

    # A commitment an earlier attempt left ACTIVE refuses this lane's signup before the lane writes
    # anything, so it is given back first, through the Scout's own projection rather than any table read.
    recovery, recovery_steps, busy_commitments = recover_standing_commitments(admin, scout, lane_id)
    record["commitmentRecovery"] = recovery
    cleanup += recovery
    profile = _lane_profile(scout, busy_commitments)
    record["scoutProfileId"] = str(profile["profileId"])

    if prior:
        record["priorSweep"] = sweep_prior(admin, scout, prior, transport)
        cleanup += record["priorSweep"]

    try:
        build_lane(admin, scout, lane_names(canary_id, unit_number=digits + 1), catalog_id, canary, profile)
        canary_before = canary_snapshot(admin, canary)
        build_lane(admin, scout, lane_names(lane_id, unit_number=digits), catalog_id, lane, profile)
        write_stage_three_rows(admin, scout, lane, chosen[:2], written)
        record["readWithLaneStanding"] = lane_reads(admin, lane["unitCampaignId"])
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
    record["canary"]["lane"] = canary
    record["lane"] = lane
    record["writes"] = written
    if canary.get("unitCampaignId") and not canary_before:
        canary_before = canary_snapshot(admin, canary)

    if written:
        cleanup += teardown(admin, scout, lane, written)
    else:
        cleanup.append(
            stage3.cleanup_row(
                "§3.7.7 product teardown", "the lane wrote no Stage 3 row, so there was nothing to remove"
            )
        )
    try:
        if canary.get("unitCampaignId"):
            record["canarySweepTokens"] = sweep_tokens(canary, None)
        if lane.get("unitCampaignId"):
            row, detail = sweep_row(sweep_tokens(lane, written, recovery_steps), record.get("residueCensus", {}))
            cleanup.append(row)
            record["sweep"] = detail
        if canary.get("unitCampaignId"):
            canary_after = canary_snapshot(admin, canary)
            record["canary"]["after"] = canary_after
            record["canary"]["identical"] = json.dumps(canary_before, sort_keys=True) == json.dumps(
                canary_after, sort_keys=True
            )
            cleanup += teardown(admin, scout, canary, {})
            canary_row, canary_detail = sweep_row(sweep_tokens(canary, None), record.get("canaryResidueCensus", {}))
            cleanup.append(canary_row)
            record["canarySweep"] = canary_detail
            record["canary"]["removed"] = _gone(admin, canary)
        if lane.get("unitCampaignId"):
            record["readAfterTeardown"] = _safe_reads(admin, lane["unitCampaignId"])
    except Exception as exc:  # noqa: BLE001 - the record has to survive a failing sweep to report one
        record["sweepError"] = f"{type(exc).__name__}: {exc}"
    # The retained class is counted last, after every teardown and sweep this run can run, and it is counted
    # by read: what is left is enumerated with its counts and key shapes instead of being reported as cleaned.
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
    record["cleanup"] = cleanup
    record["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{lane_id}.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


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


def _gone(admin: str, canary: Mapping[str, Any]) -> bool:
    """Whether the canary's Unit Campaign is no longer answered by its Unit, after its own sweep."""
    try:
        return not _items(
            api.gql(admin, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"], {"unitId": canary["unitId"]})
        )
    except api.GraphQLError:
        return True


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
    args = parser.parse_args(list(argv) if argv is not None else None)
    prior = [item.strip() for item in args.sweep_prior.split(",") if item.strip()]
    record = run(args.out, args.data_id, prior)
    keys = (
        "dataId",
        "error",
        "sweepError",
        "commitmentRecovery",
        "priorSweep",
        "residueCensus",
        "sweep",
        "canarySweep",
        "cleanup",
    )
    print(json.dumps({key: record.get(key) for key in keys}, indent=2))
    failures = stage3.cleanup_failures(record["cleanup"])
    blocked = stage3.cleanup_blocked(record["cleanup"])
    if record["canary"].get("lane") and not record["canary"].get("identical"):
        failures.append("the canary lane changed across this lane's sweep")
    for key in ("error", "sweepError"):
        if record.get(key):
            failures.append(record[key])
    print(f"cleanup failures: {failures or 'none'}; blocked: {blocked or 'none'}")
    print(f"record: {record['dataId']}")
    return 1 if failures else 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
