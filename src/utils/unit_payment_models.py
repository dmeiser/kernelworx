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

import re
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from boto3.dynamodb.conditions import Key

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .pagination import query_all_items
from .unit_models import normalize_required_text, unit_pk

# --- Key layout (data model §6.1) ------------------------------------------------

PAYMENT_SK_PREFIX = "PAYMENT#"

# The Unit QR prefix (§4.3 of SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md):
#
#     payment-qr-codes/units/<unitId>/<paymentMethodId>/<sha256>-<uuid>.<ext>
#
# A separate root from the legacy account scheme (``payment-qr-codes/<accountId>/``)
# is what lets the execution role hold one scoped grant, and carrying the
# paymentMethodId in the key is what makes a foreign key detectable: an
# ``s3Key`` a caller supplies on confirm has to sit under the prefix of the very
# method it names, or it belongs to somebody else.
#
# The object name is the pair that makes the attachment immutable. The digest is
# the SHA-256 of the bytes the browser says it is uploading, so the stored key
# commits to specific bytes; the uuid makes the name unique to ONE upload
# request, so the pre-signed POST this API hands out never names a key another
# request already committed. Confirmation then hashes what is actually in the
# bucket and refuses unless it matches the digest in the key: the row can only
# ever reference an object whose bytes are the bytes its own name declares, and
# a later POST cannot quietly swap them under a committed key.
UNIT_QR_ROOT = "payment-qr-codes/units"

# A stored object name: the digest the mint declared, the uuid that makes this
# upload's name unique, and the extension both were minted for. Nothing else is
# ever accepted back on confirm or delete.
_QR_DIGEST_HEX = re.compile(r"[0-9a-f]{64}")
_QR_OBJECT_NAME = re.compile(r"[0-9a-f]{64}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z]{3,4}")

# The two key segments a Unit QR sits under. Unit ids and paymentMethodIds are
# generated identifiers, so the character set here is a guard against a caller
# smuggling a path segment (``..``, ``/``) into a prefix match.
_QR_KEY_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


# API contract §3.4: maximum 50 active custom methods per Unit.
MAX_ACTIVE_PAYMENT_METHODS = 50

# The ceiling guard (§4.1.1): a sort key the ``PAYMENT#`` collection query can
# never return, holding the count of ACTIVE custom methods. A create counts rows
# first only to produce a readable refusal; the ceiling itself is the counter's
# transaction condition, because a count read before a transaction settles
# nothing — two differently named creates can both read 49 and both commit. The
# counter is the authority, and only create and deactivate move it.
PAYMENT_CAPACITY_SK = "PAYMENT-CAPACITY"

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
    property and the create's conditional Put is the race guard. The prefix is the
    full ``PAYMENT#`` rather than a bare ``PAYMENT`` because the Unit's payment
    collection query runs ``begins_with`` on it, and the ceiling counter shares
    this partition under a ``PAYMENT-``-shaped key a looser prefix would swallow.
    """
    return f"{PAYMENT_SK_PREFIX}{normalized_name}"


def normalized_name_from_sk(sort_key: str) -> str:
    """The normalized name a payment sort key carries.

    Read off the stored key, never re-derived from caller input: a rename and a
    deactivation both have to address the row that exists, and the name the caller
    typed is not evidence of what the key says.
    """
    return sort_key[len(PAYMENT_SK_PREFIX) :]


def payment_key(unit_id: str, normalized_name: str) -> Dict[str, str]:
    """The custom-method item's key pair."""
    return {"pk": unit_pk(unit_id), "sk": payment_sk(normalized_name)}


def payment_capacity_key(unit_id: str) -> Dict[str, str]:
    """The ceiling counter's key pair — same partition, unreachable by the query."""
    return {"pk": unit_pk(unit_id), "sk": PAYMENT_CAPACITY_SK}


def read_payment_active_count(unit_id: str) -> Optional[int]:
    """The stored ceiling counter, or None when this Unit has never had one.

    Read only by the create and deactivate paths, which are the only writers. A
    missing counter is not a zero: the caller seeds it from the row count it just
    read, which is what keeps a hand-seeded collection under the ceiling instead
    of handing it 50 free slots.
    """
    response = tables.units.get_item(Key=payment_capacity_key(unit_id), ConsistentRead=True)
    item = response.get("Item")
    if not isinstance(item, dict):
        return None
    count = item.get("activeCount")
    return int(count) if isinstance(count, (int, Decimal)) else None


# --- QR object keys (§4.1.2) -----------------------------------------------------


def normalize_qr_digest(value: Any) -> str:
    """The 64-hex-digit SHA-256 an upload declares, lower-cased.

    The browser hashes the file it is about to POST, so the object name this
    handler mints is a claim about bytes the server has not seen yet — which is
    exactly what confirmation then checks. Anything that is not 64 hex digits is
    a caller who cannot name the bytes they are uploading.
    """
    if not isinstance(value, str):
        raise AppError(ErrorCode.INVALID_INPUT, "sha256 must be a hex digest")
    digest = value.strip().lower()
    if not _QR_DIGEST_HEX.fullmatch(digest):
        raise AppError(ErrorCode.INVALID_INPUT, "sha256 must be 64 hexadecimal digits")
    return digest


def unit_qr_key_digest(s3_key: str, unit_id: str, payment_method_id: str) -> str:
    """The digest a Unit QR object name declares — empty unless the key is this method's.

    One gate answers both questions a confirm or download asks of an object name:
    does it belong to this method at all, and does it name the bytes it claims. A
    key under another Unit, another method, or the legacy account scheme returns
    the empty string, which no stored object's digest can match, so a caller
    cannot sidestep either half by supplying a name.
    """
    if not unit_qr_key_is_mine(s3_key, unit_id, payment_method_id):
        return ""
    declared, _, _ = s3_key.rsplit("/", 1)[-1].partition("-")
    return declared


def unit_qr_prefix(unit_id: str, payment_method_id: str) -> str:
    """The only S3 prefix one Unit payment method may ever hold objects under.

    Both segments are checked against :data:`_QR_KEY_SEGMENT` here rather than at
    the call sites, because this is the string a foreign-key refusal is decided
    by: an unchecked segment would let ``a/..``-shaped input match another
    method's prefix.
    """
    for name, segment in (("unitId", unit_id), ("paymentMethodId", payment_method_id)):
        if not _QR_KEY_SEGMENT.fullmatch(segment):
            raise AppError(ErrorCode.INVALID_INPUT, f"{name} cannot address a QR object")
    return f"{UNIT_QR_ROOT}/{unit_id}/{payment_method_id}"


def new_unit_qr_object_key(unit_id: str, payment_method_id: str, digest_hex: str, extension: str) -> str:
    """Mint one upload target: a fresh, digest-named object under this method's prefix.

    Two properties do the work. The name is unique to THIS upload request, so the
    pre-signed POST this API issues never names an object another request already
    committed — a replacement displaces a different key than the one it writes,
    and deleting the displaced one can never remove the current image. And the
    name declares the SHA-256 of the bytes, so the reference this key can become
    commits to specific bytes that confirmation then verifies.
    """
    return f"{unit_qr_prefix(unit_id, payment_method_id)}/{digest_hex}-{uuid.uuid4()}.{extension}"


def unit_qr_key_is_mine(s3_key: str, unit_id: str, payment_method_id: str) -> bool:
    """True when ``s3_key`` is an object this method owns and nothing else.

    The confirm and delete paths ask this before they touch S3: a key under
    another Unit, another method, or the legacy account scheme is foreign, and
    signing, storing, or deleting it would act on someone else's bytes.
    """
    prefix = f"{unit_qr_prefix(unit_id, payment_method_id)}/"
    if not s3_key.startswith(prefix):
        return False
    return _QR_OBJECT_NAME.fullmatch(s3_key[len(prefix) :]) is not None


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
    updated_by_account_id: Optional[Any] = None,
    pending_qr_purge_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Render a custom-method item at ``UNIT#<unitId> / PAYMENT#<normalizedName>``.

    ``created_at`` lets a rename carry the original creation audit onto the new
    key; every other write stamps ``now_iso`` as its creation too. The QR key is
    stored only when one is attached: an absent attribute and a null read
    identically, and §4.1.2 is the only writer of a non-null value.

    ``updated_by_account_id`` is who wrote THIS revision. It defaults to the
    creator because creation is the only write where the two are known to be the
    same account; a rename or QR mutation that leaves it out credits the edit to
    whoever made the method, who may no longer admin the Unit.
    """
    identity = normalize_required_text(payment_method_id, "paymentMethodId", _PAYMENT_ID_MAX_CHARS)
    unit_identity = normalize_required_text(unit_id, "unitId")
    display = normalize_payment_display_name(display_name)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise AppError(ErrorCode.INVALID_INPUT, "version must be at least 1")
    editor = updated_by_account_id if updated_by_account_id is not None else created_by_account_id
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
        "updatedByAccountId": normalize_required_text(editor, "updatedByAccountId", _PAYMENT_ID_MAX_CHARS),
        "version": version,
    }
    if qr_code_s3_key is not None:
        item["qrCodeS3Key"] = qr_code_s3_key
    if pending_qr_purge_keys:
        # Cleanup work survives the key move: a rename that dropped this set
        # would abandon an object no row references any more, in a bucket no
        # sweeper walks. Stored as a set of strings, so a key can only be owed
        # once however many writes retired it.
        item["pendingQrPurgeKeys"] = {str(key) for key in pending_qr_purge_keys if str(key)}
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
