"""Shared sale-payment validation for Show & Sell pooled sales.

Delivery checklist §4.1.3; data model §5.14; API contract `createShowAndSellSale`.

A sale names its payment method by ``methodCode``, never by whatever label the
browser happened to show:

    CASH | CHECK | OTHER | CUSTOM:<paymentMethodId>

and it carries exactly one immutable snapshot, ``paymentMethodSnapshot`` of
``{methodCode, displayName, otherDetails}``, whose display name is read from the
server's own row. That is what keeps a later rename or deletion off a historical
sale (`PAY-06`), and what keeps a custom method somebody named ``Cash`` out of the
cash column: money is classified by the code and never by the display text
(`PAY-06`, AC-31).

The pooled-sale write paths (checklist §4.2, §4.3) are this module's callers, and
they land in the next wave, so the payment half of their contract lives here in
one place rather than being restated by each of them:

- :func:`normalize_method_code` decides what a sale may name at all;
- :func:`resolve_sale_payment` resolves a ``CUSTOM:`` code inside the event's own
  Unit, so another Unit's method is simply not there (AUTH-U-05);
- :func:`normalize_other_details` requires the Other explanation — required for
  Other, including a split-payment explanation (AC-20), and never parsed (§5.14);
- :func:`sale_payment_decision` combines the three and refuses a method retired
  between the read that filled the picker and the write that records the sale;
- :func:`payment_method_condition_action` is the ``ConditionCheck`` the sale's
  transaction carries, so that race is settled by the write rather than by the
  read before it;
- :func:`expected_cash_cents` is the one classifier of expected cash, kept beside
  the snapshot rule it follows from so the two cannot drift (§4.3.3 is its caller).

A built-in has no stored row, so it has no version, no active flag, and nothing
to condition: its version is 0 and it can never be deactivated, which is why
:func:`payment_method_condition_action` answers ``None`` for one.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .mutations import wire_key
from .unit_models import normalize_required_text
from .unit_payment_models import BUILTIN_PAYMENT_METHOD_IDS, BUILTIN_PAYMENT_METHODS, find_payment_by_id

CUSTOM_METHOD_CODE_PREFIX = "CUSTOM:"

# The Other explanation is free text a Unit Admin types at the table — how a split
# was taken, which check number arrived, that the unit was reimbursed later. It is
# required (AC-19) and never parsed (§5.14), so nothing downstream depends on its
# shape. 250 characters is generous for one line of explanation at the table while
# keeping a sale's snapshot small beside the line items it shares an item with.
OTHER_DETAILS_MAX_CHARS = 250

# The display name a built-in reports, read from the same table the method list
# renders, so the picker and the sale snapshot can never disagree.
BUILTIN_DISPLAY_NAMES: Mapping[str, str] = {
    str(method["paymentMethodId"]): str(method["displayName"]) for method in BUILTIN_PAYMENT_METHODS
}


def _refuse_unknown_method(text: str) -> str:
    """A code that names neither a built-in nor a ``CUSTOM:`` method is a caller bug."""
    raise AppError(
        ErrorCode.INVALID_INPUT,
        "paymentMethod.methodCode must be CASH, CHECK, OTHER, or CUSTOM:<paymentMethodId>.",
        details={"subcode": "UNKNOWN_PAYMENT_METHOD_CODE", "methodCode": text},
    )


def normalize_method_code(value: Any) -> str:
    """Validate the ``methodCode`` a sale names and return it in canonical form.

    Built-in codes are case-insensitive on the way in, so a picker that sends
    ``cash`` and a caller that sends ``CASH`` mean the same sale. The id after
    ``CUSTOM:`` is NOT re-cased: it is the stored ``paymentMethodId`` and has to
    resolve to the row it came from.
    """
    if not isinstance(value, str) or not value.strip():
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "paymentMethod.methodCode is required; every sale records exactly one payment method.",
            details={"subcode": "PAYMENT_METHOD_REQUIRED"},
        )
    text = value.strip()
    if text.upper() in BUILTIN_PAYMENT_METHOD_IDS:
        return text.upper()
    if text.upper().startswith(CUSTOM_METHOD_CODE_PREFIX):
        payment_method_id = normalize_required_text(text[len(CUSTOM_METHOD_CODE_PREFIX) :], "paymentMethod.methodCode")
        return f"{CUSTOM_METHOD_CODE_PREFIX}{payment_method_id}"
    return _refuse_unknown_method(text)


def custom_method_id(method_code: str) -> Optional[str]:
    """The ``paymentMethodId`` a ``CUSTOM:`` code addresses, or None for a built-in."""
    if method_code.startswith(CUSTOM_METHOD_CODE_PREFIX):
        return method_code[len(CUSTOM_METHOD_CODE_PREFIX) :]
    return None


def resolve_sale_payment(unit_id: str, method_code: str) -> Optional[Dict[str, Any]]:
    """The stored custom method a sale selects, resolved inside this Unit.

    ``None`` answers both for a built-in (no row exists) and for a method that is
    not this Unit's — another Unit's ``paymentMethodId`` included, which must not
    be distinguishable (AUTH-U-05). A caller that needs to tell those apart asks
    :func:`custom_method_id` first.
    """
    payment_method_id = custom_method_id(method_code)
    if payment_method_id is None:
        return None
    row = find_payment_by_id(unit_id, payment_method_id)
    return None if row is None else dict(row)


def _carries_details(value: Any) -> bool:
    """Any non-blank value counts as an Other explanation; blank text is the same as none."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def normalize_other_details(method_code: str, value: Any) -> Optional[str]:
    """Require the Other explanation, and refuse one attached to any other method.

    Other is how a sale records anything the method list cannot name, a split
    payment above all (AC-20), so the explanation is what makes the record
    readable in a report later (AC-19). Every other method already says what it
    is, so details on one are a caller mistake rather than data.
    """
    if method_code != "OTHER":
        if _carries_details(value):
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "paymentMethod.otherDetails is recorded only for the Other method.",
                details={"subcode": "OTHER_DETAILS_NOT_ALLOWED", "methodCode": method_code},
            )
        return None
    return normalize_required_text(value, "paymentMethod.otherDetails", OTHER_DETAILS_MAX_CHARS)


def _refuse_inactive_method(row: Mapping[str, Any]) -> None:
    """A method retired since the picker was filled is a reload, not a bad sale."""
    raise AppError(
        ErrorCode.CONFLICT,
        "This payment method is no longer available for new sales. Reload and choose another.",
        details={
            "subcode": "PAYMENT_METHOD_NOT_ACTIVE",
            "paymentMethodId": str(row.get("paymentMethodId", "")),
            "displayName": str(row.get("displayName", "")),
        },
    )


def payment_method_condition_action(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``ConditionCheck`` that pins the method this snapshot read.

    The version AND the active flag the read saw are both in the condition, so the
    sale's transaction fails whole if either moved between the read and the commit
    — the same optimistic-lock rule the rename and QR paths use, reached across a
    key this write does not otherwise touch. The row's own key pair is used rather
    than a rebuilt one: the sort key is the normalized name as stored, and
    re-deriving it could address a different row than the one read.
    """
    return {
        "TableName": tables.units.table_name,
        "Key": wire_key({"pk": str(row["pk"]), "sk": str(row["sk"])}),
        "ConditionExpression": "#version = :version AND #isActive = :isActive",
        "ExpressionAttributeNames": {"#version": "version", "#isActive": "isActive"},
        "ExpressionAttributeValues": {
            ":version": {"N": str(int(row["version"]))},
            ":isActive": {"BOOL": bool(row.get("isActive", True))},
        },
    }


def build_payment_method_snapshot(row: Mapping[str, Any], other_details: Optional[str]) -> Dict[str, Any]:
    """One sale's payment snapshot for a stored custom method.

    The name is the row's, never the caller's: a method renamed the day after a
    sale leaves that sale's original display alone, and a sale can never be
    recorded under a name it did not pay by (§5.14, PAY-06).
    """
    return {
        "methodCode": f"{CUSTOM_METHOD_CODE_PREFIX}{row['paymentMethodId']}",
        "displayName": str(row["displayName"]),
        "otherDetails": other_details,
    }


def builtin_payment_method_snapshot(method_code: str, other_details: Optional[str]) -> Dict[str, Any]:
    """One sale's payment snapshot for a computed built-in."""
    return {"methodCode": method_code, "displayName": BUILTIN_DISPLAY_NAMES[method_code], "otherDetails": other_details}


def sale_payment_decision(
    *, unit_id: str, method_code: Any, other_details: Any = None, require_active: bool = True
) -> Dict[str, Any]:
    """Decide one sale's payment: the snapshot to write, and the condition to carry.

    ``require_active`` is false only for the correction path's unchanged method —
    the API contract lets a historical correction keep naming a method the Unit has
    since retired. Every other call, a new sale above all, refuses a retired method
    with ``CONFLICT`` and writes nothing, and the returned condition is what turns
    the window between that read and the commit into a failed transaction rather
    than a sale against a method the Unit removed.
    """
    code = normalize_method_code(method_code)
    details = normalize_other_details(code, other_details)
    if custom_method_id(code) is None:
        return {"snapshot": builtin_payment_method_snapshot(code, details), "condition": None}

    row = resolve_sale_payment(unit_id, code)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "Unit payment method not found")
    if require_active and not bool(row.get("isActive", True)):
        _refuse_inactive_method(row)
    return {"snapshot": build_payment_method_snapshot(row, details), "condition": payment_method_condition_action(row)}


def expected_cash_cents(payment_method_snapshot: Mapping[str, Any], total_cents: Any) -> int:
    """Expected cash, decided by the method code alone (§5.14, AC-31).

    A custom method named ``Cash`` or ``Extra cash`` must not show up in the cash
    drawer, and an Other note describing a split must not either, so neither the
    display name nor ``otherDetails`` is consulted here. §4.3.3 is the caller; this
    rule lives beside the snapshot rule it follows from, so the two cannot drift.
    """
    cents = int(total_cents)
    if payment_method_snapshot.get("methodCode") != "CASH":
        return 0
    return cents
