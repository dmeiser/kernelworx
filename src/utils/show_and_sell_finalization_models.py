"""Wave 6.1 (§5.1.1) — finalization records, immutable snapshots, credit, and the scoped total.

Delivery checklist §5.1.1; data model §5.16, §5.17, §5.18, §6.2, §6.4; spec §7 (SPLIT-02,
SPLIT-09, SPLIT-10), §11.1-11.2 (FIN-02..04, CASH-01..04).

This is the model layer every later finalization surface writes and reads through. It
owns five row kinds and the arithmetic that binds them, and it refuses — at build time,
before any storage sees a byte — every shape that would let a finalized event answer
two different money questions:

- **The finalization version** (:func:`build_finalization_row`): one row per approved
  version at ``FINALIZATION#<finalizationId>``. Business values are immutable after
  approval; only the lifecycle status moves (APPROVED → SUSPENDED or SUPERSEDED), and
  :func:`mark_finalization_suspended` / :func:`mark_finalization_superseded` are row
  transforms, not transitions — committing one is the reopen resolver's transaction
  (§5.3, a later card), which is why nothing here touches storage.
- **Immutable inputs.** A finalized report must reproduce the version exactly, so a
  version's sale, work, and return inputs are their own child rows (§6.4), copied in
  full rather than pointed at: :func:`build_sale_snapshot_row` refuses a sale row that
  is missing any line, buyer, payment, or revision fact (§5.16: "it is not a pointer to
  a mutable current sale"), and a later catalog rename or sale correction can never
  reach it because the copy is deep.
- **Cash reconciliation** (:func:`cash_reconciliation`): the CASH-03 chain —
  calculated, manual adjustment plus reason, adjusted, actual, discrepancy plus
  explanation — computed exactly, with the two explanations required by CASH-02 and
  CASH-04 refused when a nonzero amount would stand unexplained.
- **Credit arithmetic** (:func:`base_shares`, :func:`build_credit_row`). Shares round
  *down* to whole cents and the remainder stays visible as unassigned cents
  (SPLIT-10); the Kernel assigns those cents by hand, and
  :func:`validate_credit_set` is the invariant SPLIT-09 states — across all Scouts the
  approved allocations equal the whole-event pool exactly once.
- **The Unit-Campaign-scoped total** (:func:`apply_approved_credit`,
  :func:`reverse_approved_credit`, :func:`reconcile_total_with_credits`): one small
  projection per Scout Campaign per *Unit* Campaign (§5.18), never shared across Unit
  Campaigns, never negative, and provably equal to the approved allocation detail it
  summarizes.

Two things this module deliberately does not do: it never approves, suspends, or
supersedes a version *in storage* — the lifecycle transactions are §5.2 and §5.3 — and
it never persists credit for a preview (§5.17: "persisted only for a finalization
version; pending previews are computed from current sales/work"), so the credit
builders here are used by writers that carry them into a transaction, not by any read.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Tuple

from . import inventory_models
from .dynamodb import tables
from .errors import AppError, ErrorCode
from .pagination import query_all_items
from .show_and_sell_models import (
    CREDIT_SK_PREFIX,
    FINALIZATION_SK_PREFIX,
    SPLIT_METHOD_EQUAL,
    SPLIT_METHOD_TIME_WORKED,
    show_and_sell_pk,
)
from .show_and_sell_sale_models import (
    BUYER_EMAIL_ATTRIBUTE,
    BUYER_NAME_ATTRIBUTE,
    BUYER_PHONE_ATTRIBUTE,
    ENTERED_BY_ATTRIBUTE,
    LINE_ITEMS_ATTRIBUTE,
    MAX_SALE_REASON_LENGTH,
    PAYMENT_SNAPSHOT_ATTRIBUTE,
    REVISION_ATTRIBUTE,
    SALE_AT_ATTRIBUTE,
    SALE_ID_ATTRIBUTE,
    SALE_STATUS_ACTIVE,
    normalize_money_cents,
    normalize_sale_key_id,
)
from .unit_campaign_models import SCOUT_CAMPAIGN_PK_PREFIX, UNIT_CAMPAIGN_PK_PREFIX
from .unit_models import MAX_ID_LENGTH, normalize_optional_text, normalize_required_text

# --- Entity types and lifecycle vocabulary (data model §5.16, §5.17, §9) -----------

FINALIZATION_ENTITY_TYPE = "ShowAndSellFinalization"
RETURN_LINE_ENTITY_TYPE = "ShowAndSellFinalizationReturnLine"
SALE_SNAPSHOT_ENTITY_TYPE = "FinalizationSaleSnapshot"
WORK_SNAPSHOT_ENTITY_TYPE = "FinalizationWorkSnapshot"
CREDIT_ENTITY_TYPE = "ScoutSalesAllocation"
TOTAL_ENTITY_TYPE = "ScoutCampaignShowAndSellTotal"

#: The three states of one finalization *version* (§5.16, §9). ``APPROVED`` is the
#: point a version is born at (§5.2); ``SUSPENDED`` is what a reopen leaves behind
#: (§5.3), and ``SUPERSEDED`` is what re-finalization retires the prior version to.
FINALIZATION_STATUS_APPROVED = "APPROVED"
FINALIZATION_STATUS_SUSPENDED = "SUSPENDED"
FINALIZATION_STATUS_SUPERSEDED = "SUPERSEDED"
FINALIZATION_STATUSES: frozenset[str] = frozenset(
    {FINALIZATION_STATUS_APPROVED, FINALIZATION_STATUS_SUSPENDED, FINALIZATION_STATUS_SUPERSEDED}
)

#: The credit record's own lifecycle (§5.17), deliberately the same three words: a
#: Scout's credit moves exactly as the version that approved it moves, and a report
#: that sees ``APPROVED`` credit under a ``SUSPENDED`` version is a torn read, not a
#: third state.
ALLOCATION_STATUS_APPROVED = FINALIZATION_STATUS_APPROVED
ALLOCATION_STATUS_SUSPENDED = FINALIZATION_STATUS_SUSPENDED
ALLOCATION_STATUS_SUPERSEDED = FINALIZATION_STATUS_SUPERSEDED
ALLOCATION_STATUSES: frozenset[str] = FINALIZATION_STATUSES

# --- Key layout (data model §6.2, §6.4) --------------------------------------------

#: Sort-key markers between a finalization id and its child rows inside the event
#: partition. The finalization id itself carries no ``#`` (see
#: :func:`normalize_finalization_id`), which is what lets these markers scope the
#: children without a fixed-width id: ``FINALIZATION#f#SALE#s`` can only parse one way.
RETURN_SK_MARKER = "#RETURN#"
SALE_SNAPSHOT_SK_MARKER = "#SALE#"
WORK_SNAPSHOT_SK_MARKER = "#WORK#"

#: The scoped total's fixed sort key inside its composite partition key (§6.2).
SHOW_AND_SELL_TOTAL_SK = "SHOW_AND_SELL_TOTAL"

# --- Attribute names (§5.16, §5.17, §5.18) ------------------------------------------

FINALIZATION_ID_ATTRIBUTE = "finalizationId"
ALLOCATION_ID_ATTRIBUTE = "allocationId"
VERSION_NUMBER_ATTRIBUTE = "versionNumber"
WHOLE_POOL_CENTS_ATTRIBUTE = "wholePoolCents"
SPLIT_METHOD_ATTRIBUTE = "splitMethod"
RETURN_LINES_ATTRIBUTE = "returnLines"
CASH_ATTRIBUTE = "cash"
PREVIOUS_FINALIZATION_ID_ATTRIBUTE = "previousFinalizationId"
APPROVED_BY_ATTRIBUTE = "approvedByAccountId"
APPROVED_AT_ATTRIBUTE = "approvedAt"
SUSPENDED_BY_ATTRIBUTE = "suspendedByAccountId"
SUSPENDED_AT_ATTRIBUTE = "suspendedAt"
SUSPENSION_REASON_ATTRIBUTE = "suspensionReason"
SOURCE_EVENT_VERSION_ATTRIBUTE = "sourceEventVersion"

PRODUCT_ID_ATTRIBUTE = "productId"
ALLOCATED_QTY_ATTRIBUTE = "allocatedQty"
EXPECTED_QTY_ATTRIBUTE = "expectedQty"
ACTUAL_QTY_ATTRIBUTE = "actualQty"
VARIANCE_QTY_ATTRIBUTE = "varianceQty"
NET_STOCK_EFFECT_QTY_ATTRIBUTE = "netStockEffectQty"
RECONCILIATION_MOVEMENT_ID_ATTRIBUTE = "reconciliationMovementId"
REASON_ATTRIBUTE = "reason"
TOTAL_CENTS_ATTRIBUTE = "totalCents"

CALCULATED_EXPECTED_CENTS_ATTRIBUTE = "calculatedExpectedCents"
MANUAL_ADJUSTMENT_CENTS_ATTRIBUTE = "manualAdjustmentCents"
MANUAL_ADJUSTMENT_REASON_ATTRIBUTE = "manualAdjustmentReason"
ADJUSTED_EXPECTED_CENTS_ATTRIBUTE = "adjustedExpectedCents"
ACTUAL_CASH_CENTS_ATTRIBUTE = "actualCashCents"
DISCREPANCY_CENTS_ATTRIBUTE = "discrepancyCents"
DISCREPANCY_EXPLANATION_ATTRIBUTE = "discrepancyExplanation"

SLOT_ID_ATTRIBUTE = "slotId"
PROFILE_ID_ATTRIBUTE = "profileId"
CAMPAIGN_ID_ATTRIBUTE = "campaignId"
UNIT_CAMPAIGN_ID_ATTRIBUTE = "unitCampaignId"
SHOW_AND_SELL_ID_ATTRIBUTE = "showAndSellId"
ACTUAL_MINUTES_ATTRIBUTE = "actualMinutes"
SOURCE_SIGNUP_VERSION_ATTRIBUTE = "sourceSignupVersion"

BASE_AMOUNT_CENTS_ATTRIBUTE = "baseAmountCents"
ROUNDING_CREDIT_CENTS_ATTRIBUTE = "roundingCreditCents"
AMOUNT_CENTS_ATTRIBUTE = "amountCents"
STATUS_ATTRIBUTE = "status"
CREATED_AT_ATTRIBUTE = "createdAt"
UPDATED_AT_ATTRIBUTE = "updatedAt"
VERSION_ATTRIBUTE = "version"
APPROVED_AMOUNT_CENTS_ATTRIBUTE = "approvedAmountCents"

# --- Row-shape allowlists (same discipline as §5.10's EVENT_ROW_ATTRIBUTES) ---------

#: Every attribute a ``FINALIZATION#`` row may carry. An extra attribute would be a
#: fact the design never declares, so no read projects it and no test covers it.
FINALIZATION_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        FINALIZATION_ID_ATTRIBUTE,
        SHOW_AND_SELL_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        VERSION_NUMBER_ATTRIBUTE,
        STATUS_ATTRIBUTE,
        WHOLE_POOL_CENTS_ATTRIBUTE,
        SPLIT_METHOD_ATTRIBUTE,
        CASH_ATTRIBUTE,
        PREVIOUS_FINALIZATION_ID_ATTRIBUTE,
        APPROVED_BY_ATTRIBUTE,
        APPROVED_AT_ATTRIBUTE,
        SUSPENDED_BY_ATTRIBUTE,
        SUSPENDED_AT_ATTRIBUTE,
        SUSPENSION_REASON_ATTRIBUTE,
        SOURCE_EVENT_VERSION_ATTRIBUTE,
    }
)

RETURN_LINE_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        FINALIZATION_ID_ATTRIBUTE,
        PRODUCT_ID_ATTRIBUTE,
        ALLOCATED_QTY_ATTRIBUTE,
        EXPECTED_QTY_ATTRIBUTE,
        ACTUAL_QTY_ATTRIBUTE,
        VARIANCE_QTY_ATTRIBUTE,
        NET_STOCK_EFFECT_QTY_ATTRIBUTE,
        RECONCILIATION_MOVEMENT_ID_ATTRIBUTE,
        REASON_ATTRIBUTE,
    }
)

SALE_SNAPSHOT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        FINALIZATION_ID_ATTRIBUTE,
        SALE_ID_ATTRIBUTE,
        SALE_AT_ATTRIBUTE,
        BUYER_NAME_ATTRIBUTE,
        BUYER_PHONE_ATTRIBUTE,
        BUYER_EMAIL_ATTRIBUTE,
        ENTERED_BY_ATTRIBUTE,
        LINE_ITEMS_ATTRIBUTE,
        TOTAL_CENTS_ATTRIBUTE,
        PAYMENT_SNAPSHOT_ATTRIBUTE,
        REVISION_ATTRIBUTE,
    }
)

WORK_SNAPSHOT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        FINALIZATION_ID_ATTRIBUTE,
        SLOT_ID_ATTRIBUTE,
        PROFILE_ID_ATTRIBUTE,
        CAMPAIGN_ID_ATTRIBUTE,
        ACTUAL_MINUTES_ATTRIBUTE,
        SOURCE_SIGNUP_VERSION_ATTRIBUTE,
    }
)

CREDIT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        ALLOCATION_ID_ATTRIBUTE,
        FINALIZATION_ID_ATTRIBUTE,
        SHOW_AND_SELL_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        CAMPAIGN_ID_ATTRIBUTE,
        PROFILE_ID_ATTRIBUTE,
        ACTUAL_MINUTES_ATTRIBUTE,
        BASE_AMOUNT_CENTS_ATTRIBUTE,
        ROUNDING_CREDIT_CENTS_ATTRIBUTE,
        AMOUNT_CENTS_ATTRIBUTE,
        STATUS_ATTRIBUTE,
        CREATED_AT_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

TOTAL_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        CAMPAIGN_ID_ATTRIBUTE,
        PROFILE_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        APPROVED_AMOUNT_CENTS_ATTRIBUTE,
        VERSION_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

#: The six keys of the embedded cash map (§5.16), and nothing else.
CASH_MAP_KEYS: frozenset[str] = frozenset(
    {
        CALCULATED_EXPECTED_CENTS_ATTRIBUTE,
        MANUAL_ADJUSTMENT_CENTS_ATTRIBUTE,
        MANUAL_ADJUSTMENT_REASON_ATTRIBUTE,
        ADJUSTED_EXPECTED_CENTS_ATTRIBUTE,
        ACTUAL_CASH_CENTS_ATTRIBUTE,
        DISCREPANCY_CENTS_ATTRIBUTE,
        DISCREPANCY_EXPLANATION_ATTRIBUTE,
    }
)

# --- Errors ------------------------------------------------------------------------

#: A nonzero manual cash adjustment with no reason (CASH-02), or a nonzero
#: discrepancy with no explanation (CASH-04).
CASH_ADJUSTMENT_REASON_REQUIRED = "CASH_ADJUSTMENT_REASON_REQUIRED"
CASH_DISCREPANCY_EXPLANATION_REQUIRED = "CASH_DISCREPANCY_EXPLANATION_REQUIRED"
#: A reason or explanation that explains nothing: a blank attached to a zero amount is
#: the same smuggled ambiguity in the other direction — the record claims someone
#: accounted for something the arithmetic says did not happen.
CASH_REASON_WITHOUT_ADJUSTMENT = "CASH_REASON_WITHOUT_ADJUSTMENT"
CASH_EXPLANATION_WITHOUT_DISCREPANCY = "CASH_EXPLANATION_WITHOUT_DISCREPANCY"
#: Adjusted expected cash below zero: the adjustment is a correction of the count,
#: not a way to make the drawer owe money.
ADJUSTED_EXPECTED_NEGATIVE = "ADJUSTED_EXPECTED_NEGATIVE"
#: A stored cash map whose computed fields do not follow from its inputs.
CASH_ARITHMETIC_BROKEN = "CASH_ARITHMETIC_BROKEN"
#: A return variance on a first-finalization line was never given its linked
#: stock-only adjustment (FIN-03, INV-02/INV-03).
RETURN_VARIANCE_UNADJUSTED = "RETURN_VARIANCE_UNADJUSTED"
#: A stock-only adjustment linked where the arithmetic says nothing moved.
STOCK_ADJUSTMENT_WITHOUT_VARIANCE = "STOCK_ADJUSTMENT_WITHOUT_VARIANCE"
#: A snapshot source missing any input the version used (§5.16 completeness).
SNAPSHOT_INPUT_INCOMPLETE = "SNAPSHOT_INPUT_INCOMPLETE"
#: A version number below 1.
VERSION_NUMBER_INVALID = "VERSION_NUMBER_INVALID"
#: A rounding draft touching the same participant twice (§5.1.3: unique participants).
DUPLICATE_ROUNDING_PARTICIPANT = "DUPLICATE_ROUNDING_PARTICIPANT"
#: A rounding assignment for a profile that is not an eligible confirmed participant.
ROUNDING_PARTICIPANT_INELIGIBLE = "ROUNDING_PARTICIPANT_INELIGIBLE"
#: A rounding draft whose cents exceed the unassigned remainder (§7.2: sum ≤ unassigned).
ROUNDING_OVERSUM = "ROUNDING_OVERSUM"
#: Approved allocations that do not sum to the whole pool exactly (SPLIT-09).
CREDIT_POOL_MISMATCH = "CREDIT_POOL_MISMATCH"
#: A zero-minute participant under TIME_WORKED: §5.17 bars it, and a zero weight
#: would take a share of a pool the Scout did not work for.
TIME_WORKED_MINUTES_REQUIRED = "TIME_WORKED_MINUTES_REQUIRED"
#: The scoped total is missing where one was required to move.
TOTAL_NOT_FOUND = "TOTAL_NOT_FOUND"
#: A scope mismatch: a credit from one Unit Campaign applied to another's total
#: (§5.18: the projection is "never shared across Unit Campaigns").
TOTAL_SCOPE_MISMATCH = "TOTAL_SCOPE_MISMATCH"
#: Decrementing a total below zero — the projection carries the same non-negative
#: balance invariant as the inventory surface.
TOTAL_CREDIT_UNDERFLOW = "TOTAL_CREDIT_UNDERFLOW"
#: The current approved allocation detail and the projection disagree (DM-AC-08).
DETAIL_TOTAL_MISMATCH = "DETAIL_TOTAL_MISMATCH"
#: A finalization row asked for in a state the caller's operation does not accept.
FINALIZATION_STATE_INVALID = "FINALIZATION_STATE_INVALID"


def _invalid(field: str, rule: str) -> AppError:
    """One INVALID_INPUT rejection, spelled the same way everywhere in this module."""
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


def _refuse(code: str, message: str, **details: Any) -> NoReturn:
    """A refusal carrying its subcode; see the note in the sale model's ``_refuse``."""
    raise AppError(ErrorCode.CONFLICT, message, details={"subcode": code, **details})


# --- Identity ----------------------------------------------------------------------


def new_finalization_id() -> str:
    """A stable finalization-version identity, generated before the write (§5.16).

    A UUID rather than a counter, and with no ``#`` allowed in it at all: this id is
    the first segment of four different composite sort keys
    (``FINALIZATION#<id>``, ``...#RETURN#<product>``, ``...#SALE#<sale>``,
    ``...#WORK#<slot>#<profile>``, and ``CREDIT#<id>#<profile>``), so an empty or
    ``#``-bearing id would make one child key parse two ways.
    """
    return str(uuid.uuid4())


def new_allocation_id() -> str:
    """A stable credit identity (§5.17)."""
    return str(uuid.uuid4())


def normalize_finalization_id(value: Any, field: str = FINALIZATION_ID_ATTRIBUTE) -> str:
    """Validate a ``finalizationId``: a bare id with no ``#`` segment at all.

    Stricter than the sale ids on purpose (see :func:`new_finalization_id`): a sale id
    is always the *last`` segment of its key, so its internal ``#`` are harmless, while
    a finalization id always has child markers after it.
    """
    text = normalize_required_text(value, field, MAX_ID_LENGTH)
    if "#" in text:
        raise _invalid(field, "must not contain #")
    return text


def normalize_finalization_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate a ``FinalizationStatus`` (§5.16)."""
    if not isinstance(value, str) or value not in FINALIZATION_STATUSES:
        raise _invalid(field, f"must be one of {', '.join(sorted(FINALIZATION_STATUSES))}")
    return value


def normalize_allocation_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate an ``AllocationCreditStatus`` (§5.17)."""
    if not isinstance(value, str) or value not in ALLOCATION_STATUSES:
        raise _invalid(field, f"must be one of {', '.join(sorted(ALLOCATION_STATUSES))}")
    return value


def normalize_split_method(value: Any, field: str = SPLIT_METHOD_ATTRIBUTE) -> str:
    """Validate a ``SplitMethod`` — the same two methods the event row stores."""
    if not isinstance(value, str) or value not in {SPLIT_METHOD_EQUAL, SPLIT_METHOD_TIME_WORKED}:
        raise _invalid(field, f"must be one of {SPLIT_METHOD_EQUAL}, {SPLIT_METHOD_TIME_WORKED}")
    return value


def normalize_version_number(value: Any, field: str = VERSION_NUMBER_ATTRIBUTE) -> int:
    """A finalization version number: 1, 2, 3 ... (§5.16 "positive integer")."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _refuse(
            VERSION_NUMBER_INVALID,
            f"{field} must be a positive integer counting this event's approvals",
            field=field,
        )
    return value


def normalize_signed_cents(value: Any, field: str) -> int:
    """A signed integer cent amount, bounded by the same ceiling as money rows.

    Cash adjustments and discrepancies are signed (§5.16); pool, base, and amount
    fields go through :func:`~src.utils.show_and_sell_sale_models.normalize_money_cents`
    instead, which refuses a negative.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field, "must be an integer number of cents")
    if value > inventory_models.MAX_QUANTITY or value < -inventory_models.MAX_QUANTITY:
        raise _invalid(
            field, f"must be between {-inventory_models.MAX_QUANTITY} and {inventory_models.MAX_QUANTITY} cents"
        )
    return value


# --- Key builders (§6.2, §6.4) ------------------------------------------------------


def finalization_sk(finalization_id: str) -> str:
    """A version's sort key inside its event's partition."""
    return f"{FINALIZATION_SK_PREFIX}#{normalize_finalization_id(finalization_id)}"


def finalization_key(show_and_sell_id: str, finalization_id: str) -> Dict[str, str]:
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": finalization_sk(finalization_id)}


def return_line_sk(finalization_id: str, product_id: str) -> str:
    """One return line of one version (§6.4)."""
    return (
        f"{finalization_sk(finalization_id)}{RETURN_SK_MARKER}{normalize_sale_key_id(product_id, PRODUCT_ID_ATTRIBUTE)}"
    )


def return_line_key(show_and_sell_id: str, finalization_id: str, product_id: str) -> Dict[str, str]:
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": return_line_sk(finalization_id, product_id)}


def sale_snapshot_sk(finalization_id: str, sale_id: str) -> str:
    """One immutable sale-input child of one version (§6.4)."""
    return f"{finalization_sk(finalization_id)}{SALE_SNAPSHOT_SK_MARKER}{normalize_sale_key_id(sale_id, SALE_ID_ATTRIBUTE)}"


def sale_snapshot_key(show_and_sell_id: str, finalization_id: str, sale_id: str) -> Dict[str, str]:
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": sale_snapshot_sk(finalization_id, sale_id)}


def work_snapshot_sk(finalization_id: str, slot_id: str, profile_id: str) -> str:
    """One immutable per-slot work child of one version (§6.4)."""
    slot = normalize_sale_key_id(slot_id, SLOT_ID_ATTRIBUTE)
    profile = normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH)
    return f"{finalization_sk(finalization_id)}{WORK_SNAPSHOT_SK_MARKER}{slot}#{profile}"


def work_snapshot_key(show_and_sell_id: str, finalization_id: str, slot_id: str, profile_id: str) -> Dict[str, str]:
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": work_snapshot_sk(finalization_id, slot_id, profile_id)}


def credit_sk(finalization_id: str, profile_id: str) -> str:
    """One Scout's credit for one version (§6.4): ``CREDIT#<finalizationId>#<profileId>``."""
    profile = normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH)
    return f"{CREDIT_SK_PREFIX}#{normalize_finalization_id(finalization_id)}#{profile}"


def credit_key(show_and_sell_id: str, finalization_id: str, profile_id: str) -> Dict[str, str]:
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": credit_sk(finalization_id, profile_id)}


def total_key(unit_campaign_id: str, campaign_id: str) -> Dict[str, str]:
    """The scoped total's key on ``unit_campaigns`` (§6.2).

    The composite partition key — Unit Campaign *then* Scout Campaign — is what makes
    the §5.18 scope physical rather than a convention: there is no single key under
    which a cross-Unit-Campaign total could even be written.
    """
    unit = normalize_sale_key_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE)
    campaign = normalize_sale_key_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE)
    return {
        "pk": f"{UNIT_CAMPAIGN_PK_PREFIX}#{unit}#{SCOUT_CAMPAIGN_PK_PREFIX}#{campaign}",
        "sk": SHOW_AND_SELL_TOTAL_SK,
    }


# --- Cash reconciliation (§11.2, CASH-01..04, §5.16) --------------------------------


def cash_reconciliation(
    *,
    calculated_expected_cents: Any,
    manual_adjustment_cents: Any = 0,
    manual_adjustment_reason: Any = None,
    actual_cash_cents: Any,
    discrepancy_explanation: Any = None,
) -> Dict[str, Any]:
    """The embedded CASH-03 record, computed exactly and self-explained.

    Every number is derived here rather than accepted: ``adjusted = calculated +
    adjustment`` and ``discrepancy = actual - adjusted`` are recomputed from the two
    inputs the Kernel typed, so a client cannot send a discrepancy that its own
    numbers do not produce. The two explanations are required precisely when the
    amount they explain is nonzero (CASH-02, CASH-04), and refused when the amount is
    zero — a record that says someone accounted for a difference the arithmetic says
    did not happen is the same ambiguity, backwards.
    """
    calculated = normalize_money_cents(calculated_expected_cents, CALCULATED_EXPECTED_CENTS_ATTRIBUTE)
    adjustment = normalize_signed_cents(manual_adjustment_cents, MANUAL_ADJUSTMENT_CENTS_ATTRIBUTE)
    actual = normalize_money_cents(actual_cash_cents, ACTUAL_CASH_CENTS_ATTRIBUTE)
    adjusted = calculated + adjustment
    if adjusted < 0:
        _refuse(
            ADJUSTED_EXPECTED_NEGATIVE,
            "the expected-cash adjustment cannot take adjusted expected cash below zero",
            calculatedExpectedCents=calculated,
            manualAdjustmentCents=adjustment,
        )
    discrepancy = actual - adjusted
    reason = normalize_optional_text(
        manual_adjustment_reason, MANUAL_ADJUSTMENT_REASON_ATTRIBUTE, MAX_SALE_REASON_LENGTH
    )
    explanation = normalize_optional_text(
        discrepancy_explanation, DISCREPANCY_EXPLANATION_ATTRIBUTE, MAX_SALE_REASON_LENGTH
    )
    if adjustment != 0 and reason is None:
        _refuse(CASH_ADJUSTMENT_REASON_REQUIRED, "a nonzero expected-cash adjustment must carry its reason")
    if adjustment == 0 and reason is not None:
        _refuse(CASH_REASON_WITHOUT_ADJUSTMENT, "an expected-cash reason requires a nonzero adjustment")
    if discrepancy != 0 and explanation is None:
        _refuse(
            CASH_DISCREPANCY_EXPLANATION_REQUIRED,
            "a nonzero cash discrepancy must carry an explanation before approval (CASH-04)",
            discrepancyCents=discrepancy,
        )
    if discrepancy == 0 and explanation is not None:
        _refuse(CASH_EXPLANATION_WITHOUT_DISCREPANCY, "a cash explanation requires a nonzero discrepancy")
    return {
        CALCULATED_EXPECTED_CENTS_ATTRIBUTE: calculated,
        MANUAL_ADJUSTMENT_CENTS_ATTRIBUTE: adjustment,
        MANUAL_ADJUSTMENT_REASON_ATTRIBUTE: reason,
        ADJUSTED_EXPECTED_CENTS_ATTRIBUTE: adjusted,
        ACTUAL_CASH_CENTS_ATTRIBUTE: actual,
        DISCREPANCY_CENTS_ATTRIBUTE: discrepancy,
        DISCREPANCY_EXPLANATION_ATTRIBUTE: explanation,
    }


def validate_cash_reconciliation(cash: Mapping[str, Any]) -> Dict[str, Any]:
    """Re-check a stored cash map: the computed fields must follow from the inputs.

    A stored record carries all seven fields, so this reads the two *inputs* back
    through the same builder and refuses if a hand-written row disagrees with its own
    arithmetic — the "exact cash equations" the row invariants demand (§5.16).
    """
    if set(cash) != set(CASH_MAP_KEYS):
        raise _invalid(CASH_ATTRIBUTE, f"must carry exactly {', '.join(sorted(CASH_MAP_KEYS))}")
    recomputed = cash_reconciliation(
        calculated_expected_cents=cash[CALCULATED_EXPECTED_CENTS_ATTRIBUTE],
        manual_adjustment_cents=cash[MANUAL_ADJUSTMENT_CENTS_ATTRIBUTE],
        manual_adjustment_reason=cash[MANUAL_ADJUSTMENT_REASON_ATTRIBUTE],
        actual_cash_cents=cash[ACTUAL_CASH_CENTS_ATTRIBUTE],
        discrepancy_explanation=cash[DISCREPANCY_EXPLANATION_ATTRIBUTE],
    )
    if recomputed != dict(cash):
        _refuse(
            CASH_ARITHMETIC_BROKEN,
            "the stored cash record's adjusted and discrepancy values do not follow from its inputs",
        )
    return dict(cash)


# --- Return reconciliation line (§5.16, FIN-02..FIN-04) ------------------------------


def expected_return_qty(allocated_qty: Any, sold_qty: Any) -> int:
    """FIN-02's expected return: assigned quantity minus recorded immediate-handoff sales."""
    allocated = inventory_models.normalize_quantity(allocated_qty, ALLOCATED_QTY_ATTRIBUTE)
    sold = inventory_models.normalize_quantity(sold_qty, EXPECTED_QTY_ATTRIBUTE)
    if sold > allocated:
        _refuse(
            "SOLD_ABOVE_ALLOCATED",
            "recorded sales exceed the event's allocation; correct the sale before finalizing",
            allocatedQty=allocated,
            soldQty=sold,
        )
    return allocated - sold


def build_return_line_row(
    *,
    show_and_sell_id: str,
    finalization_id: str,
    product_id: Any,
    allocated_qty: Any,
    expected_qty: Any,
    actual_qty: Any,
    reconciliation_movement_id: Any = None,
    reason: Any = None,
    informational_variance: bool = False,
) -> Dict[str, Any]:
    """One immutable ``FINALIZATION#<id>#RETURN#<product>`` line (§5.16, §6.4).

    ``varianceQty`` and ``netStockEffectQty`` are derived, never supplied: variance is
    ``actual - expected`` (informational on a re-finalization version, where the stock
    delta is computed against the previous approved baseline by §5.3 instead), and the
    net physical effect the version had on the Unit is ``actual - allocated``. A first
    version's variance may only change stock through the linked stock-only adjustment
    (FIN-03, INV-02/INV-03): variance without one is refused, and an adjustment linked
    where the arithmetic says nothing moved is refused too.
    """
    allocated = inventory_models.normalize_quantity(allocated_qty, ALLOCATED_QTY_ATTRIBUTE)
    expected = inventory_models.normalize_quantity(expected_qty, EXPECTED_QTY_ATTRIBUTE)
    actual = inventory_models.normalize_quantity(actual_qty, ACTUAL_QTY_ATTRIBUTE)
    variance = actual - expected
    net_stock_effect = actual - allocated
    movement_id = normalize_optional_text(
        reconciliation_movement_id, RECONCILIATION_MOVEMENT_ID_ATTRIBUTE, MAX_ID_LENGTH
    )
    line_reason = normalize_optional_text(reason, REASON_ATTRIBUTE, MAX_SALE_REASON_LENGTH)
    if variance != 0 and not informational_variance and movement_id is None:
        _refuse(
            RETURN_VARIANCE_UNADJUSTED,
            "a return variance changes stock only through a linked stock-only adjustment with a reason (FIN-03)",
            productId=product_id,
            varianceQty=variance,
        )
    if (movement_id is not None or line_reason is not None) and variance == 0:
        _refuse(
            STOCK_ADJUSTMENT_WITHOUT_VARIANCE,
            "a stock-only adjustment requires a nonzero return variance",
            productId=product_id,
        )
    if movement_id is not None and line_reason is None:
        raise _invalid(REASON_ATTRIBUTE, "is required with a stock-only adjustment (INV-03)")
    return {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": return_line_sk(finalization_id, product_id),
        "entityType": RETURN_LINE_ENTITY_TYPE,
        FINALIZATION_ID_ATTRIBUTE: normalize_finalization_id(finalization_id),
        PRODUCT_ID_ATTRIBUTE: normalize_sale_key_id(product_id, PRODUCT_ID_ATTRIBUTE),
        ALLOCATED_QTY_ATTRIBUTE: allocated,
        EXPECTED_QTY_ATTRIBUTE: expected,
        ACTUAL_QTY_ATTRIBUTE: actual,
        VARIANCE_QTY_ATTRIBUTE: variance,
        NET_STOCK_EFFECT_QTY_ATTRIBUTE: net_stock_effect,
        RECONCILIATION_MOVEMENT_ID_ATTRIBUTE: movement_id,
        REASON_ATTRIBUTE: line_reason,
    }


# --- Immutable sale-input snapshot (§5.16, §6.4) -------------------------------------


def build_sale_snapshot_row(finalization_id: str, sale: Mapping[str, Any], *, show_and_sell_id: str) -> Dict[str, Any]:
    """Copy one active sale in full as ``FINALIZATION#<id>#SALE#<saleId>``.

    "Complete immutable inputs" (§5.16) is a refusal, not a comment: every line must
    carry its stable id, product, name snapshot, price snapshot, quantities, and
    subtotal; the sale must carry its buyer fields (null included), one payment
    snapshot, its revision, and an ACTIVE status; and the line subtotals must add to
    the stored total, because a snapshot whose parts do not sum to its whole is a
    second, disagreeing answer about the pool. The copy is deep, so a later catalog
    rename or sale correction rewrites nothing that this version used (PAY-06's rule
    one level up).
    """
    fid = normalize_finalization_id(finalization_id)
    missing = [
        name
        for name in (
            SALE_ID_ATTRIBUTE,
            SALE_AT_ATTRIBUTE,
            LINE_ITEMS_ATTRIBUTE,
            TOTAL_CENTS_ATTRIBUTE,
            PAYMENT_SNAPSHOT_ATTRIBUTE,
            REVISION_ATTRIBUTE,
            STATUS_ATTRIBUTE,
        )
        if name not in sale
    ]
    if missing:
        _refuse(
            SNAPSHOT_INPUT_INCOMPLETE,
            "a sale snapshot requires the complete stored sale, not a projection of it",
            missing=missing,
        )
    if sale[STATUS_ATTRIBUTE] != SALE_STATUS_ACTIVE:
        _refuse(
            SNAPSHOT_INPUT_INCOMPLETE,
            "only an ACTIVE sale enters a finalization's inputs; a voided sale is not part of the pool",
            saleId=sale[SALE_ID_ATTRIBUTE],
            status=sale[STATUS_ATTRIBUTE],
        )
    line_items = sale[LINE_ITEMS_ATTRIBUTE]
    if not isinstance(line_items, list):
        _refuse(
            SNAPSHOT_INPUT_INCOMPLETE,
            "a sale snapshot's line items must be the stored list",
            saleId=sale[SALE_ID_ATTRIBUTE],
        )
    for index, line in enumerate(line_items):
        line_missing = [
            name
            for name in (
                "lineItemId",
                "productId",
                "productNameSnapshot",
                "unitPriceCentsSnapshot",
                "immediateQty",
                "weOweQty",
                "subtotalCents",
            )
            if name not in line
        ]
        if line_missing:
            _refuse(
                SNAPSHOT_INPUT_INCOMPLETE,
                "every snapshot line must carry its complete stored line",
                saleId=sale[SALE_ID_ATTRIBUTE],
                lineIndex=index,
                missing=line_missing,
            )
    subtotal_sum = sum(int(line["subtotalCents"]) for line in line_items)
    if subtotal_sum != int(sale[TOTAL_CENTS_ATTRIBUTE]):
        _refuse(
            SNAPSHOT_INPUT_INCOMPLETE,
            "the snapshot's line subtotals do not sum to its sale total",
            saleId=sale[SALE_ID_ATTRIBUTE],
            subtotalSum=subtotal_sum,
            totalCents=sale["totalCents"],
        )
    row: Dict[str, Any] = {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": sale_snapshot_sk(fid, str(sale[SALE_ID_ATTRIBUTE])),
        "entityType": SALE_SNAPSHOT_ENTITY_TYPE,
        FINALIZATION_ID_ATTRIBUTE: fid,
        SALE_ID_ATTRIBUTE: sale[SALE_ID_ATTRIBUTE],
        SALE_AT_ATTRIBUTE: sale[SALE_AT_ATTRIBUTE],
        BUYER_NAME_ATTRIBUTE: sale.get(BUYER_NAME_ATTRIBUTE),
        BUYER_PHONE_ATTRIBUTE: sale.get(BUYER_PHONE_ATTRIBUTE),
        BUYER_EMAIL_ATTRIBUTE: sale.get(BUYER_EMAIL_ATTRIBUTE),
        ENTERED_BY_ATTRIBUTE: sale.get(ENTERED_BY_ATTRIBUTE),
        LINE_ITEMS_ATTRIBUTE: copy.deepcopy(line_items),
        TOTAL_CENTS_ATTRIBUTE: sale[TOTAL_CENTS_ATTRIBUTE],
        PAYMENT_SNAPSHOT_ATTRIBUTE: copy.deepcopy(sale[PAYMENT_SNAPSHOT_ATTRIBUTE]),
        REVISION_ATTRIBUTE: sale[REVISION_ATTRIBUTE],
    }
    return row


# --- Immutable work-input snapshot (§5.16, §6.4) -------------------------------------


def build_work_snapshot_row(
    *,
    finalization_id: str,
    show_and_sell_id: str,
    slot_id: Any,
    profile_id: Any,
    campaign_id: Any,
    actual_minutes: Any,
    source_signup_version: Any,
) -> Dict[str, Any]:
    """Copy one confirmed participant/slot as ``FINALIZATION#<id>#WORK#<slot>#<profile>``.

    The exact five fields §5.16 names, plus nothing: a suspended or superseded report
    must reproduce per-slot minutes after later corrections moved the signup rows, so
    the snapshot is the version's answer, frozen. A snapshot exists only for *confirmed*
    work, and confirmation means at least one minute — a zero here would be an
    un-confirmed signup taking a share of the pool.
    """
    fid = normalize_finalization_id(finalization_id)
    minutes = inventory_models.normalize_quantity(actual_minutes, ACTUAL_MINUTES_ATTRIBUTE, minimum=1)
    version = inventory_models.normalize_quantity(source_signup_version, SOURCE_SIGNUP_VERSION_ATTRIBUTE, minimum=1)
    return {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": work_snapshot_sk(fid, str(slot_id), str(profile_id)),
        "entityType": WORK_SNAPSHOT_ENTITY_TYPE,
        FINALIZATION_ID_ATTRIBUTE: fid,
        SLOT_ID_ATTRIBUTE: normalize_sale_key_id(slot_id, SLOT_ID_ATTRIBUTE),
        PROFILE_ID_ATTRIBUTE: normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH),
        CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE),
        ACTUAL_MINUTES_ATTRIBUTE: minutes,
        SOURCE_SIGNUP_VERSION_ATTRIBUTE: version,
    }


# --- The finalization version row (§5.16) -------------------------------------------


def build_finalization_row(
    *,
    show_and_sell_id: str,
    unit_campaign_id: str,
    finalization_id: str,
    version_number: Any,
    whole_pool_cents: Any,
    split_method: str,
    cash: Mapping[str, Any],
    previous_finalization_id: Any = None,
    approved_by_account_id: Any,
    approved_at: Any,
    source_event_version: Any,
) -> Dict[str, Any]:
    """One approved finalization version as a row (§5.16).

    The row is born ``APPROVED`` — there is no ``PENDING`` finalization row, because a
    preview that is not approved is deliberately *not* persisted anywhere (§5.17), and
    a first version has no predecessor while a re-finalization names the one it
    replaces. This only builds the row; committing it alongside credits, snapshots,
    totals, and event pointers is the single §5.2 transaction.
    """
    fid = normalize_finalization_id(finalization_id)
    previous = normalize_optional_text(previous_finalization_id, PREVIOUS_FINALIZATION_ID_ATTRIBUTE, MAX_ID_LENGTH)
    if previous is not None:
        normalize_finalization_id(previous, PREVIOUS_FINALIZATION_ID_ATTRIBUTE)
    row: Dict[str, Any] = {
        "pk": show_and_sell_pk(show_and_sell_id),
        "sk": finalization_sk(fid),
        "entityType": FINALIZATION_ENTITY_TYPE,
        FINALIZATION_ID_ATTRIBUTE: fid,
        SHOW_AND_SELL_ID_ATTRIBUTE: show_and_sell_id,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: unit_campaign_id,
        VERSION_NUMBER_ATTRIBUTE: normalize_version_number(version_number),
        STATUS_ATTRIBUTE: FINALIZATION_STATUS_APPROVED,
        WHOLE_POOL_CENTS_ATTRIBUTE: normalize_money_cents(whole_pool_cents, WHOLE_POOL_CENTS_ATTRIBUTE),
        SPLIT_METHOD_ATTRIBUTE: normalize_split_method(split_method),
        CASH_ATTRIBUTE: validate_cash_reconciliation(cash),
        PREVIOUS_FINALIZATION_ID_ATTRIBUTE: previous,
        APPROVED_BY_ATTRIBUTE: approved_by_account_id,
        APPROVED_AT_ATTRIBUTE: approved_at,
        SUSPENDED_BY_ATTRIBUTE: None,
        SUSPENDED_AT_ATTRIBUTE: None,
        SUSPENSION_REASON_ATTRIBUTE: None,
        SOURCE_EVENT_VERSION_ATTRIBUTE: inventory_models.normalize_quantity(
            source_event_version, SOURCE_EVENT_VERSION_ATTRIBUTE, minimum=1
        ),
    }
    _require_row_shape(row, FINALIZATION_ROW_ATTRIBUTES)
    return row


def mark_finalization_suspended(
    row: Mapping[str, Any],
    *,
    suspended_by_account_id: Any,
    suspended_at: Any,
    suspension_reason: Any,
) -> Dict[str, Any]:
    """The row transform a reopen writes (§5.16, §5.3.1) — not the transaction.

    Only an approved version suspends, and the reopen reason is mandatory and kept on
    the version forever: "reason-history" is the audit that a reopen was never quiet.
    Committing the result — with credits suspended, totals decremented, and the
    approved pointer cleared — is §5.3's write.
    """
    current = normalize_finalization_status(row[STATUS_ATTRIBUTE])
    if current != FINALIZATION_STATUS_APPROVED:
        _refuse(
            FINALIZATION_STATE_INVALID,
            "only an APPROVED finalization can be suspended",
            finalizationId=row[FINALIZATION_ID_ATTRIBUTE],
            status=current,
        )
    reason = normalize_required_text(suspension_reason, SUSPENSION_REASON_ATTRIBUTE, MAX_SALE_REASON_LENGTH)
    updated = dict(row)
    updated[STATUS_ATTRIBUTE] = FINALIZATION_STATUS_SUSPENDED
    updated[SUSPENDED_BY_ATTRIBUTE] = suspended_by_account_id
    updated[SUSPENDED_AT_ATTRIBUTE] = suspended_at
    updated[SUSPENSION_REASON_ATTRIBUTE] = reason
    _require_row_shape(updated, FINALIZATION_ROW_ATTRIBUTES)
    return updated


def mark_finalization_superseded(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The row transform re-finalization retires the prior version with (§5.16).

    No actor or timestamp fields exist for supersession in §5.16: the new version's own
    approval audit says who replaced it and when, so a second copy of that fact on the
    retired row would be a second answer to one question.
    """
    current = normalize_finalization_status(row[STATUS_ATTRIBUTE])
    if current != FINALIZATION_STATUS_APPROVED:
        _refuse(
            FINALIZATION_STATE_INVALID,
            "only an APPROVED finalization is superseded by a new version",
            finalizationId=row[FINALIZATION_ID_ATTRIBUTE],
            status=current,
        )
    updated = dict(row)
    updated[STATUS_ATTRIBUTE] = FINALIZATION_STATUS_SUPERSEDED
    _require_row_shape(updated, FINALIZATION_ROW_ATTRIBUTES)
    return updated


def _require_row_shape(row: Mapping[str, Any], allowed: frozenset[str]) -> None:
    """Refuse a row carrying an attribute the model never declared (§5.10 discipline)."""
    extra = sorted(set(row) - allowed)
    missing = sorted(allowed - set(row))
    if extra or missing:
        _refuse(
            SNAPSHOT_INPUT_INCOMPLETE,
            "the row does not match the shape the data model declares",
            entityType=row.get("entityType"),
            extra=extra,
            missing=missing,
        )


# --- Credit arithmetic (§7, SPLIT-02..SPLIT-10, §5.17) -------------------------------


def whole_pool_cents(active_sales: Sequence[Mapping[str, Any]]) -> int:
    """SPLIT-02: one whole-event pool, not per-slot pools.

    Every ACTIVE sale's total enters, and a We Owe sale's total already contains its
    owed lines — SPLIT-05 counts those sales exactly once, so adding obligations here
    would double the pool.
    """
    return sum(
        int(sale[TOTAL_CENTS_ATTRIBUTE]) for sale in active_sales if sale.get(STATUS_ATTRIBUTE) == SALE_STATUS_ACTIVE
    )


def base_shares(
    *,
    whole_pool_cents: int,
    split_method: str,
    eligible_work: Sequence[Tuple[Any, int]],
) -> Dict[str, int]:
    """Round-down base shares of one pool across eligible confirmed participants.

    ``eligible_work`` is ``(profileId, confirmedMinutes)`` per eligible Scout: EQUAL
    weights every participant once (SPLIT-03 — which slots they worked does not
    matter), TIME_WORKED weights by confirmed minutes and refuses a zero-minute
    participant (§5.17 bars one, and a zero weight would quietly take a share of a
    pool the Scout did not work for). Shares are integer floor division of exact
    integer arithmetic — no repeating decimal is ever stored (SPLIT-10) — and the
    residue is what :func:`unassigned_cents` reports for the Kernel to assign.
    """
    method = normalize_split_method(split_method)
    pool = normalize_money_cents(whole_pool_cents, WHOLE_POOL_CENTS_ATTRIBUTE)
    weights: Dict[str, int] = {}
    for profile_id, minutes in eligible_work:
        profile = normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH)
        if profile in weights:
            _refuse(
                DUPLICATE_ROUNDING_PARTICIPANT, "one participant cannot hold two shares of one pool", profileId=profile
            )
        weight = int(minutes)
        if method == SPLIT_METHOD_TIME_WORKED and weight < 1:
            _refuse(
                TIME_WORKED_MINUTES_REQUIRED,
                "a TIME_WORKED participant must have confirmed minutes above zero",
                profileId=profile,
            )
        weights[profile] = weight
    if not weights:
        return {}
    if method == SPLIT_METHOD_TIME_WORKED:
        total_weight = sum(weights.values())
        return {profile: pool * weight // total_weight for profile, weight in weights.items()}
    # EQUAL: every participant carries weight one, whatever slots they worked (SPLIT-03).
    headcount = len(weights)
    return {profile: pool // headcount for profile in weights}


def unassigned_cents(whole_pool_cents: int, shares: Mapping[str, int]) -> int:
    """The cents the round-down left unassigned — displayed, never auto-winnowed (SPLIT-10)."""
    return int(whole_pool_cents) - sum(int(value) for value in shares.values())


def normalize_rounding_assignments(assignments: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """Validate the shape of the Kernel's rounding assignments (§7.2, §5.1.3).

    Entries are ``{profileId, cents}``; cents are non-negative integers, and a
    participant named twice is refused rather than last-write-wins — the draft is a
    complete answer, and silently resolving a duplicate would guess at a Kernel's
    intent with money on the line.
    """
    result: Dict[str, int] = {}
    for entry in assignments:
        profile = normalize_required_text(entry.get(PROFILE_ID_ATTRIBUTE), PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH)
        cents = normalize_money_cents(entry.get("cents"), "rounding.cents")
        if profile in result:
            _refuse(
                DUPLICATE_ROUNDING_PARTICIPANT,
                "one participant cannot appear twice in one rounding draft",
                profileId=profile,
            )
        result[profile] = cents
    return result


def validate_rounding_draft(
    assignments: Mapping[str, int],
    *,
    eligible_profile_ids: Sequence[str],
    unassigned: int,
) -> None:
    """The draft's two bounds (§5.1.3): eligible unique participants, and sum ≤ unassigned.

    Assigning *all* the leftover cents is what finalization requires (SPLIT-10); the
    draft surface only forbids assigning too many, because a draft is work in progress
    by design. Eligibility is checked against the caller's eligible set — the same
    confirmed participants the base shares were computed from.
    """
    eligible = set(eligible_profile_ids)
    total = 0
    for profile, cents in assignments.items():
        if profile not in eligible:
            _refuse(
                ROUNDING_PARTICIPANT_INELIGIBLE,
                "rounding cents can only be assigned to an eligible confirmed participant",
                profileId=profile,
            )
        total += int(cents)
    if total > unassigned:
        _refuse(
            ROUNDING_OVERSUM,
            "the rounding draft cannot assign more cents than the split left unassigned",
            assignedCents=total,
            unassignedCents=unassigned,
        )


def build_credit_row(
    *,
    finalization: Mapping[str, Any],
    campaign_id: Any,
    profile_id: Any,
    actual_minutes: Any,
    base_amount_cents: Any,
    rounding_credit_cents: Any,
    created_at: Any,
    updated_at: Any,
    status: str = ALLOCATION_STATUS_APPROVED,
) -> Dict[str, Any]:
    """One ``CREDIT#<finalizationId>#<profileId>`` allocation (§5.17).

    ``amountCents`` is derived, never supplied — base plus the Kernel-assigned rounding
    cents — so a caller cannot offer a total that its own parts do not add up to. The
    finalization's scope travels on the row so a later scoped read or total never has
    to join back to the version to know which Unit Campaign owns the credit.
    """
    fid = normalize_finalization_id(finalization[FINALIZATION_ID_ATTRIBUTE])
    profile = normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH)
    base = normalize_money_cents(base_amount_cents, BASE_AMOUNT_CENTS_ATTRIBUTE)
    rounding = normalize_money_cents(rounding_credit_cents, ROUNDING_CREDIT_CENTS_ATTRIBUTE)
    minutes = inventory_models.normalize_quantity(actual_minutes, ACTUAL_MINUTES_ATTRIBUTE)
    row: Dict[str, Any] = {
        "pk": show_and_sell_pk(str(finalization[SHOW_AND_SELL_ID_ATTRIBUTE])),
        "sk": credit_sk(fid, profile),
        "entityType": CREDIT_ENTITY_TYPE,
        ALLOCATION_ID_ATTRIBUTE: new_allocation_id(),
        FINALIZATION_ID_ATTRIBUTE: fid,
        SHOW_AND_SELL_ID_ATTRIBUTE: finalization[SHOW_AND_SELL_ID_ATTRIBUTE],
        UNIT_CAMPAIGN_ID_ATTRIBUTE: finalization[UNIT_CAMPAIGN_ID_ATTRIBUTE],
        CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE),
        PROFILE_ID_ATTRIBUTE: profile,
        ACTUAL_MINUTES_ATTRIBUTE: minutes,
        BASE_AMOUNT_CENTS_ATTRIBUTE: base,
        ROUNDING_CREDIT_CENTS_ATTRIBUTE: rounding,
        AMOUNT_CENTS_ATTRIBUTE: base + rounding,
        STATUS_ATTRIBUTE: normalize_allocation_status(status),
        CREATED_AT_ATTRIBUTE: created_at,
        UPDATED_AT_ATTRIBUTE: updated_at,
    }
    _require_row_shape(row, CREDIT_ROW_ATTRIBUTES)
    return row


def validate_credit_set(finalization: Mapping[str, Any], credit_rows: Sequence[Mapping[str, Any]]) -> None:
    """SPLIT-09, exactly: the approved allocations equal the whole pool once.

    This is what finalization approval asserts before it publishes: the round-down
    residue has been fully assigned (no unassigned cent remains, SPLIT-09) — a short
    sum is just as much a refusal as an over-long one, because the pool would silently
    lose cents that were collected at the table.
    """
    pool = int(finalization[WHOLE_POOL_CENTS_ATTRIBUTE])
    approved = [row for row in credit_rows if row.get(STATUS_ATTRIBUTE) == ALLOCATION_STATUS_APPROVED]
    for row in approved:
        if int(row[AMOUNT_CENTS_ATTRIBUTE]) != int(row[BASE_AMOUNT_CENTS_ATTRIBUTE]) + int(
            row[ROUNDING_CREDIT_CENTS_ATTRIBUTE]
        ):
            _refuse(
                CREDIT_POOL_MISMATCH,
                "an allocation's amount does not equal its base plus rounding cents",
                allocationId=row.get(ALLOCATION_ID_ATTRIBUTE),
            )
    total = sum(int(row[AMOUNT_CENTS_ATTRIBUTE]) for row in approved)
    if total != pool:
        _refuse(
            CREDIT_POOL_MISMATCH,
            "approved allocations must equal the whole-event pool exactly (SPLIT-09)",
            wholePoolCents=pool,
            allocationTotalCents=total,
        )


# --- The Unit-Campaign-scoped total (§5.18, DM-AC-08) --------------------------------


def build_total_row(
    *,
    campaign_id: Any,
    profile_id: Any,
    unit_campaign_id: Any,
    approved_amount_cents: Any,
    version: Any,
    updated_at: Any,
) -> Dict[str, Any]:
    """A ``SHOW_AND_SELL_TOTAL`` projection row for one Scout Campaign in one Unit Campaign."""
    row: Dict[str, Any] = {
        **total_key(str(unit_campaign_id), str(campaign_id)),
        "entityType": TOTAL_ENTITY_TYPE,
        CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE),
        PROFILE_ID_ATTRIBUTE: normalize_required_text(profile_id, PROFILE_ID_ATTRIBUTE, MAX_ID_LENGTH),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_sale_key_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        APPROVED_AMOUNT_CENTS_ATTRIBUTE: normalize_money_cents(approved_amount_cents, APPROVED_AMOUNT_CENTS_ATTRIBUTE),
        VERSION_ATTRIBUTE: inventory_models.normalize_quantity(version, VERSION_ATTRIBUTE, minimum=1),
        UPDATED_AT_ATTRIBUTE: updated_at,
    }
    _require_row_shape(row, TOTAL_ROW_ATTRIBUTES)
    return row


def load_campaign_total(unit_campaign_id: str, campaign_id: str) -> Optional[Dict[str, Any]]:
    """Read the scoped total by its exact key (never an eventually consistent GSI sum)."""
    item = tables.unit_campaigns.get_item(Key=total_key(unit_campaign_id, campaign_id))
    row = item.get("Item")
    return dict(row) if row else None


def apply_approved_credit(
    total: Optional[Mapping[str, Any]],
    *,
    credit: Mapping[str, Any],
    updated_at: Any,
) -> Dict[str, Any]:
    """Move the projection for one approved credit (§5.18).

    The credit row carries its own scope, and a total answering for a *different* Unit
    Campaign is refused outright — "never shared across Unit Campaigns or their
    operation locks" is enforced at the arithmetic, not by convention. A missing total
    is created at exactly the credit's amount and version 1.
    """
    if total is None:
        return build_total_row(
            campaign_id=credit[CAMPAIGN_ID_ATTRIBUTE],
            profile_id=credit[PROFILE_ID_ATTRIBUTE],
            unit_campaign_id=credit[UNIT_CAMPAIGN_ID_ATTRIBUTE],
            approved_amount_cents=credit[AMOUNT_CENTS_ATTRIBUTE],
            version=1,
            updated_at=updated_at,
        )
    _require_total_scope(total, credit)
    row = dict(total)
    row[APPROVED_AMOUNT_CENTS_ATTRIBUTE] = int(total[APPROVED_AMOUNT_CENTS_ATTRIBUTE]) + int(
        credit[AMOUNT_CENTS_ATTRIBUTE]
    )
    row[VERSION_ATTRIBUTE] = int(total[VERSION_ATTRIBUTE]) + 1
    row[UPDATED_AT_ATTRIBUTE] = updated_at
    return row


def reverse_approved_credit(total: Mapping[str, Any], *, amount_cents: Any, updated_at: Any) -> Dict[str, Any]:
    """Subtract a suspended version's exact approved amounts (§5.3.1's projection half).

    The result cannot go below zero: a total underflowing means the amounts reversed
    were never in this scope, which is exactly the torn-projection DM-AC-08 exists to
    catch before it becomes a report.
    """
    amount = normalize_money_cents(amount_cents, APPROVED_AMOUNT_CENTS_ATTRIBUTE)
    remaining = int(total[APPROVED_AMOUNT_CENTS_ATTRIBUTE]) - amount
    if remaining < 0:
        _refuse(
            TOTAL_CREDIT_UNDERFLOW,
            "the scoped total cannot give back more credit than it holds",
            approvedAmountCents=int(total[APPROVED_AMOUNT_CENTS_ATTRIBUTE]),
            reversingCents=amount,
        )
    row = dict(total)
    row[APPROVED_AMOUNT_CENTS_ATTRIBUTE] = remaining
    row[VERSION_ATTRIBUTE] = int(total[VERSION_ATTRIBUTE]) + 1
    row[UPDATED_AT_ATTRIBUTE] = updated_at
    return row


def _require_total_scope(total: Mapping[str, Any], credit: Mapping[str, Any]) -> None:
    for name in (CAMPAIGN_ID_ATTRIBUTE, UNIT_CAMPAIGN_ID_ATTRIBUTE):
        if str(total.get(name)) != str(credit.get(name)):
            _refuse(
                TOTAL_SCOPE_MISMATCH,
                "a credit may only move the total of its own Scout Campaign in its own Unit Campaign",
                attribute=name,
                totalScope=total.get(name),
                creditScope=credit.get(name),
            )


def reconcile_total_with_credits(total: Mapping[str, Any], credit_rows: Sequence[Mapping[str, Any]]) -> None:
    """DM-AC-08: the projection equals its currently approved detail, or the pair is broken.

    Every credit that claims this scope is summed at APPROVED status only — a
    suspended or superseded allocation belongs to credit the projection no longer
    carries — and a row from a different scope is refused rather than silently
    excluded, because a reconciliation that quietly ignores rows proves nothing.
    """
    total_cents = 0
    for row in credit_rows:
        if str(row.get(CAMPAIGN_ID_ATTRIBUTE)) != str(total[CAMPAIGN_ID_ATTRIBUTE]) or str(
            row.get(UNIT_CAMPAIGN_ID_ATTRIBUTE)
        ) != str(total[UNIT_CAMPAIGN_ID_ATTRIBUTE]):
            if row.get(STATUS_ATTRIBUTE) == ALLOCATION_STATUS_APPROVED:
                _refuse(
                    TOTAL_SCOPE_MISMATCH,
                    "a credit in another scope was offered to this total's reconciliation",
                    allocationId=row.get(ALLOCATION_ID_ATTRIBUTE),
                )
            continue
        if row.get(STATUS_ATTRIBUTE) == ALLOCATION_STATUS_APPROVED:
            total_cents += int(row[AMOUNT_CENTS_ATTRIBUTE])
    if total_cents != int(total[APPROVED_AMOUNT_CENTS_ATTRIBUTE]):
        _refuse(
            DETAIL_TOTAL_MISMATCH,
            "the scoped total disagrees with its currently approved allocation detail",
            approvedAmountCents=int(total[APPROVED_AMOUNT_CENTS_ATTRIBUTE]),
            detailTotalCents=total_cents,
        )


# --- Reads (§6.4 partition scoping) --------------------------------------------------


def _partition_rows(show_and_sell_id: str, sk_prefix: str) -> List[Dict[str, Any]]:
    return list(
        query_all_items(
            tables.show_and_sells,
            {
                "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
                "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": f"{sk_prefix}#"},
                "ConsistentRead": True,
            },
        )
    )


def finalization_rows(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """This event's finalization versions, child rows excluded.

    The ``FINALIZATION#`` prefix names the versions and their three kinds of child
    alike; the entity-type filter is what answers "the versions" rather than "every
    row finalization ever wrote".
    """
    return [
        dict(row)
        for row in _partition_rows(show_and_sell_id, FINALIZATION_SK_PREFIX)
        if row.get("entityType") == FINALIZATION_ENTITY_TYPE
    ]


def read_finalization(show_and_sell_id: str, finalization_id: str) -> Optional[Dict[str, Any]]:
    """One version by its exact key, consistently."""
    item = tables.show_and_sells.get_item(Key=finalization_key(show_and_sell_id, finalization_id))
    row = item.get("Item")
    return dict(row) if row else None


def finalization_return_line_rows(show_and_sell_id: str, finalization_id: str) -> List[Dict[str, Any]]:
    """One version's immutable return lines (§6.4)."""
    prefix = f"{finalization_sk(finalization_id)}{RETURN_SK_MARKER}"
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": prefix},
            "ConsistentRead": True,
        },
    )
    return [dict(row) for row in rows if row.get("entityType") == RETURN_LINE_ENTITY_TYPE]


def finalization_sale_snapshot_rows(show_and_sell_id: str, finalization_id: str) -> List[Dict[str, Any]]:
    """One version's immutable sale inputs (§6.4)."""
    prefix = f"{finalization_sk(finalization_id)}{SALE_SNAPSHOT_SK_MARKER}"
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": prefix},
            "ConsistentRead": True,
        },
    )
    return [dict(row) for row in rows if row.get("entityType") == SALE_SNAPSHOT_ENTITY_TYPE]


def finalization_work_snapshot_rows(show_and_sell_id: str, finalization_id: str) -> List[Dict[str, Any]]:
    """One version's immutable per-slot work (§6.4)."""
    prefix = f"{finalization_sk(finalization_id)}{WORK_SNAPSHOT_SK_MARKER}"
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": prefix},
            "ConsistentRead": True,
        },
    )
    return [dict(row) for row in rows if row.get("entityType") == WORK_SNAPSHOT_ENTITY_TYPE]


def finalization_credit_rows(show_and_sell_id: str, finalization_id: str) -> List[Dict[str, Any]]:
    """One version's credit rows (§6.4), in sort order by profile."""
    prefix = f"{CREDIT_SK_PREFIX}#{normalize_finalization_id(finalization_id)}#"
    rows = query_all_items(
        tables.show_and_sells,
        {
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": prefix},
            "ConsistentRead": True,
        },
    )
    return [dict(row) for row in rows if row.get("entityType") == CREDIT_ENTITY_TYPE]
