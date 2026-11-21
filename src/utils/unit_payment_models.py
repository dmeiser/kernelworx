"""UnitPaymentMethod persistence (delivery checklist §4.1.1, data model §5.4/§6.1).

Custom methods live on the Unit's own partition at

    UNIT#<unitId> / PAYMENT#<normalizedName>    the custom method  (§5.4)

so the per-Unit uniqueness the contract demands is the item key itself: a second
method with the same normalized name addresses the same row, and the create's
conditional Put (``attribute_not_exists``) is what refuses the race rather than
the read that preceded it. The built-in Cash, Check, and Other are COMPUTED on
every read and are never stored (data model §5.4): nothing can rename,
deactivate, or masquerade as a built-in, because a built-in has no row at all.
Their reserved normalized names are refused by every create/rename.

Invariants enforced here:

- ``normalizedName`` is the case-folded ``displayName`` and is unique per Unit
  (§5.4). ``paymentMethodId`` is generated identity and STABLE across renames:
  a rename writes the new key with the same id and deletes the old one, so
  historical ``ShowAndSellSale.paymentMethodSnapshot`` values and any later
  ``paymentMethodId`` reference keep resolving (§5.4, PAY-06).
- ``version`` is the optimistic-concurrency token for renames and QR mutations;
  it starts at 1 and every stored mutation increments it. Built-ins report
  version 0 — they have no stored row to version, and 0 is the one number no
  custom method can have, so a caller can never stale-check a built-in.
- At most ``MAX_ACTIVE_PAYMENT_METHODS`` ACTIVE custom methods per Unit
  (API contract §3.4); inactive rows stay for history and still occupy their
  normalized-name key.
- A deactivated method reads back with every other field intact
  (PAY-M-03-01): deactivation flips ``isActive`` and the audit fields and
  nothing else.

Authorization is not this module's job: :mod:`src.utils.unit_auth` decides who
may reach these rows, exactly as it does for the Unit and grant rows sharing the
partition.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .pagination import query_all_items
from .unit_models import normalize_required_text, unit_pk

# --- Key layout (data model §6.1) ------------------------------------------------

PAYMENT_SK_PREFIX = "PAYMENT"

# API contract §3.4: maximum 50 active custom methods per Unit.
MAX_ACTIVE_PAYMENT_METHODS = 50

# The stored audit/optimistic fields every custom method carries.
_PAYMENT_ID_MAX_CHARS = 100

# --- Built-in methods (§5.4, PAY-02) ---------------------------------------------

# Computed on every read, in display order. The ids are the exact methodCodes a
# later sale snapshot uses to classify expected cash (CASH-01: expected Cash
# comes ONLY from methodCode = CASH), and they can never collide with a custom
# paymentMethodId because custom ids are generated UUIDs.
BUILTIN_PAYMENT_METHODS: tuple[Dict[str, str], ...] = (
    {"paymentMethodId": "CASH", "displayName": "Cash"},
    {"paymentMethodId": "CHECK", "displayName": "Check"},
    {"paymentMethodId": "OTHER", "displayName": "Other"},
)

BUILTIN_PAYMENT_METHOD_IDS: frozenset[str] = frozenset(method["paymentMethodId"] for method in BUILTIN_PAYMENT_METHODS)

# The normalized names the contract reserves case-insensitively (§5.4): a custom
# method can never masquerade as a built-in.
RESERVED_NORMALIZED_NAMES: frozenset[str] = frozenset(normalized for normalized in ("cash", "check", "other"))


# --- Key builders ----------------------------------------------------------------


def payment_sk(normalized_name: str) -> str:
    """Sort key of one custom method, addressed by its normalized name.

    The normalized name IS the key segment, so per-Unit uniqueness is a key
    property and the create's conditional Put is the race guard.
    """
    return f"{PAYMENT_SK_PREFIX}#{normalized_name}"


def payment_key(unit_id: str, normalized_name: str) -> Dict[str, str]:
    """The custom-method item's key pair."""
    return {"pk": unit_pk(unit_id), "sk": payment_sk(normalized_name)}


# --- Normalization and validation ------------------------------------------------


def normalize_payment_display_name(value: Any) -> str:
    """Trim a required display name to 1-100 characters (API contract §3.4)."""
    return normalize_required_text(value, "displayName")


def normalize_payment_name(display_name: str) -> str:
    """The case-folded uniqueness key of a display name (§5.4).

    Case-folding, not lower-casing, is what "normalized" means here: it folds
    the aggressive case pairs (``ß`` → ``ss``) as well, so two spellings that
    any reader would call the same name cannot hold two rows.
    """
    return display_name.casefold()


def is_reserved_payment_name(normalized_name: str) -> bool:
    """True when a normalized name would collide with a built-in method."""
    return normalized_name in RESERVED_NORMALIZED_NAMES


def new_payment_method_id() -> str:
    """A stable custom-method identity, generated before any write.

    A rename carries this id onto the new key, so it — not the normalized-name
    key — is what stays stable across the method's whole history.
    """
    return str(uuid.uuid4())


# --- Item builder ----------------------------------------------------------------


def build_payment_item(
    *,
    payment_method_id: Any,
    unit_id: Any,
    display_name: Any,
    created_by_account_id: Any,
    now_iso: str,
    created_at: Optional[str] = None,
    is_active: bool = True,
    qr_code_s3_key: Optional[str] = None,
    version: int = 1,
) -> Dict[str, Any]:
    """Render a custom-method item at ``UNIT#<unitId> / PAYMENT#<normalizedName>``.

    ``created_at`` lets a rename carry the original creation audit onto the new
    key; every other write stamps ``now_iso`` as its creation too. The QR key is
    stored only when one is attached: an absent attribute and a null read
    identically, and §4.1.2 is the only writer of a non-null value.
    """
    identity = normalize_required_text(payment_method_id, "paymentMethodId", _PAYMENT_ID_MAX_CHARS)
    unit_identity = normalize_required_text(unit_id, "unitId")
    display = normalize_payment_display_name(display_name)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "version must be at least 1")
    item: Dict[str, Any] = {
        "pk": unit_pk(unit_identity),
        "sk": payment_sk(normalize_payment_name(display)),
        "paymentMethodId": identity,
        "unitId": unit_identity,
        "displayName": display,
        "normalizedName": normalize_payment_name(display),
        "isActive": bool(is_active),
        "createdAt": created_at if created_at is not None else now_iso,
        "updatedAt": now_iso,
        "createdByAccountId": normalize_required_text(
            created_by_account_id, "createdByAccountId", _PAYMENT_ID_MAX_CHARS
        ),
        "updatedByAccountId": normalize_required_text(
            created_by_account_id, "updatedByAccountId", _PAYMENT_ID_MAX_CHARS
        ),
        "version": version,
    }
    if qr_code_s3_key is not None:
        item["qrCodeS3Key"] = qr_code_s3_key
    return item


# --- Reads -----------------------------------------------------------------------


def list_payment_rows(unit_id: str) -> List[Dict[str, Any]]:
    """Every stored custom-method row on the Unit, active or not, consistently.

    Strongly consistent: ``createUnitPaymentMethod`` counts the active rows
    against the 50-cap and a rename reads the collection to resolve
    ``paymentMethodId`` and check the name collision — an eventually consistent
    read would let a fresh 50th method hide and admit a 51st.
    """
    items = query_all_items(
        tables.units,
        {
            "KeyConditionExpression": Key("pk").eq(unit_pk(unit_id)) & Key("sk").begins_with(PAYMENT_SK_PREFIX),
            "ConsistentRead": True,
        },
    )
    return [item for item in items if isinstance(item, dict)]


def find_payment_by_id(unit_id: str, payment_method_id: str) -> Optional[Dict[str, Any]]:
    """Resolve a custom-method row by its stable id.

    The collection query is the only lookup path: a ``paymentMethodId`` is not a
    key segment, and API contract §4.3 makes the Unit's payment collection the
    one consistent way to resolve it (PAY-M-02-02). Inactive rows resolve too —
    history still names them — and the built-in ids never resolve to a row here,
    which is what makes the built-ins impossible to mutate.
    """
    for row in list_payment_rows(unit_id):
        if str(row.get("paymentMethodId", "")) == payment_method_id:
            return row
    return None


# --- Projections -----------------------------------------------------------------


def payment_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project a stored custom-method item onto the ``UnitPaymentMethod`` type.

    ``pk``/``sk`` are storage detail and never leave the handler; the
    normalized name is deliberately not projected — it is a uniqueness key, and
    users see ``displayName`` (the snapshot contract snapshots that name, not
    the key).
    """
    qr_key = row.get("qrCodeS3Key")
    return {
        "paymentMethodId": str(row["paymentMethodId"]),
        "unitId": str(row["unitId"]),
        "displayName": str(row["displayName"]),
        "isActive": bool(row.get("isActive", True)),
        "qrCodeS3Key": str(qr_key) if isinstance(qr_key, str) and qr_key else None,
        "createdAt": row.get("createdAt"),
        "updatedAt": row.get("updatedAt"),
        "createdByAccountId": row.get("createdByAccountId"),
        "updatedByAccountId": row.get("updatedByAccountId"),
        "version": int(row["version"]),
    }


def builtin_payment_payloads(unit_id: str) -> List[Dict[str, Any]]:
    """The computed built-in Cash/Check/Other for one Unit (§5.4, PAY-02).

    Always active, never mutable, never carrying a QR: a built-in's version is 0
    because there is no row under it to version, and 0 is outside the stored
    version range (which starts at 1), so no ``expectedVersion`` can ever stale-
    check a built-in by accident.
    """
    return [
        {
            "paymentMethodId": method["paymentMethodId"],
            "unitId": unit_id,
            "displayName": method["displayName"],
            "isActive": True,
            "qrCodeS3Key": None,
            "createdAt": None,
            "updatedAt": None,
            "createdByAccountId": None,
            "updatedByAccountId": None,
            "version": 0,
        }
        for method in BUILTIN_PAYMENT_METHODS
    ]
