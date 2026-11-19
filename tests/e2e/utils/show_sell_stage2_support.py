"""Stage 2 (inventory, Scout custody, fulfillment) support for the deployed-stack acceptance suite.

This module holds the parts of §2.8.5 that can be proven without a deployed stack: the GraphQL
documents and input payloads the Stage 2 suite sends, the check that they still match the SDL this
repository ships, and the arithmetic a persisted Stage 2 answer has to satisfy.

It lives next to :mod:`tests.e2e.utils.show_sell_graphql`, and for the same reason the evidence
helpers do — outside the spec, so ``tests/unit`` can execute it.  Importing the Stage 2 spec itself
from the unit suite fails on its ``slow`` marker under the root pytest configuration.

Two rules the whole module follows:

* **A document names the arguments the SDL declares.**  :func:`stage_two_contract_violations`
  compares every document and input builder here against ``tofu/application/schema/schema.graphql``,
  so a resolver rename stops a lane with a named mismatch instead of an AppSync parse error
  partway through it.
* **A quantity is checked against the rows it is derived from, never against a stored copy.**
  §5.2 defines ``sellableKernelQty``, ``unassignedKernelQty``, ``assignmentOverageQty`` and
  ``totalUnitOwnedUndeliveredQty`` as formulas over the balance, allocation and custody rows, and
  the deployed read recomputes them per request
  (:func:`src.utils.inventory_models.derived_inventory_quantities`).  What a live answer has to
  satisfy is those formulas, so that is what the helpers assert.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "MISSING_ENDPOINT_NOTE",
    "STAGE_TWO_DOCUMENTS",
    "STAGE_TWO_READS",
    "STAGE_TWO_SUPPORT_DOCUMENTS",
    "STAGE_TWO_WRITES",
    "adjust_input",
    "assert_cleanup_clean",
    "assert_cleanup_clean",
    "council_need_positions",
    "council_on_order_input",
    "custody_by_product",
    "fixture_sweep",
    "run_cleanup_step",
    "CLEANUP_BLOCKED",
    "CLEANUP_FAILED",
    "CLEANUP_OBSERVED",
    "STRICT_CLEANUP",
    "cleanup_blocked",
    "cleanup_failures",
    "cleanup_problems",
    "CleanupBlocked",
    "cleanup_row",
    "custody_sale_input",
    "fulfill_input",
    "issue_input",
    "missing_stage_two_endpoints",
    "movement_trail_violations",
    "position_arithmetic_violations",
    "StageTwoCleanupError",
    "receipt_input",
    "remove_membership_input",
    "return_input",
    "reverse_input",
    "stage_two_contract_violations",
    "stage_two_fields_in_schema",
    "stage_two_selection_violations",
]

#: The Stage 2 mutations the acceptance ids name (``INV-M-01``–``INV-M-07``).
STAGE_TWO_WRITES: tuple[str, ...] = (
    "recordInventoryReceipt",
    "adjustInventory",
    "adjustCouncilOnOrder",
    "issueStockToScout",
    "returnStockFromScout",
    "fulfillIndividualOrderLine",
    "reverseIndividualOrderFulfillment",
)

#: The Stage 2 queries the acceptance ids name (``INV-Q-01``–``INV-Q-05``), the
#: ``unitScoutCampaignOrders`` read the fulfillment screen is built on, and the
#: ``createOrder`` extension ``ORD-API-02`` exercises.
STAGE_TWO_READS: tuple[str, ...] = (
    "inventoryPositions",
    "inventoryMovements",
    "scoutCustodyBalances",
    "myScoutCustody",
    "orderFulfillments",
    "unitScoutCampaignOrders",
    "createOrder",
)

#: Says *why* a Stage 2 lane stopped, in the words a reader of the evidence needs.  A suite that
#: quietly skips because the deployed build predates its endpoints reads the same as one that
#: passed, so the reason has to name the build and what it waits on.
MISSING_ENDPOINT_NOTE = (
    "the deployed build answers no Stage 2 endpoint, so §2.8.5 cannot run against this stack: it "
    "waits on the Stage 2 merge SHA's `Deploy Dev` run"
)

# ---------------------------------------------------------------------------
# Input builders: one per Stage 2 write, so a payload shape exists in exactly one place and the
# SDL check below has something concrete to compare against.
# ---------------------------------------------------------------------------


def _idempotency(key: str) -> dict[str, str]:
    """The ``IdempotencyInput`` every Stage 2 mutation requires (``IDEM-01``)."""
    return {"idempotencyKey": key}


def receipt_input(unit_campaign_id: str, product_id: str, quantity: int, *, idempotency_key: str) -> dict[str, Any]:
    """``RecordInventoryReceiptInput`` — stock received into the campaign's Kernel balance."""
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "quantity": quantity,
        "idempotency": _idempotency(idempotency_key),
    }


def adjust_input(
    unit_campaign_id: str,
    product_id: str,
    quantity_delta: int,
    reason: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``AdjustInventoryInput`` — a signed change to central stock, always carrying its reason."""
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "quantityDelta": quantity_delta,
        "reason": reason,
        "idempotency": _idempotency(idempotency_key),
    }


def council_on_order_input(
    unit_campaign_id: str,
    product_id: str,
    quantity_delta: int,
    *,
    reason: str = "Kernel says the Council has it on order",
    idempotency_key: str = "council-on-order",
) -> dict[str, Any]:
    """``AdjustCouncilOnOrderInput`` — the separate on-order balance, never a stock delta."""
    return {
        "unitCampaignId": unit_campaign_id,
        "productId": product_id,
        "quantityDelta": quantity_delta,
        "reason": reason,
        "idempotency": _idempotency(idempotency_key),
    }


def issue_input(
    unit_campaign_id: str,
    campaign_id: str,
    profile_id: str,
    product_id: str,
    quantity: int,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``IssueStockToScoutInput`` — Kernel stock into one Scout's custody (``INV-M-04``)."""
    return {
        "unitCampaignId": unit_campaign_id,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "productId": product_id,
        "quantity": quantity,
        "idempotency": _idempotency(idempotency_key),
    }


def return_input(
    unit_campaign_id: str,
    campaign_id: str,
    profile_id: str,
    items: Sequence[Mapping[str, Any]],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``ReturnStockFromScoutInput`` — one batch of products, one atomic result (``INV-M-05-01``)."""
    return {
        "unitCampaignId": unit_campaign_id,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "items": [dict(item) for item in items],
        "idempotency": _idempotency(idempotency_key),
    }


def fulfill_input(
    order_id: str,
    line_item_id: str,
    quantity: int,
    version: int,
    *,
    idempotency_key: str,
    source: str = "KERNEL_STOCK",
) -> dict[str, Any]:
    """``FulfillIndividualOrderLineInput`` for one source of an owed line.

    ``source`` is the §5.19 choice the whole difference in effects hangs on: ``KERNEL_STOCK``
    consumes unassigned Kernel stock and must name the movement it wrote (``INV-M-06-01``),
    ``EXTERNAL_COUNCIL`` met the demand from outside the Unit's stock and must name no movement at
    all — it writes no inventory row whatever, so ``councilOnOrderQty`` stays where it was
    (``INV-M-06-02``, measured on dev on 2026-11-18).  ``expectedFulfillmentVersion`` is the guard both condition on: the Order's
    version the caller last read, which every fulfillment and reversal increments (§5.19).
    """
    return {
        "orderId": order_id,
        "lineItemId": line_item_id,
        "quantity": quantity,
        "source": source,
        "expectedFulfillmentVersion": version,
        "idempotency": _idempotency(idempotency_key),
    }


def reverse_input(order_id: str, fulfillment_id: str, version: int, *, idempotency_key: str) -> dict[str, Any]:
    """``ReverseIndividualOrderFulfillmentInput`` — the reversal names a record, not a line."""
    return {
        "orderId": order_id,
        "fulfillmentId": fulfillment_id,
        "expectedFulfillmentVersion": version,
        "idempotency": _idempotency(idempotency_key),
    }


def remove_membership_input(
    unit_campaign_id: str,
    campaign_id: str,
    membership_version: int,
    guard_version: int,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``RemoveUnitCampaignMembershipInput`` — the removal half of the ORD-API-02-04 rejoin.

    Both versions are required: the mutation conditions on the membership row and the Scout
    Campaign's tenancy guard it just read, which is what makes a stale roster read a ``CONFLICT``
    rather than a second removal.
    """
    return {
        "unitCampaignId": unit_campaign_id,
        "campaignId": campaign_id,
        "expectedMembershipVersion": membership_version,
        "expectedGuardVersion": guard_version,
        "idempotency": _idempotency(idempotency_key),
    }


def custody_sale_input(
    profile_id: str,
    campaign_id: str,
    product_id: str,
    quantity: int,
    customer_name: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``CreateOrderInput`` for a door-to-door sale (``ORD-API-02``).

    ``createOrder`` is the legacy Order pipeline, so it carries ``idempotencyKey`` at the top of
    the input rather than an ``IdempotencyInput``, and its price comes from the catalog of the
    Scout Campaign named here — which is why the Stage 2 lane creates that Campaign on the same
    catalog as the Unit Campaign (AGENTS.md, "A joined Scout Campaign and its Unit Campaign can
    sell from different catalogs").

    No ``lineItemId`` is sent.  The SDL says the write mints the line's identity (§5.19) and the
    sale answered on dev on 2026-11-18 confirms it — the line comes back under a server-minted id,
    so a caller reads it from the answer instead of naming it, and only ``updateOrder`` re-uses a
    stored one.
    """
    return {
        "profileId": profile_id,
        "campaignId": campaign_id,
        "customerName": customer_name,
        "orderDate": "2026-11-07T08:00:00Z",
        "paymentMethod": "Cash",
        "lineItems": [{"productId": product_id, "quantity": quantity}],
        "fulfillmentMode": "CONSUME_SCOUT_CUSTODY",
        "idempotencyKey": idempotency_key,
    }


def share_read_input(profile_id: str, target_account_email: str) -> dict[str, Any]:
    """``ShareProfileDirectInput`` granting READ and nothing else (``ORD-API-02-03``).

    READ is "view the profile and its campaigns, orders, and generated reports"; WRITE is what
    "place and update orders" needs (``PermissionType``, ``createOrder`` requires Profile Owner/WRITE
    or a Unit Admin of the originating Unit).  A caller holding only READ is therefore the exact
    identity ``ORD-API-02-03`` asks for: able to see the custody, not able to consume it.
    """
    return {
        "profileId": profile_id,
        "targetAccountEmail": target_account_email,
        "permissions": ["READ"],
    }


def revoke_share_input(profile_id: str, target_account_id: str) -> dict[str, Any]:
    """``RevokeShareInput``: the share is keyed by profile and account, not by the grant's id."""
    return {"profileId": profile_id, "targetAccountId": target_account_id}


def deactivate_unit_campaign_input(unit_campaign_id: str, version: int, *, idempotency_key: str) -> dict[str, Any]:
    """``UpdateUnitCampaignInput`` closing one Unit Campaign the lane no longer needs.

    This is the furthest the product goes toward taking a Unit Campaign down: there is no
    ``deleteUnitCampaign`` mutation, and the read side filters on ``isActive``, so deactivating is
    what makes a finished lane's rows inert instead of offering themselves to the next picker.  It
    is not deletion, and the evidence record says so.
    """
    return {
        "unitCampaignId": unit_campaign_id,
        "isActive": False,
        "version": {"expectedVersion": version},
        "idempotency": _idempotency(idempotency_key),
    }


# ---------------------------------------------------------------------------
# Cleanup: what counts as a cleanup failure, and the fixture sweep that finishes the job
# ---------------------------------------------------------------------------


#: Set ``SS_STRICT_CLEANUP=1`` to make an environment-blocked cleanup step fail the run as well.
#: That is the state the gate reaches when the Stage 2 table grant lands for
#: ``kernelworx-qa-ue1-dev``; until then the blocked rows are reported, not passed over.
STRICT_CLEANUP = os.environ.get("SS_STRICT_CLEANUP", "").strip() not in ("", "0", "false", "no")

CLEANUP_OBSERVED = "observed"
CLEANUP_BLOCKED = "blocked"
CLEANUP_FAILED = "failed"

#: The one sanctioned path to a fixture row on the deployed stack.  Project memory (AGENTS.md,
#: "Show & Sell QA login fixture on the dev pool") is explicit that the acceptance harness holds no
#: AWS credentials and never provisions or repairs an identity, so the live lane holds no AWS SDK
#: client of its own: it runs this script and reads its report.  The script owns the attribution rule (a row is
#: fixture-owned only when its own key or owner attribute spells a fixture ``sub`` or fixture
#: address), and ``sweep`` narrows that rule by a lane token so one run can never take another
#: lane's rows.
QA_FIXTURE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "qa_fixture.py"


class StageTwoCleanupError(AssertionError):
    """A §2.8.7 cleanup step did not do what its own read-back says it did.

    It subclasses ``AssertionError`` on purpose: a cleanup failure is a failed acceptance claim, and
    pytest has to report it as a failure rather than a pass with a note in the record.
    """


def cleanup_row(acceptance: str, summary: str, result: str = CLEANUP_OBSERVED) -> dict[str, str]:
    """One cleanup observation: what was attempted, what happened, and whether it counts."""
    assert result in (CLEANUP_OBSERVED, CLEANUP_BLOCKED, CLEANUP_FAILED), f"unknown cleanup result {result!r}"
    return {"acceptance": acceptance, "result": result, "summary": summary}


def cleanup_failures(rows: Iterable[Mapping[str, str]]) -> list[str]:
    """The cleanup rows that mean the lane did not finish the job: refusals and unmet read-backs.

    These are the lane's own failures, and they always cost the run.  A row whose result string is
    missing counts here too — a teardown step that reports nothing is not evidence that it removed
    something.
    """
    return [
        f"{row.get('acceptance', '?')}: {row.get('summary', '')}" for row in rows if row.get("result") == CLEANUP_FAILED
    ]


def cleanup_problems(rows: Iterable[Mapping[str, str]]) -> list[str]:
    """Every cleanup row that is not a completed, read-back-verified removal.

    Anything not marked ``observed`` is a problem: a refused mutation, an unmet read-back, or a step
    the environment made impossible (``blocked``).  A teardown step that reports nothing at all is a
    problem too — silence is not evidence that something was removed.
    """
    return [
        f"{row.get('acceptance', '?')}: {row.get('summary', '')}"
        for row in rows
        if row.get("result") != CLEANUP_OBSERVED
    ]


def cleanup_blocked(rows: Iterable[Mapping[str, str]]) -> list[str]:
    """The cleanup rows the environment made impossible, each carrying the error that says why.

    Reported apart because it is an owner or infrastructure decision rather than a lane defect —
    ``dynamodb:Scan`` on the Stage 2 inventory table is denied to the QA identity, for instance.
    Still counted by :func:`cleanup_problems`, so it never passes for a removal.
    """
    return [
        f"{row.get('acceptance', '?')}: {row.get('summary', '')}"
        for row in rows
        if row.get("result") == CLEANUP_BLOCKED
    ]


class CleanupBlocked(RuntimeError):
    """A cleanup step the environment made impossible rather than refused.

    Raised by a step that cannot run at all — a table the fixture identity is denied ``Scan`` on,
    for example — so the verdict says "not met, and here is the error" instead of either passing for
    a removal or failing the lane for something its own code did wrong.
    """


def run_cleanup_step(acceptance: str, action: Callable[[], str]) -> dict[str, str]:
    """Run one cleanup step and turn every refusal or unmet read-back into a verdict.

    This is the whole reason a teardown can be trusted.  A step that raises — a mutation the server
    refused, a read-back that still answers the row it was supposed to remove, a canary the sweep
    disturbed — comes back as ``failed``; a step the environment made impossible comes back as
    ``blocked``.  Neither is an ordinary observation, and :func:`assert_cleanup_clean` turns either
    into a failed run once the evidence is on disk.
    """
    try:
        return cleanup_row(acceptance, action())
    except CleanupBlocked as exc:
        return cleanup_row(acceptance, f"{type(exc).__name__}: {exc}", result=CLEANUP_BLOCKED)
    except Exception as exc:  # noqa: BLE001 - a failed cleanup step is a verdict, never a crash mid-teardown
        return cleanup_row(acceptance, f"{type(exc).__name__}: {exc}", result=CLEANUP_FAILED)


def assert_cleanup_clean(rows: Iterable[Mapping[str, str]], *, strict: bool | None = None) -> None:
    """Fail the run when a cleanup step failed, and when ``strict`` also when one was blocked.

    The lane writes its evidence before it calls this, so the record of a failed teardown exists and
    the run still turns red.  Before this shape a refused ``deleteOrder`` or a disturbed canary was
    filed as an observation and pytest exited 0, which is how a mandatory cleanup gate stops
    meaning anything.

    ``failed`` is always fatal: it is the lane's own work not done.  ``blocked`` is fatal only under
    ``SS_STRICT_CLEANUP=1``: it means the environment refused the step — ``dynamodb:Scan`` denied on a
    Stage 2 table, for instance — which the lane cannot fix by writing different code.  Either way the
    row is in the record, so a cleanup the run did not achieve is never presented as one it achieved.
    """
    if strict is None:
        strict = STRICT_CLEANUP
    failures = cleanup_failures(rows)
    blocked = cleanup_blocked(rows) if strict else []
    problems = failures + blocked
    if problems:
        raise StageTwoCleanupError(f"{len(problems)} §2.8.7 cleanup step(s) not met: " + "; ".join(problems))


#: The token kinds a lane may name.  The *shapes* live in ``TOKEN_SHAPES`` in ``scripts/qa_fixture.py``,
#: which is the one that refuses a token with no kind, or a partial one; this list is the vocabulary the lane
#: builds, and ``tests/unit/test_qa_fixture.py`` fails if the two ever disagree.
LANE_TOKEN_KINDS: tuple[str, ...] = ("data-id", "unit", "unit-campaign", "campaign", "profile", "order", "join-code")


def fixture_sweep(tokens: Sequence[str]) -> tuple[int, list[str], list[str]]:
    """Run the sanctioned fixture sweeper over these typed lane tokens and split its report.

    The lane names what it created by kind — its ``DATA_ID``, the Unit, Unit Campaign and Scout Campaign
    ids it was answered, its seller profile, the join codes it minted, the Orders it sold — and
    ``scripts/qa_fixture.py`` checks each against the stored shape of that kind before reading a table.
    The sweeper then applies one reviewed rule per key shape, deletes what a rule says belongs to this
    lane, re-scans, and reports what survived (``LEFT``), what a rule refused (``kept``: another
    tenant's grant, membership, custody or marker on a partition this lane named, a guard whose Scout
    Campaign no token names exactly, and the lane's own append-only movement history), and what it could
    not read (``BLOCKED``).  Nothing here removes a row directly.

    Returns:
        ``(exit code, blocked lines, report lines)``.  Exit code 0 means every row a rule called this
        lane's was deleted and the re-scan found none of them left.  A ``BLOCKED`` line names a table the
        fixture identity cannot read together with the action it is denied — measured on dev on
        2026-11-19, ``kernelworx-inventory-ue1-dev``, ``kernelworx-orders-ue1-dev`` and
        ``kernelworx-order-fulfillments-ue1-dev`` all deny ``dynamodb:Scan`` (and ``dynamodb:DeleteItem``)
        to ``kernelworx-qa-ue1-dev`` — which is an owner or infrastructure decision, not something the
        lane can code around.
    """
    argv = [sys.executable, str(QA_FIXTURE_SCRIPT), "sweep", "--yes"]
    for token in tokens:
        argv += ["--lane", token]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    lines = [line.strip() for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    blocked = [line for line in lines if line.startswith("BLOCKED")]
    return done.returncode, blocked, lines


# ---------------------------------------------------------------------------
# Documents: one per endpoint, verbatim, sending the arguments the suite needs.
# ---------------------------------------------------------------------------

_POSITIONS = """
query StageTwoPositions($unitCampaignId: ID!) {
  inventoryPositions(unitCampaignId: $unitCampaignId) {
    items {
      unitCampaignId
      productId
      kernelPhysicalQty
      soldInPossessionQty
      councilOnOrderQty
      sellableKernelQty
      assignedOpenQty
      unassignedKernelQty
      assignmentOverageQty
      withScoutQty
      totalUnitOwnedUndeliveredQty
      version
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

_MOVEMENTS = """
query StageTwoMovements($unitCampaignId: ID!) {
  inventoryMovements(unitCampaignId: $unitCampaignId, page: {limit: 100}) {
    items {
      movementId
      productId
      movementType
      kernelPhysicalDelta
      soldPossessionDelta
      withScoutDelta
      assignedDelta
      councilOnOrderDelta
      profileId
      orderId
      fulfillmentId
      reason
      actorAccountId
      occurredAt
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

_CUSTODY = """
query StageTwoCustody($unitCampaignId: ID!) {
  scoutCustodyBalances(unitCampaignId: $unitCampaignId, page: {limit: 100}) {
    items {
      unitCampaignId
      productId
      profileId
      campaignId
      withScoutQty
      version
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

_MY_CUSTODY = """
query StageTwoMyCustody($unitCampaignId: ID!, $profileId: ID!) {
  myScoutCustody(unitCampaignId: $unitCampaignId, profileId: $profileId) {
    productId
    profileId
    campaignId
    withScoutQty
    version
  }
}
""".strip()

_FULFILLMENTS = """
query StageTwoFulfillments($orderId: ID!) {
  orderFulfillments(orderId: $orderId, page: {limit: 50}) {
    items {
      fulfillmentId
      orderId
      unitId
      unitCampaignId
      campaignId
      profileId
      lineItemId
      productId
      recordType
      quantity
      source
      inventoryMovementId
      reversalOfFulfillmentId
      actorAccountId
      createdAt
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

_SCOUT_ORDERS = """
query StageTwoScoutOrders($unitCampaignId: ID!, $campaignId: ID!) {
  unitScoutCampaignOrders(unitCampaignId: $unitCampaignId, campaignId: $campaignId, page: {limit: 50}) {
    items {
      orderId
      profileId
      campaignId
      unitId
      unitCampaignId
      customerName
      fulfillmentVersion
      lineItems {
        lineItemId
        productId
        quantity
        fulfilledQuantity
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

#: One ``InventoryPosition`` selection, reused by every write that answers a position.
_POSITION_BODY = (
    "unitCampaignId productId kernelPhysicalQty soldInPossessionQty councilOnOrderQty version "
    "sellableKernelQty assignedOpenQty unassignedKernelQty assignmentOverageQty withScoutQty "
    "totalUnitOwnedUndeliveredQty"
)

#: Each Stage 2 mutation selects what the SDL says that mutation answers, which is the row it
#: changed rather than a status: ``recordInventoryReceipt``, ``adjustInventory`` and
#: ``adjustCouncilOnOrder`` answer one ``InventoryPosition``; ``issueStockToScout`` answers the
#: position and the custody balance it moved; ``returnStockFromScout`` answers both lists;
#: ``fulfillIndividualOrderLine`` answers the Order, the fulfillment record and the position; and
#: ``createOrder`` answers the legacy ``Order`` itself.  A movement id is in none of those payloads,
#: so the suite proves the audit trail by reading ``inventoryMovements`` after each write.
_WRITE_SELECTIONS: dict[str, str] = {
    "recordInventoryReceipt": _POSITION_BODY,
    "adjustInventory": _POSITION_BODY,
    "adjustCouncilOnOrder": _POSITION_BODY,
    "issueStockToScout": (
        "inventoryPosition { " + _POSITION_BODY + " } "
        "custodyBalance { unitCampaignId productId profileId campaignId withScoutQty version }"
    ),
    "returnStockFromScout": (
        "inventoryPositions { " + _POSITION_BODY + " } "
        "custodyBalances { unitCampaignId productId profileId campaignId withScoutQty version }"
    ),
    "fulfillIndividualOrderLine": (
        "order { orderId campaignId unitCampaignId fulfillmentVersion "
        "lineItems { lineItemId productId quantity fulfilledQuantity } } "
        "fulfillment { fulfillmentId orderId unitCampaignId campaignId lineItemId productId recordType quantity "
        "source inventoryMovementId actorAccountId } "
        "inventoryPosition { " + _POSITION_BODY + " }"
    ),
    "reverseIndividualOrderFulfillment": (
        "order { orderId campaignId unitCampaignId fulfillmentVersion "
        "lineItems { lineItemId productId quantity fulfilledQuantity } } "
        "reversal { fulfillmentId orderId unitCampaignId recordType quantity source inventoryMovementId "
        "reversalOfFulfillmentId actorAccountId } "
        "inventoryPosition { " + _POSITION_BODY + " }"
    ),
    "createOrder": (
        "orderId profileId campaignId unitId unitCampaignId fulfillmentVersion totalAmount "
        "lineItems { lineItemId productId quantity fulfilledQuantity }"
    ),
}

#: Mutation → (its input type, its document).  Built from one table so a Stage 2 write cannot be
#: added to the suite with an ad-hoc query string.
_WRITE_INPUT_TYPES: dict[str, str] = {
    "recordInventoryReceipt": "RecordInventoryReceiptInput",
    "adjustInventory": "AdjustInventoryInput",
    "adjustCouncilOnOrder": "AdjustCouncilOnOrderInput",
    "issueStockToScout": "IssueStockToScoutInput",
    "returnStockFromScout": "ReturnStockFromScoutInput",
    "fulfillIndividualOrderLine": "FulfillIndividualOrderLineInput",
    "reverseIndividualOrderFulfillment": "ReverseIndividualOrderFulfillmentInput",
    "createOrder": "CreateOrderInput",
}

_MUTATIONS: dict[str, str] = {
    field: f"mutation StageTwo{field[0].upper()}{field[1:]}($input: {input_type}!) "
    f"{{ {field}(input: $input) {{ {_WRITE_SELECTIONS[field]} }} }}"
    for field, input_type in _WRITE_INPUT_TYPES.items()
}

#: The reads a Stage 2 lane needs that are not themselves Stage 2 fields: the catalog identity the
#: two Campaigns have to share, the products the campaign's inventory may name, and the removal the
#: ``ORD-API-02-04`` rejoin starts from.  They live here so the SDL check below covers them too —
#: an ad-hoc query string in the spec is the one place a rename would go unnoticed.
_CATALOG_IDENTITY = """
query StageTwoCampaignCatalog($unitCampaignId: ID!) {
  unitCampaign(unitCampaignId: $unitCampaignId) {
    unitCampaignId
    unitId
    campaignName
    catalogId
    isActive
  }
}
""".strip()

_SCOUT_CAMPAIGN_CATALOG = """
query StageTwoScoutCampaignCatalog($campaignId: ID!) {
  getCampaign(campaignId: $campaignId) {
    campaignId
    campaignName
    catalogId
    unitCampaignId
  }
}
""".strip()

_CATALOG_PRODUCTS = """
query StageTwoCatalogProducts($unitCampaignId: ID!) {
  unitCampaignCatalog(unitCampaignId: $unitCampaignId) {
    catalogId
    catalogName
    products {
      productId
      productName
      price
    }
  }
}
""".strip()

_SCOUT_CAMPAIGNS = """
query StageTwoScoutCampaigns($profileId: ID!) {
  listCampaignsByProfile(profileId: $profileId, limit: 100) {
    campaigns {
      campaignId
      campaignName
      catalogId
      unitCampaignId
      isActive
    }
  }
}
""".strip()

#: The catalog a Stage 2 lane is allowed to build both Campaigns on.  It needs one catalog that
#: *both* identities can pick: the Unit Campaign's stock keys on its own ``catalogId`` while
#: ``createOrder`` prices the sale in the Scout Campaign's (WORK-161), so a lane whose two
#: Campaigns sit on different catalogs has its custody sale refused with no Order written.  The
#: create-campaign picker offers a caller their own catalogs plus ``listManagedCatalogs``, and that
#: query filters ``catalogType = ADMIN_MANAGED`` — measured on dev on 2026-11-18, a
#: ``createCatalog`` catalog is ``USER_CREATED`` and stays invisible to the other identity even
#: with ``isPublic: true``, while ``createManagedCatalog`` answers the Unit admin ``FORBIDDEN``
#: ("Admin access required").  So the lane reads the shared catalog the stack already carries
#: rather than creating one, and skips with those words when the stack carries none.
_MANAGED_CATALOGS = """
query StageTwoManagedCatalogs {
  listManagedCatalogs {
    catalogId
    catalogName
    catalogType
    isPublic
    products {
      productId
      productName
      price
      sortOrder
    }
  }
}
""".strip()

#: The admin's roster read for this lane: ``scoutCampaignCatalogId`` is what lets the suite compare
#: the two catalogs before sending a sale the server would refuse (WORK-161), and ``version`` /
#: ``guardVersion`` are what ``removeUnitCampaignMembership`` conditions on.
_ROSTER = """
query StageTwoRoster($unitCampaignId: ID!) {
  unitCampaignRoster(unitCampaignId: $unitCampaignId, page: {limit: 50}) {
    items {
      unitCampaignId
      unitId
      campaignId
      profileId
      scoutName
      campaignName
      scoutCampaignCatalogId
      status
      version
      guardVersion
    }
  }
}
""".strip()

_REMOVE_MEMBERSHIP = """
mutation StageTwoRemoveMembership($input: RemoveUnitCampaignMembershipInput!) {
  removeUnitCampaignMembership(input: $input) {
    profileId
    campaignId
    unitCampaignId
    status
    version
    guardVersion
  }
}
""".strip()

# --- The lane's own lifecycle: the second Unit Campaign, the READ-only share, the teardown ----

_UNIT_CAMPAIGNS = """
query StageTwoUnitCampaigns($unitId: ID!) {
  unitCampaigns(unitId: $unitId, page: {limit: 50}) {
    items {
      unitCampaignId
      unitId
      campaignName
      campaignYear
      catalogId
      joinCode
      isActive
      version
    }
  }
}
""".strip()

_MY_UNITS = """
query StageTwoMyUnits($page: PageInput) {
  myUnits(page: $page) {
    items {
      unitId
      unitType
      unitNumber
      displayName
      version
    }
  }
}
""".strip()

_SHARE_READ = """
mutation StageTwoShareRead($input: ShareProfileDirectInput!) {
  shareProfileDirect(input: $input) {
    shareId
    profileId
    targetAccountId
    permissions
  }
}
""".strip()

_SHARES = """
query StageTwoShares($profileId: ID!) {
  listSharesByProfile(profileId: $profileId) {
    shareId
    profileId
    targetAccountId
    permissions
  }
}
""".strip()

_REVOKE_SHARE = """
mutation StageTwoRevokeShare($input: RevokeShareInput!) {
  revokeShare(input: $input)
}
""".strip()

_DELETE_CAMPAIGN = """
mutation StageTwoDeleteCampaign($campaignId: ID!) {
  deleteCampaign(campaignId: $campaignId)
}
""".strip()

_DELETE_PROFILE = """
mutation StageTwoDeleteProfile($profileId: ID!) {
  deleteSellerProfile(profileId: $profileId)
}
""".strip()

_DELETE_ORDER = """
mutation StageTwoDeleteOrder($orderId: ID!) {
  deleteOrder(orderId: $orderId)
}
""".strip()

_PROFILES = """
query StageTwoProfiles($limit: Int) {
  listMyProfiles(limit: $limit) {
    profiles {
      profileId
      sellerName
      isOwner
    }
  }
}
""".strip()

_SCOUT_CAMPAIGN = """
query StageTwoScoutCampaign($campaignId: ID!) {
  getCampaign(campaignId: $campaignId) {
    campaignId
    campaignName
    isActive
  }
}
""".strip()

_DEACTIVATE_UNIT_CAMPAIGN = """
mutation StageTwoDeactivateUnitCampaign($input: UpdateUnitCampaignInput!) {
  updateUnitCampaign(input: $input) {
    unitCampaignId
    unitId
    campaignName
    isActive
    version
  }
}
""".strip()


#: Field → the document the suite sends for it.  The read documents spell out every field the
#: acceptance assertions read, so a projection that stops answering one fails the run instead of
#: reading as a zero.
STAGE_TWO_DOCUMENTS: dict[str, str] = {
    "inventoryPositions": _POSITIONS,
    "inventoryMovements": _MOVEMENTS,
    "scoutCustodyBalances": _CUSTODY,
    "myScoutCustody": _MY_CUSTODY,
    "orderFulfillments": _FULFILLMENTS,
    "unitScoutCampaignOrders": _SCOUT_ORDERS,
    **_MUTATIONS,
}

#: Documents for the Stage 2 lane's non-Stage-2 calls, keyed by what the lane uses them for.
STAGE_TWO_SUPPORT_DOCUMENTS: dict[str, str] = {
    "campaignCatalogIdentity": _CATALOG_IDENTITY,
    "managedCatalogs": _MANAGED_CATALOGS,
    "scoutCampaignCatalog": _SCOUT_CAMPAIGN_CATALOG,
    "catalogProducts": _CATALOG_PRODUCTS,
    "scoutCampaigns": _SCOUT_CAMPAIGNS,
    "unitCampaigns": _UNIT_CAMPAIGNS,
    "myUnits": _MY_UNITS,
    "roster": _ROSTER,
    "removeMembership": _REMOVE_MEMBERSHIP,
    "shareRead": _SHARE_READ,
    "shares": _SHARES,
    "revokeShare": _REVOKE_SHARE,
    "deleteCampaign": _DELETE_CAMPAIGN,
    "deleteProfile": _DELETE_PROFILE,
    "deleteOrder": _DELETE_ORDER,
    "profiles": _PROFILES,
    "scoutCampaign": _SCOUT_CAMPAIGN,
    "deactivateUnitCampaign": _DEACTIVATE_UNIT_CAMPAIGN,
}

#: Which builder feeds which mutation, so the SDL check covers the payload keys as well.
_BUILDERS: dict[str, tuple[Callable[..., dict[str, Any]], str]] = {
    "recordInventoryReceipt": (receipt_input, "RecordInventoryReceiptInput"),
    "adjustInventory": (adjust_input, "AdjustInventoryInput"),
    "adjustCouncilOnOrder": (council_on_order_input, "AdjustCouncilOnOrderInput"),
    "issueStockToScout": (issue_input, "IssueStockToScoutInput"),
    "returnStockFromScout": (return_input, "ReturnStockFromScoutInput"),
    "fulfillIndividualOrderLine": (fulfill_input, "FulfillIndividualOrderLineInput"),
    "reverseIndividualOrderFulfillment": (reverse_input, "ReverseIndividualOrderFulfillmentInput"),
    "createOrder": (custody_sale_input, "CreateOrderInput"),
    "removeUnitCampaignMembership": (remove_membership_input, "RemoveUnitCampaignMembershipInput"),
    "shareProfileDirect": (share_read_input, "ShareProfileDirectInput"),
    "revokeShare": (revoke_share_input, "RevokeShareInput"),
    "updateUnitCampaign": (deactivate_unit_campaign_input, "UpdateUnitCampaignInput"),
}

#: One call per builder, with contract-shaped arguments, so its keys can be compared to its type.
_SAMPLES: dict[str, dict[str, Any]] = {
    "RecordInventoryReceiptInput": receipt_input("UC#x", "PROD#x", 4, idempotency_key="k"),
    "AdjustInventoryInput": adjust_input("UC#x", "PROD#x", -1, "Gift to an outgoing volunteer", idempotency_key="k"),
    "AdjustCouncilOnOrderInput": council_on_order_input("UC#x", "PROD#x", 3, idempotency_key="k"),
    "IssueStockToScoutInput": issue_input("UC#x", "CAMP#x", "PROFILE#x", "PROD#x", 4, idempotency_key="k"),
    "ReturnStockFromScoutInput": return_input(
        "UC#x", "CAMP#x", "PROFILE#x", [{"productId": "PROD#x", "quantity": 2}], idempotency_key="k"
    ),
    "FulfillIndividualOrderLineInput": fulfill_input("ORDER#x", "line-1", 1, 0, idempotency_key="k"),
    "ReverseIndividualOrderFulfillmentInput": reverse_input("ORDER#x", "Fulfillment#x", 1, idempotency_key="k"),
    "CreateOrderInput": custody_sale_input("PROFILE#x", "CAMP#x", "PROD#x", 3, "Taylor Door", idempotency_key="k"),
    "RemoveUnitCampaignMembershipInput": remove_membership_input("UC#x", "CAMP#x", 1, 2, idempotency_key="k"),
    "ShareProfileDirectInput": share_read_input("PROFILE#x", "scout@example.test"),
    "RevokeShareInput": revoke_share_input("PROFILE#x", "ACCOUNT#x"),
    "UpdateUnitCampaignInput": deactivate_unit_campaign_input("UC#x", 1, idempotency_key="k"),
}


# ---------------------------------------------------------------------------
# The SDL contract
# ---------------------------------------------------------------------------


def _block_body(sdl: str, keyword: str, name: str) -> str:
    """One ``type``/``input`` block's body from the SDL, or an empty string."""
    match = re.search(rf"\n{keyword} {name} \{{(.*?)\n\}}\n", sdl, re.DOTALL)
    return match.group(1) if match else ""


def _field_exists(sdl: str, type_name: str, field: str) -> bool:
    """Whether *type_name* declares *field*."""
    return re.search(rf"\n  {field}\(", _block_body(sdl, "type", type_name)) is not None


def _field_arguments(sdl: str, type_name: str, field: str) -> set[str]:
    """Top-level argument names *type_name* declares for *field*."""
    return _call_fragment_arguments(_strip_doc_comments(_block_body(sdl, "type", type_name)), field)


def _strip_doc_comments(text: str) -> str:
    """Remove SDL doc comments, so prose can never read as an argument name.

    The split is on the delimiter rather than a non-greedy match because a GraphQL block string may
    contain a plain double quote — the ``Campaign.campaignName`` comment says ``(for example "Fall"
    or "Spring")``, which ends a naive match early and leaves the rest of the sentence looking like
    field declarations.
    """
    parts = text.split('"""')
    return "".join(parts[index] for index in range(0, len(parts), 2))


def _top_level_names(fragment: str) -> set[str]:
    """``name:`` pairs sitting at the top level of one parenthesised fragment.

    Depth matters: ``page: {limit: 100}`` sends ``page`` and says nothing about ``limit``, which
    belongs to ``PageInput`` and is checked where its own type is declared.
    """
    names: set[str] = set()
    depth = 0
    for match in re.finditer(r"(\{|\}|\(|\)|(\w+)\s*:)", fragment):
        symbol = match.group(1)
        if symbol in "{(":
            depth += 1
        elif symbol in "})":
            depth -= 1
        elif depth == 0:
            names.add(match.group(2))
    return names


def _input_member_names(sdl: str, type_name: str) -> set[str]:
    """Member names of one SDL ``input`` type."""
    body = _strip_doc_comments(_block_body(sdl, "input", type_name))
    return set(re.findall(r"^\s{2}(\w+):", body, re.MULTILINE))


def _document_arguments(document: str, field: str) -> set[str]:
    """Argument names one document passes at its call of *field*."""
    return _call_fragment_arguments(document, field)


def _call_fragment_arguments(text: str, field: str) -> set[str]:
    """Top-level argument names of the first call of *field* in *text*."""
    match = re.search(rf"\b{field}\(", text)
    if not match:
        return set()
    open_at = text.index("(", match.start())
    depth = 0
    for position in range(open_at, len(text)):
        if text[position] == "(":
            depth += 1
        elif text[position] == ")":
            depth -= 1
            if depth == 0:
                return _top_level_names(text[open_at + 1 : position])
    return set()


_TYPE_BLOCK = re.compile(
    r"\n(?:type|input) (\w+)(?: implements [^{]+?)?(?: @[^\s{]+(?:\([^)]*\))?)* \{(.*?)\n\}\n",
    re.DOTALL,
)
_FIELD_LINE = re.compile(r"\n  (\w+)\s*(?:\([^)]*\))?\s*:\s*([^\n]+)")


def _unwrap_type(declaration: str) -> str:
    """The object type name a SDL field returns, with wrappers and directives removed.

    ``listManagedCatalogs: [Catalog!]! @cache(...)`` declares a directive after the type, and a
    directive attached to a field name is not part of the type's name — read as one, it would make
    a real field look like a type the SDL does not define.
    """
    return declaration.split("@", 1)[0].replace("[", "").replace("]", "").replace("!", "").strip()


def _type_member_map(sdl: str) -> dict[str, dict[str, str]]:
    """Every ``type``/``input`` in the SDL, mapped to its members and their declared return types."""
    types: dict[str, dict[str, str]] = {}
    for match in _TYPE_BLOCK.finditer(sdl):
        body = _strip_doc_comments(match.group(2))
        types[match.group(1)] = {field.group(1): _unwrap_type(field.group(2)) for field in _FIELD_LINE.finditer(body)}
    return types


def _document_tokens(document: str) -> list[str]:
    """A GraphQL document as structural tokens: names, braces, spreads; argument lists removed."""
    tokens: list[str] = []
    position = 0
    while position < len(document):
        character = document[position]
        if character.isspace():
            position += 1
        elif character == "(":
            depth = 0
            while position < len(document):
                if document[position] == "(":
                    depth += 1
                elif document[position] == ")":
                    depth -= 1
                    if depth == 0:
                        position += 1
                        break
                position += 1
        elif character in "{}":
            tokens.append(character)
            position += 1
        elif document.startswith("...", position):
            tokens.append("...")
            position += 3
        else:
            match = re.match(r"[\w$]+", document[position:])
            if match is None:
                position += 1
                continue
            tokens.append(match.group(0))
            position += len(match.group(0))
    return tokens


def _selection_tree(document: str) -> list[tuple[str, list[tuple[str, Any]]]]:
    """The top-level selection set of one document, as ``(field, nested)`` pairs.

    Only what the check needs is parsed: one operation, one root field, and the nested selection
    sets below it.  Variable definitions and argument lists are removed as tokens, so an argument
    name can never be read as a selected field.
    """
    tokens = _document_tokens(document)
    root_index = 0
    while root_index < len(tokens) and tokens[root_index] != "{":
        root_index += 1

    def parse(index: int) -> tuple[list[tuple[str, Any]], int]:
        selections: list[tuple[str, Any]] = []
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                return selections, index + 1
            if token in "{":
                nested, index = parse(index + 1)
                if selections:
                    name, _existing = selections[-1]
                    selections[-1] = (name, nested)
                continue
            if token in ("...", "}"):
                index += 1
                continue
            name = token
            index += 1
            if index < len(tokens) and tokens[index] == ":":
                name, index = tokens[index + 1], index + 2
            selections.append((name, []))
        return selections, index

    selections, _ = parse(root_index + 1)
    return [(name, nested) for name, nested in selections]


def _check_selections(
    selections: list[tuple[str, Any]],
    type_name: str,
    types: Mapping[str, Mapping[str, str]],
    path: str,
    violations: list[str],
) -> None:
    """Walk one selection set against *type_name*, naming every field the SDL does not declare."""
    members = types.get(type_name)
    if members is None:
        violations.append(f"{path}: {type_name} is not an object type in the SDL")
        return
    for field, nested in selections:
        reported = f"{path}.{field}".lstrip(".")
        if field not in members:
            violations.append(f"{reported}: {type_name} declares no {field}")
            continue
        if not nested:
            continue
        _check_selections(nested, members[field], types, reported, violations)


def stage_two_selection_violations(sdl: str) -> list[str]:
    """Every field the Stage 2 documents select that this SDL does not declare.

    The argument-level check is not enough on its own: ``inventoryPositions`` answers a connection,
    so a document that selects ``positions`` where the SDL says ``items``, or asks
    ``recordInventoryReceipt`` for a ``movementId`` its payload does not carry, is a document that
    fails at AppSync parse time — partway through a live lane, after the writes it precedes.

    Args:
        sdl: SDL text, normally ``tofu/application/schema/schema.graphql``.

    Returns:
        One sentence per field the SDL does not declare, naming the document's path to it.
    """
    types = _type_member_map(sdl)
    violations: list[str] = []
    for document in {**STAGE_TWO_DOCUMENTS, **STAGE_TWO_SUPPORT_DOCUMENTS}.values():
        root = "Mutation" if document.startswith("mutation") else "Query"
        _check_selections(_selection_tree(document), root, types, "", violations)
    return violations


def stage_two_contract_violations(sdl: str) -> list[str]:
    """Every way the shipped SDL and the Stage 2 suite's documents and payloads disagree.

    An empty list means the suite can be sent to this API: each Stage 2 field exists, every
    argument its document passes is declared, and every key an input builder puts in a payload is
    a member of the SDL input type that field takes.

    Args:
        sdl: SDL text, normally ``tofu/application/schema/schema.graphql``.

    Returns:
        One sentence per disagreement, naming the field and what is missing.
    """
    violations: list[str] = []
    for field, document in STAGE_TWO_DOCUMENTS.items():
        if not (_field_exists(sdl, "Query", field) or _field_exists(sdl, "Mutation", field)):
            violations.append(f"{field}: the SDL declares no such field")
            continue
        declared = _field_arguments(sdl, "Query", field) | _field_arguments(sdl, "Mutation", field)
        extra = sorted(_document_arguments(document, field) - declared)
        if extra:
            violations.append(f"{field}: the document sends {extra}, the SDL declares {sorted(declared)}")
    for field, (_builder, type_name) in _BUILDERS.items():
        members = _input_member_names(sdl, type_name)
        if not members:
            violations.append(f"{field}: the SDL declares no input type {type_name}")
            continue
        sample = _SAMPLES[type_name]
        unknown = sorted(key for key in sample if key not in members)
        if unknown:
            violations.append(f"{field}: the payload sends {unknown}, {type_name} declares {sorted(members)}")
    return violations


def missing_stage_two_endpoints(sdl: str) -> list[str]:
    """Stage 2 fields this SDL does not carry at all.

    A non-empty list is what lets a Stage 2 run say *stopped* rather than *passed*: the suite
    reports the endpoints the deployed build is missing and §2.8.5 stays open.
    """
    return [
        field
        for field in (*STAGE_TWO_WRITES, *STAGE_TWO_READS)
        if not (_field_exists(sdl, "Mutation", field) or _field_exists(sdl, "Query", field))
    ]


def stage_two_fields_in_schema(schema: Mapping[str, Any]) -> list[str]:
    """Which Stage 2 fields the deployed API's own introspection answers.

    Args:
        schema: the ``data`` object of ``query { __schema { queryType { fields { name } }
            mutationType { fields { name } } } }``.

    Returns:
        The Stage 2 names this API carries, in the order this module lists them.  A short list is
        what stops a live lane: the suite reports the endpoints the deployed build is missing
        instead of failing a step on an unknown field.
    """
    root = schema.get("__schema") or {}
    declared: set[str] = set()
    for root_type in ("queryType", "mutationType"):
        for field in (root.get(root_type) or {}).get("fields") or []:
            declared.add(str(field.get("name", "")))
    return [field for field in (*STAGE_TWO_WRITES, *STAGE_TWO_READS) if field in declared]


# ---------------------------------------------------------------------------
# What a persisted Stage 2 answer has to satisfy
# ---------------------------------------------------------------------------

#: Every §7 quantity a position answer carries, and the §5.2 formula behind each one that is
#: derived rather than stored.  The first three formulas are the ones a reader argues about, so
#: the violation message quotes them.
_STORED_QUANTITIES: tuple[str, ...] = (
    "kernelPhysicalQty",
    "soldInPossessionQty",
    "councilOnOrderQty",
)
_DERIVED_QUANTITIES: tuple[str, ...] = (
    "sellableKernelQty",
    "assignedOpenQty",
    "unassignedKernelQty",
    "assignmentOverageQty",
    "withScoutQty",
    "totalUnitOwnedUndeliveredQty",
)
_FORMULA_TEXT: dict[str, str] = {
    "sellableKernelQty": "sellable = physical - sold-in-possession",
    "unassignedKernelQty": "unassigned = max(0, sellable - assigned)",
    "assignmentOverageQty": "overage = max(0, assigned - sellable)",
    "totalUnitOwnedUndeliveredQty": "unit-owned total = physical + with-scout",
}


def position_arithmetic_violations(positions: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every §5.2 formula an ``inventoryPositions`` answer breaks.

    Args:
        positions: the ``positions`` items of one answer.

    Returns:
        One sentence per broken formula, naming the product and quoting the numbers.
    """
    violations: list[str] = []
    wanted = (*_STORED_QUANTITIES, *_DERIVED_QUANTITIES)
    for position in positions:
        product_id = str(position.get("productId", "<unknown product>"))
        missing = [key for key in wanted if position.get(key) is None]
        if missing:
            violations.append(f"{product_id}: the answer carries no {missing}")
            continue
        physical = int(position["kernelPhysicalQty"])
        sold_here = int(position["soldInPossessionQty"])
        assigned = int(position["assignedOpenQty"])
        with_scout = int(position["withScoutQty"])
        sellable = physical - sold_here
        expected = {
            "sellableKernelQty": sellable,
            "unassignedKernelQty": max(0, sellable - assigned),
            "assignmentOverageQty": max(0, assigned - sellable),
            "totalUnitOwnedUndeliveredQty": physical + with_scout,
        }
        for key, want in expected.items():
            if int(position[key]) != want:
                numbers = {key: position[key] for key in wanted}
                violations.append(
                    f"{product_id}: {key}={position[key]}, {_FORMULA_TEXT[key]} says {want} for {numbers}"
                )
    return violations


def custody_by_product(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Units in custody per product, from a ``scoutCustodyBalances`` or ``myScoutCustody`` answer.

    Args:
        rows: the custody items for one Scout.

    Returns:
        Product id to ``withScoutQty``; a product with no row is absent rather than zero, because
        "no row" and "a row at zero" are different answers from the deployed read.
    """
    totals: dict[str, int] = {}
    for row in rows:
        product_id = str(row.get("productId", ""))
        if not product_id:
            continue
        totals[product_id] = totals.get(product_id, 0) + int(row.get("withScoutQty") or 0)
    return totals


def _movement_matches(row: Mapping[str, Any], want: Mapping[str, Any]) -> bool:
    """Does one trail row satisfy one expectation?  Only the named keys have to agree."""
    return all(key in row and row[key] == value for key, value in want.items())


def movement_trail_violations(
    movements: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Every expected movement this trail does not hold exactly once, and every trail gap.

    An expectation names ``movementType`` plus whichever of the §5.8 delta columns, ``productId``,
    ``profileId``, ``orderId``, ``fulfillmentId`` and ``reason`` the caller cares about, and stays
    silent about the rest.  Each match is consumed once, which is what turns "the receipt wrote a
    movement" into "the receipt wrote exactly one movement".

    Args:
        movements: one lane's ``inventoryMovements`` items.
        expected: what the lane's writes owe the trail.

    Returns:
        One sentence per unsatisfied expectation, plus every leftover movement that names no
        actor or adjusts stock without a reason.
    """
    remaining = list(movements)
    violations: list[str] = []
    for want in expected:
        matches = [row for row in remaining if _movement_matches(row, want)]
        if not matches:
            violations.append(f"nothing in the trail matches {want}")
            continue
        if len(matches) > 1:
            violations.append(f"{len(matches)} movements match {want}: the write ran twice")
        remaining.remove(matches[0])
    for row in remaining:
        if not row.get("actorAccountId"):
            violations.append(f"movement {row.get('movementId', '<unknown>')} names no actor")
        if str(row.get("movementType")) == "STOCK_ADJUSTMENT" and not row.get("reason"):
            violations.append(f"stock adjustment {row.get('movementId', '<unknown>')} carries no reason")
    return violations


def council_need_positions(demand: int, sellable: int, unassigned: int) -> dict[str, int]:
    """Both RPT-06 Council Needs numbers for one product, which SS-SM-10 reads together.

    ``Physical-stock Council need = max(0, actual demand - sellable Kernel stock)`` and
    ``After-assignments Council need = max(0, actual demand - unassigned Kernel stock)``: the
    acceptance step requires both to be visible at once, whichever one the Unit prefers as primary.
    """
    return {
        "physicalStockNeed": max(0, demand - sellable),
        "afterAssignmentsNeed": max(0, demand - unassigned),
    }
