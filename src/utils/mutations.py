"""Shared mutation helper: the program's one idempotent conditional write path.

Leaf 1.7.2 of the Show & Sell delivery checklist. Every Show & Sell / inventory
mutation (Stages 1-5) writes through this module, so the cross-cutting rules
live once instead of in every resolver:

1. Normalized request fingerprint. Two retries of the same logical request must
   hash identically even when the client sent keys in a different order or with
   untrimmed text, and must hash differently when any meaningful value changed
   (API contract §3.1: "Reusing a key with different normalized content returns
   `INVALID_INPUT`").
2. Seven-day idempotency marker in an existing aggregate table (data model
   §8.9). The marker's key carries actor, operation type and resource scope, so
   the same caller key never collides across operations or tenants; its value
   carries the fingerprint and the original result reference. A completed retry
   returns the original result without new effects; a same-key/different-
   fingerprint request fails without writing.
3. Conditional DynamoDB transaction. The marker insertion rides in the *first*
   transaction alongside the business writes, which is what makes the whole
   operation atomic: there is no window in which a marker exists but the
   business rows do not. `ConditionCheckItem` is not permission to call
   `TransactWriteItems` (impact map §4.2), so the caller's role must grant the
   action on every table named here. ``execute()`` enforces this by refusing
   any plan whose first action is not the marker's conditional Put: a plan that
   could commit without the marker would tell the caller the write failed when
   the post-commit marker flip is rejected, and the caller's retry would
   double-apply it.
4. 90-action write-plan counting. A plan over `MAX_TRANSACTION_ACTIONS` fails
   before any DynamoDB call with `CONFLICT` and `OPERATION_TOO_LARGE` in its
   details (data model §8.10). Field maxima are not independently composable,
   so the count is of real planned actions, not of input list lengths.
5. `CONFLICT` / `RESOURCE_BUSY` classification. A cancelled transaction (a
   failed condition - a stale `expectedVersion`, an already-consumed invite, a
   guard that moved) is a non-retryable `CONFLICT`; throttling is the retryable
   `RESOURCE_BUSY`. Two distinct, correctly-scoped code sets feed the split:
   top-level fault codes go through ``src.utils.dynamodb``'s transient-error
   set, while per-item ``CancellationReasons`` throttling uses this module's
   own ``PER_ITEM_THROTTLE_CODES`` spellings.

Out of scope here by contract: the finalization-feasibility preflight (data
model §8.10) is a per-mutation computation over domain state, so each mutation
computes its own minimum resulting finalization write set and feeds the total
into one plan; this helper only enforces the resulting total.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, cast

from botocore.exceptions import BotoCoreError, ClientError

from .dynamodb import get_dynamodb_client, is_transient_client_error
from .errors import AppError, ErrorCode
from .logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.client import DynamoDBClient

logger = get_logger(__name__)

# Logical ceiling for one mutation's complete write plan (data model §8.10):
# business writes, snapshots, balances, commitments, movements, credit
# projections and the idempotency marker. DynamoDB caps a transact_write at 100
# items; the deliberate headroom is what "leaving headroom below the service
# limit" means, and it is a product contract, not a tuning knob - the spec's
# capacity arithmetic (about 29 products for an immediate sale, about 21 for
# worst-case mixed We Owe) is derived from this number.
MAX_TRANSACTION_ACTIONS: int = 90

# The throttling spellings DynamoDB reports as PER-ITEM CancellationReason
# codes inside TransactionCanceledException. They are not the top-level
# Error.Code spellings in :data:`src.utils.dynamodb.TRANSIENT_ERROR_CODES`:
# the service uses ``ThrottlingError`` / ``ProvisionedThroughputExceeded``
# at the per-item level (see the CancellationReason Code enum).
PER_ITEM_THROTTLE_CODES: frozenset[str] = frozenset({"ThrottlingError", "ProvisionedThroughputExceeded"})

# The PER-ITEM CancellationReason code for "another transaction touched this
# item concurrently". Per-item TransactionConflict and top-level
# TransactionConflictException are the same retryable contention family as
# throttling (spec 3.3: contention is RESOURCE_BUSY, never a conflict verdict):
# the client must back off and resend, not re-read and recompute.
PER_ITEM_CONTENTION_CODES: frozenset[str] = frozenset({"TransactionConflict"})

# DynamoDB hard caps a partition key at 1024 bytes; the marker PK is assembled
# from three validated segments, each allowed hundreds of characters, so the
# assembly itself must enforce the wire limit.
_PK_MAX_BYTES = 1024

# Marker retention (API contract §3.1: "retained for seven days"; impact map
# §4.1: one numeric epoch-seconds attribute across all aggregate tables).
MARKER_TTL_SECONDS: int = 7 * 24 * 60 * 60

# The attribute DynamoDB TTL is armed with on the Show & Sell aggregate tables.
# Distinct from the legacy `invites` table's `expiresAt` and from the UnitInvite
# item's own expiry horizon: the NAME is shared, the horizon is not.
MARKER_TTL_ATTRIBUTE: str = "expiresAtEpoch"

MARKER_STATUS_IN_FLIGHT = "IN_FLIGHT"
MARKER_STATUS_COMPLETED = "COMPLETED"

# The marker Put's uniqueness guard: the whole ConditionExpression is fixture
# equality against this string (placeholder alias included), and the alias must
# bind to the marker key's real partition attribute. Anything else - a
# condition this token merely appears inside (an OR whose other disjunct is
# always true, say), an inverted shape, or a binding to some other attribute -
# is not a uniqueness guard and must never open a mutation's transaction.
MARKER_PUT_CONDITION: str = "attribute_not_exists(#pk)"
MARKER_GUARD_ATTRIBUTE: str = "pk"

# Marker key layout. `BOOTSTRAP` is the fixed scope for Unit creation, whose
# marker must not depend on the Unit it is about to create (data model §8.9).
MARKER_PK_PREFIX = "IDEM"
MARKER_SK_PREFIX = "IDEM"
BOOTSTRAP_SCOPE = "BOOTSTRAP"

_IDEMPOTENCY_KEY_MAX_CHARS = 128
_SCOPE_MAX_CHARS = 512

# A marker attribute that arrives with a shape we did not write. Silently
# treating a corrupt marker as "not ours" would re-run a mutation whose earlier
# attempt may already have committed.
_MARKER_CORRUPT_MESSAGE = "Idempotency marker is unreadable; refusing to re-run the mutation."

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_KEY_SAFE = re.compile(r"^[A-Za-z0-9#:_\-.]+$")


def _canonical_scalar(value: Any) -> Optional[str]:
    """The canonical JSON form of a scalar, or None when ``value`` is a container.

    Floats must be finite, and integral floats serialize as integers so ``2`` and
    ``2.0`` agree. GraphQL makes an omitted optional argument and an explicit
    null the same request, so ``null`` is a legal scalar here; the mapping
    handler is what drops it.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Trim padding only. Internal whitespace is content: "Ann  Marie" and
        # "Ann Marie" are different strings and must not alias to one
        # fingerprint (identifiers and enum values never contain whitespace,
        # so trimming cannot alias two codes).
        return json.dumps(value.strip())
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError(f"non-finite number in fingerprint input: {value!r}")
        if isinstance(value, float) and value.is_integer():
            return json.dumps(int(value))
        return json.dumps(value)
    if value is None:
        return "null"
    return None


def _canonical_mapping(value: Mapping[Any, Any], *, drop_none: bool) -> str:
    """Canonical form of a mapping: keys sorted, ``None`` values kept by default.

    An explicit null is kept distinct from an omitted key, because for most
    mutations they are different requests (omitted = leave unchanged, null =
    clear). Create-shaped payloads, where GraphQL already equates an omitted
    optional argument with an explicit null, pass ``drop_none=True`` to opt
    into null-dropping. A mapping whose entries all end up dropped renders as
    ``{"":null}`` so it stays distinguishable from a mapping that was empty to
    begin with, and two different payloads can never render to the same string.
    """
    entries = sorted(((str(k), v) for k, v in value.items()), key=lambda entry: entry[0])
    parts = [
        f"{json.dumps(key)}:{_canonical_json(item, drop_none=drop_none)}"
        for key, item in entries
        if not (drop_none and item is None)
    ]
    if not parts:
        # An all-null mapping and a genuinely empty one must not collide, or
        # "send displayName: null" and "send no fields" would fingerprint alike.
        return "{}" if not entries else '{"":null}'
    return "{" + ",".join(parts) + "}"


def _canonical_json(value: Any, *, drop_none: bool) -> str:
    """Serialize ``value`` to canonical JSON, raising ``TypeError`` when it is not data.

    Normalization rules are fixed so a fingerprint is stable across client
    libraries - the contract normalizes the request's *content*, not the bytes a
    client happened to send: mapping keys sorted (field order never matters),
    strings trimmed at both ends (internal whitespace is content and is
    preserved, so two different texts never hash alike), explicit nulls kept
    distinct from omitted keys unless ``drop_none`` is set (create-shaped
    payloads only), and non-JSON types raising rather than being coerced -
    silently accepting an unhashable shape is how a fingerprint stops being a
    fingerprint.
    """
    scalar = _canonical_scalar(value)
    if scalar is not None:
        return scalar
    if isinstance(value, Mapping):
        return _canonical_mapping(value, drop_none=drop_none)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(item, drop_none=drop_none) for item in value) + "]"
    raise TypeError(f"unsupported value in fingerprint input: {type(value).__name__}")


def normalized_fingerprint(payload: Mapping[str, Any], *, drop_none: bool = False) -> str:
    """Return the fingerprint of a mutation request payload.

    Args:
        payload: The operation's meaningful arguments. The caller must exclude
            the ``idempotencyKey`` itself (it is in the marker key, and folding
            it in would make a replay of the same request look different).
        drop_none: Create-shaped payloads only. GraphQL equates an omitted
            optional argument with an explicit null on a create, so createUnit
            passes ``drop_none=True``; for updates, where omitted (leave
            unchanged) and null (clear the field) are different requests, the
            default keeps explicit nulls distinct.

    Returns:
        A ``sha256:<hex>`` string. The algorithm prefix makes a later change to
        the normalization a visible migration rather than a silent fingerprint
        break that invalidates in-flight markers.

    Raises:
        AppError: INVALID_INPUT when the payload cannot be canonicalized.
    """
    try:
        canonical = _canonical_json(payload, drop_none=drop_none)
    except TypeError as exc:
        raise AppError(ErrorCode.INVALID_INPUT, "Request content cannot be fingerprinted") from exc
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _validate_idempotency_key(idempotency_key: str) -> str:
    """Validate and trim the caller-supplied idempotency key (API contract §3.1)."""
    if not isinstance(idempotency_key, str):
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey must be a string")
    key = idempotency_key.strip()
    if not key or len(key) > _IDEMPOTENCY_KEY_MAX_CHARS:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"idempotencyKey must be 1-{_IDEMPOTENCY_KEY_MAX_CHARS} characters after trimming",
        )
    if _CONTROL_CHARS.search(key) or not _KEY_SAFE.fullmatch(key):
        raise AppError(ErrorCode.INVALID_INPUT, "idempotencyKey contains unsupported characters")
    return key


def _validate_scope(scope: str) -> str:
    """Validate the resource scope segment of the marker key."""
    if not isinstance(scope, str):
        raise AppError(ErrorCode.INVALID_INPUT, "idempotency scope must be a string")
    value = scope.strip()
    if not value or len(value) > _SCOPE_MAX_CHARS:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotency scope is missing or too long")
    if _CONTROL_CHARS.search(value) or not _KEY_SAFE.fullmatch(value):
        raise AppError(ErrorCode.INVALID_INPUT, "idempotency scope contains unsupported characters")
    return value


def _escape_key_segment(segment: str) -> str:
    """Escape the key-segment delimiter inside one marker partition-key segment.

    ``actor = "a#b", operation = "c"`` and ``actor = "a", operation = "b#c"``
    would both render ``IDEM#a#b#c#...`` without escaping, letting two different
    requests share one marker. '%' is not a legal segment character (see
    :data:`_KEY_SAFE`), so '%23' is an unambiguous escape.
    """
    return segment.replace("#", "%23")


def marker_partition_key(actor_id: str, operation: str, scope: str) -> str:
    """The marker's partition key: actor + operation type + resource scope.

    ``scope`` is the `unitId` when one exists, the `joinCode` for a Campaign
    join, the `inviteCode` for Unit-invite redemption (which must survive the
    invite's deletion), or :data:`BOOTSTRAP_SCOPE` for Unit creation. Keeping
    all three segments in the key is what makes the conditional insert the
    uniqueness guard: another caller's identical key, or the same caller's
    second operation, can never collide with this one. Each segment has the
    delimiter escaped (see :func:`_escape_key_segment`) and the assembled key
    is capped at DynamoDB's 1024-byte partition-key limit.
    """
    pk = (
        f"{MARKER_PK_PREFIX}#{_escape_key_segment(_validate_scope(actor_id))}"
        f"#{_escape_key_segment(_validate_scope(operation))}"
        f"#{_escape_key_segment(_validate_scope(scope))}"
    )
    if len(pk.encode("utf-8")) > _PK_MAX_BYTES:
        raise AppError(ErrorCode.INVALID_INPUT, "idempotency marker key exceeds the partition-key size limit")
    return pk


def marker_sort_key(idempotency_key: str) -> str:
    """The marker's sort key: the caller's idempotency key."""
    return f"{MARKER_SK_PREFIX}#{_validate_idempotency_key(idempotency_key)}"


@dataclass(frozen=True)
class MarkerKeys:
    """One mutation's marker item address."""

    table_key: str
    table_name: str
    pk: str
    sk: str


def marker_keys(
    *,
    table_key: str,
    table_name: str,
    actor_id: str,
    operation: str,
    scope: str,
    idempotency_key: str,
) -> MarkerKeys:
    """Resolve the marker address for one mutation.

    Args:
        table_key: The logical table name used for test overrides.
        table_name: The physical table name (from the environment map).
        actor_id: The caller's account id.
        operation: The operation type, e.g. ``createUnit``.
        scope: The resource scope (see :func:`marker_partition_key`).
        idempotency_key: The caller-supplied key.
    """
    return MarkerKeys(
        table_key=table_key,
        table_name=table_name,
        pk=marker_partition_key(actor_id, operation, scope),
        sk=marker_sort_key(idempotency_key),
    )


def marker_ttl_epoch(now_epoch: Optional[int] = None) -> int:
    """The numeric epoch-seconds TTL value for a marker written ``now``."""
    base = now_epoch if now_epoch is not None else int(time.time())
    return base + MARKER_TTL_SECONDS


def build_marker_item(
    keys: MarkerKeys,
    *,
    fingerprint: str,
    result_id: Optional[str] = None,
    status: str = MARKER_STATUS_IN_FLIGHT,
    now_epoch: Optional[int] = None,
) -> dict[str, Any]:
    """Render the marker item in DynamoDB wire form.

    The marker is an implementation detail, not a domain model (data model
    §8.9): it carries only the fingerprint, the status, and the original result
    reference a completed retry replays.
    """
    item: dict[str, Any] = {
        "pk": {"S": keys.pk},
        "sk": {"S": keys.sk},
        "fingerprint": {"S": fingerprint},
        "status": {"S": status},
        MARKER_TTL_ATTRIBUTE: {"N": str(marker_ttl_epoch(now_epoch))},
    }
    if result_id is not None:
        item["resultId"] = {"S": result_id}
    return item


class WritePlan:
    """One mutation's complete DynamoDB transaction plan, counted as it is built.

    Every staged action is a real ``TransactWriteItems`` action, marker
    insertion included, so the 90-action ceiling is enforced against what the
    transaction will actually do. The plan never executes anything: staging a
    91st action raises before a single DynamoDB call is made, which is the
    "fails before any write" half of data model §8.10.
    """

    def __init__(self, max_actions: int = MAX_TRANSACTION_ACTIONS) -> None:
        # The budget is a product contract (data model §8.10), not a tuning
        # knob: a caller must not be able to buy back headroom DynamoDB's
        # 100-item cap was leaving unused. 91 was never an acceptable plan.
        if max_actions < 1 or max_actions > MAX_TRANSACTION_ACTIONS:
            raise ValueError(f"max_actions must stay within the {MAX_TRANSACTION_ACTIONS}-action write budget")
        self._max_actions = max_actions
        self._items: list[dict[str, Any]] = []
        self._tables: set[str] = set()

    @property
    def action_count(self) -> int:
        """Number of transaction actions staged so far."""
        return len(self._items)

    @property
    def max_actions(self) -> int:
        """The plan's action budget."""
        return self._max_actions

    @property
    def tables(self) -> frozenset[str]:
        """Physical tables this plan touches - what the caller's IAM scope must cover."""
        return frozenset(self._tables)

    def add(self, action: str, item: Mapping[str, Any]) -> None:
        """Stage one ``TransactWriteItems`` action.

        Args:
            action: ``Put`` | ``Update`` | ``Delete`` | ``ConditionCheck``.
            item: The action body, already in DynamoDB wire form; it must carry
                ``TableName``.

        Raises:
            AppError: INVALID_INPUT for an unknown action or a body without a
                table; CONFLICT with ``OPERATION_TOO_LARGE`` detail when the
                plan would exceed the budget.
        """
        if action not in {"Put", "Update", "Delete", "ConditionCheck"}:
            raise AppError(ErrorCode.INVALID_INPUT, f"unsupported transaction action {action!r}")
        table = item.get("TableName")
        if not isinstance(table, str) or not table:
            raise AppError(ErrorCode.INVALID_INPUT, "transaction action is missing TableName")
        if action == "ConditionCheck" and not item.get("ConditionExpression"):
            # A condition check with no condition can never fail, so it is not a
            # guard at all - staging one hides a missing version check behind an
            # action that looks like concurrency control.
            raise AppError(ErrorCode.INVALID_INPUT, "a ConditionCheck must carry a ConditionExpression")
        if len(self._items) >= self._max_actions:
            logger.warning(
                "Write plan exceeds the transaction budget",
                table_name=table,
                action=action,
                planned_actions=len(self._items) + 1,
                max_actions=self._max_actions,
            )
            raise self.too_large_error(self._max_actions + 1)
        self._items.append({action: dict(item)})
        self._tables.add(table)

    def transact_items(self) -> list[dict[str, Any]]:
        """A copy of the staged actions, in staging order (the marker first)."""
        return [dict(entry) for entry in self._items]

    @staticmethod
    def too_large_error(planned_actions: int) -> AppError:
        """The pre-write rejection: CONFLICT carrying OPERATION_TOO_LARGE."""
        return AppError(
            ErrorCode.CONFLICT,
            ("This request is too large for one atomic write. Split it into smaller independent requests."),
            details={
                "subcode": ErrorCode.OPERATION_TOO_LARGE,
                "plannedActions": planned_actions,
                "maxActions": MAX_TRANSACTION_ACTIONS,
                "reduction": "Split the operation into independent requests that each fit the write budget.",
            },
        )


def _get_client() -> "DynamoDBClient":
    """The plain DynamoDB client (endpoint override honored).

    Wire-form payloads require the plain client, not the service resource's
    ``meta.client`` - see :func:`src.utils.dynamodb.get_dynamodb_client`.
    """
    return get_dynamodb_client()


def _contention_or_conflict_batch_error(exc: ClientError, operation: str) -> AppError:
    """The verdict for a transaction whose conditions did not hold.

    TransactionCanceledException is a transaction whose conditions did
    not hold; ConditionalCheckFailedException is the same verdict on a
    single-item write (the marker back-fill). Neither is retryable as
    sent - UNLESS the transaction was cancelled by retryable contention:
    a per-item throttle or a per-item TransactionConflict arrives as a
    CancellationReasons code inside the cancellation payload, so the
    per-item codes are consulted before the conflict verdict and any one
    of them promotes the whole transaction to the retryable RESOURCE_BUSY
    (spec 3.3).
    """
    retryable_reasons = [
        c for c in _cancellation_summary(exc) if c in PER_ITEM_THROTTLE_CODES or c in PER_ITEM_CONTENTION_CODES
    ]
    if retryable_reasons:
        logger.warning(
            "Transaction cancelled by retryable contention",
            operation=operation,
            cancellation_reasons=retryable_reasons,
        )
        return AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to write. Please retry.")
    logger.warning(
        "Transaction cancelled",
        operation=operation,
        cancellation_reasons=_cancellation_summary(exc),
    )
    return AppError(ErrorCode.CONFLICT, "The resource changed underneath this request. Re-read and try again.")


def _is_oversize_validation_exception(exc: ClientError, code: str) -> bool:
    """True when the service rejected the transaction's shape, not its content."""
    return code == "ValidationException" and _is_oversize_or_duplicate_transaction(exc)


def _oversize_or_duplicate_error(exc: ClientError, operation: str) -> AppError:
    """The CONFLICT / ``OPERATION_TOO_LARGE`` verdict for an oversized plan."""
    # The plan helper caps every plan at MAX_TRANSACTION_ACTIONS, but a
    # caller-side bug can still stage two actions on one item; DynamoDB
    # rejects that transaction with a ValidationException. It is the
    # caller's content at fault, so it maps to the same CONFLICT /
    # OPERATION_TOO_LARGE contract as an oversized plan, not an
    # internal error.
    logger.warning(
        "Transaction rejected as oversized or duplicated",
        operation=operation,
        error=str(exc),
    )
    return AppError(
        ErrorCode.CONFLICT,
        "This request is too large for one atomic write. Split it into smaller independent requests.",
        details={
            "subcode": ErrorCode.OPERATION_TOO_LARGE,
            "reduction": "Split the operation into independent requests that each fit the write budget.",
        },
    )


def _is_top_level_contention(exc: ClientError, code: str) -> bool:
    """True when the service reports in-flight concurrency at the top level.

    TransactionInProgressException and TransactionConflictException
    carry AWS retry guidance: another request touched the item set
    concurrently, so resend after a backoff rather than re-reading.
    """
    return code in ("TransactionInProgressException", "TransactionConflictException") or is_transient_client_error(exc)


def classify_transaction_error(exc: BaseException, *, operation: str) -> AppError:
    """Translate a failed ``TransactWriteItems`` into the contract's error code.

    A cancelled transaction means one of our conditions did not hold - a stale
    ``expectedVersion``, an already-consumed invite, a moved guard - so the
    client must re-read and retry the whole read/compute/write sequence, not
    just resend: that is ``CONFLICT``. Retryable contention - throttling,
    per-item ``TransactionConflict``, top-level ``TransactionInProgress`` /
    ``TransactionConflictException``, transport faults - is the retryable
    ``RESOURCE_BUSY`` (spec 3.3). A ``ValidationException`` rejecting the
    transaction's size or shape maps to ``CONFLICT`` / ``OPERATION_TOO_LARGE``.
    Anything else is an internal failure, logged with the operation name and
    reported without an internal payload.

    Args:
        exc: The exception raised by the transaction call.
        operation: Operation name for the log line only.

    Returns:
        The :class:`AppError` the caller must raise.
    """
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("TransactionCanceledException", "ConditionalCheckFailedException"):
            return _contention_or_conflict_batch_error(exc, operation)
        if _is_oversize_validation_exception(exc, code):
            return _oversize_or_duplicate_error(exc, operation)
        if _is_top_level_contention(exc, code):
            logger.warning("Transaction blocked by in-flight activity", operation=operation, error_code=code)
            return AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to write. Please retry.")
        logger.error("Transaction failed", operation=operation, error=str(exc), error_code=code)
        return AppError(ErrorCode.INTERNAL_ERROR, "Failed to save changes")
    if isinstance(exc, BotoCoreError):
        # A transport fault, not a service verdict: the same request may succeed.
        logger.warning("Transaction failed at the transport layer", operation=operation, error=str(exc))
        return AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to write. Please retry.")
    logger.error("Transaction failed unexpectedly", operation=operation, error=str(exc))
    return AppError(ErrorCode.INTERNAL_ERROR, "Failed to save changes")


# The ValidationException message fragments DynamoDB uses for a transaction
# that names too many items or touches one item with more than one action.
_OVERSIZE_OR_DUPLICATE_MARKERS = (
    "more than 100 items",
    "multiple operations on one item",
)


def _is_oversize_or_duplicate_transaction(exc: ClientError) -> bool:
    """True when a ValidationException rejects the transaction's shape, not its auth."""
    message = str(exc.response.get("Error", {}).get("Message", "")).lower()
    return any(marker in message for marker in _OVERSIZE_OR_DUPLICATE_MARKERS)


def _cancellation_reasons(exc: ClientError) -> list[dict[str, Any]]:
    """The per-condition cancellation reasons DynamoDB reported, as plain dicts."""
    raw = exc.response.get("CancellationReasons") or []
    if not isinstance(raw, list):
        return []
    # Typed as Any by the caller's own response dict; the entries are the
    # documented {Code, Message, Item?} shapes.
    return [cast("dict[str, Any]", entry) for entry in raw if isinstance(entry, dict)]


def _cancellation_summary(exc: ClientError) -> list[str]:
    """Machine-safe one-token-per-reason summary (never the item payload)."""
    return [str(reason.get("Code", "UNKNOWN")) for reason in _cancellation_reasons(exc)]


def _is_marker_put(action: Mapping[str, Any], keys: MarkerKeys) -> bool:
    """True when a staged action is THIS mutation's conditional marker insert.

    The marker Put is identified by table plus the exact key pair, and its
    condition must be this helper's own staged uniqueness guard, structurally:
    the whole ConditionExpression equal to ``MARKER_PUT_CONDITION`` AND its
    placeholder bound to the marker key's real partition attribute. An
    unconditional marker Put, or one whose condition merely CONTAINS
    ``attribute_not_exists`` (defeated inside an ``OR`` whose other disjunct is
    always true, or inverted), or whose binding points anywhere other than the
    marker key, is not a uniqueness guard, and
    :meth:`IdempotentMutationRunner.execute` refuses to commit any plan whose
    first action is not this item.
    """
    put = action.get("Put")
    if not isinstance(put, dict):
        return False
    if put.get("TableName") != keys.table_name:
        return False
    condition = put.get("ConditionExpression")
    names = put.get("ExpressionAttributeNames")
    if condition != MARKER_PUT_CONDITION:
        return False
    if not isinstance(names, dict) or names.get("#pk") != MARKER_GUARD_ATTRIBUTE:
        return False
    item = put.get("Item")
    return isinstance(item, dict) and item.get("pk") == {"S": keys.pk} and item.get("sk") == {"S": keys.sk}


def _is_marker_condition_rejection(exc: BaseException) -> bool:
    """True when a transaction cancellation was reported against the marker insert.

    DynamoDB does not say WHICH condition failed, only why in the abstract, so
    the marker's Put action asks for ``ReturnValuesOnConditionCheckFailure =
    ALL_OLD``: the reason that comes back for the losing marker condition
    carries the existing marker item, and a marker item has an unmistakable
    shape (``fingerprint`` + ``status`` attributes on an ``IDEM#...`` sort key).
    The distinction decides the retry contract: a failed marker condition means
    a concurrent request with the same key won the race, so the caller must NOT
    re-run its arithmetic - it replays the winner on its next attempt.
    """
    if not isinstance(exc, ClientError):
        return False
    if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    for reason in _cancellation_reasons(exc):
        item = reason.get("Item")
        if not isinstance(item, dict):
            continue
        sk = item.get("sk")
        if (
            "fingerprint" in item
            and "status" in item
            and isinstance(sk, dict)
            and str(sk.get("S", "")).startswith(f"{MARKER_SK_PREFIX}#")
        ):
            return True
    return False


def _marker_from_item(item: Mapping[str, Any]) -> tuple[str, str, Optional[str]]:
    """Read ``(fingerprint, status, result_id)`` out of a marker item.

    Raises:
        AppError: INTERNAL_ERROR when a marker we found does not carry the
            attributes we always write. Falling back to "no marker" here would
            re-execute a mutation whose first attempt may already have
            committed, which is the failure this whole module exists to prevent.
    """
    fingerprint = item.get("fingerprint")
    status = item.get("status")
    if not isinstance(fingerprint, dict) or not isinstance(fingerprint.get("S"), str):
        raise AppError(ErrorCode.INTERNAL_ERROR, _MARKER_CORRUPT_MESSAGE)
    if not isinstance(status, dict) or not isinstance(status.get("S"), str):
        raise AppError(ErrorCode.INTERNAL_ERROR, _MARKER_CORRUPT_MESSAGE)
    result_id = item.get("resultId")
    return (
        fingerprint["S"],
        status["S"],
        result_id["S"] if isinstance(result_id, dict) and isinstance(result_id.get("S"), str) else None,
    )


def utc_now_iso() -> str:
    """Timestamp used for marker audit fields."""
    return datetime.now(timezone.utc).isoformat()


class IdempotentMutationRunner:
    """Runs one Show & Sell / inventory mutation through marker + transaction.

    The runner is stateless across calls; construct one per handler invocation
    (or reuse a module-level instance - it holds no per-request state).
    """

    def __init__(self, client: Optional["DynamoDBClient"] = None) -> None:
        """
        Args:
            client: Test slot for the DynamoDB client. When omitted the shared
                client from :mod:`src.utils.dynamodb` is used, so the
                ``DYNAMODB_ENDPOINT`` override and test overrides keep working.
        """
        self._client = client

    def _get_client(self) -> "DynamoDBClient":
        return self._client if self._client is not None else _get_client()

    def load_marker(self, keys: MarkerKeys) -> Optional[dict[str, Any]]:
        """Strongly consistent read of an existing marker item, or None."""
        try:
            response = self._get_client().get_item(
                TableName=keys.table_name,
                Key={"pk": {"S": keys.pk}, "sk": {"S": keys.sk}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise classify_transaction_error(exc, operation="loadIdempotencyMarker") from exc
        item = response.get("Item")
        return item if isinstance(item, dict) else None

    def replay_or_reject(
        self,
        keys: MarkerKeys,
        fingerprint: str,
        *,
        operation: str,
        load_result: Optional[Callable[[str], Any]] = None,
    ) -> tuple[bool, Any]:
        """Decide whether a prior attempt already answered this request.

        Returns:
            ``(handled, result)``. When ``handled`` is True the caller must
            return ``result`` and write nothing. When it is False the marker is
            absent (or was left in flight by a crashed attempt, which the
            transaction's marker condition resolves) and the caller may
            proceed - but a completed marker without a usable ``load_result``
            raises, because answering a replay with a fresh write would break
            the contract.

        Raises:
            AppError: INVALID_INPUT for the same key with a different
                fingerprint; INTERNAL_ERROR for a corrupt marker (a status we
                do not recognize, or a completed marker with no replayable
                result). An in-flight marker is replayed, and the marker race
                surfaces as RESOURCE_BUSY only in :meth:`execute`.
        """
        marker = self.load_marker(keys)
        if marker is None:
            return (False, None)
        marker_fingerprint, status, result_id = _marker_from_item(marker)
        if marker_fingerprint != fingerprint:
            # Same key, different normalized content: never write, never replay.
            logger.warning(
                "Idempotency key reused with different content",
                operation=operation,
                table_name=keys.table_name,
            )
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "This idempotencyKey was already used with different request content.",
                details={"subcode": "IDEMPOTENCY_FINGERPRINT_MISMATCH"},
            )
        if status not in (MARKER_STATUS_COMPLETED, MARKER_STATUS_IN_FLIGHT):
            logger.error("Idempotency marker status is unknown", operation=operation, status=status)
            raise AppError(ErrorCode.INTERNAL_ERROR, _MARKER_CORRUPT_MESSAGE)
        # IN_FLIGHT is not a "wait and see" state here: the marker insert rides
        # INSIDE the transaction, so an in-flight marker proves the business
        # writes already committed and only the status back-fill is pending. The
        # result reference was staged with the insert precisely so this retry is
        # answerable.
        if load_result is None or result_id is None:
            logger.error(
                "Idempotency marker cannot be replayed",
                operation=operation,
                table_name=keys.table_name,
                marker_status=status,
                has_result_id=result_id is not None,
                has_loader=load_result is not None,
            )
            raise AppError(ErrorCode.INTERNAL_ERROR, _MARKER_CORRUPT_MESSAGE)
        return (True, load_result(result_id))

    def execute(
        self,
        keys: MarkerKeys,
        plan: WritePlan,
        *,
        operation: str,
        fingerprint: str,
        result_id: Optional[str] = None,
        load_result: Optional[Callable[[str], Any]] = None,
        backfill_marker: bool = True,
    ) -> Any:
        """Run the whole contract for one mutation and return its result value.

        Args:
            keys: Marker address for this request.
            plan: The complete write plan, marker insertion staged FIRST (see
                :meth:`stage_marker`).
            operation: Operation name for logs and error detail.
            fingerprint: :func:`normalized_fingerprint` of the request payload.
            result_id: Identifier of the row this mutation creates, recorded in
                the marker so a replay can be answered. Required when
                ``load_result`` is given.
            load_result: Called with the marker's stored ``resultId`` to rebuild
                the original result for a completed retry.
            backfill_marker: When True, the marker is flipped to COMPLETED with
                the result id after the transaction commits.

        Returns:
            The freshly produced ``result_id``, or the replayed original result.

        Raises:
            AppError: INVALID_INPUT (fingerprint mismatch), CONFLICT (a failed
                condition, including an oversize plan), RESOURCE_BUSY (throttle
                or in-flight race), INTERNAL_ERROR (unexpected failure).
        """
        handled, replayed = self.replay_or_reject(keys, fingerprint, operation=operation, load_result=load_result)
        if handled:
            return replayed
        items = plan.transact_items()
        if not items:
            raise AppError(ErrorCode.INVALID_INPUT, "A mutation must stage at least one write action")
        if plan.action_count > MAX_TRANSACTION_ACTIONS:
            # WritePlan.add enforces its own budget; this re-check closes the
            # loop on the contract ceiling itself, so a plan object that did
            # not come out of WritePlan cannot bypass the 90-action limit
            # either (data model §8.10).
            raise WritePlan.too_large_error(plan.action_count)
        if not _is_marker_put(items[0], keys):
            # The marker insert is what makes the retry contract answerable: a
            # plan that committed without it would leave a caller whose
            # post-commit marker flip fails holding a committed write it was
            # told failed - and its retry would apply the write twice. Refuse
            # the plan before any DynamoDB call is made.
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "the write plan must stage this mutation's conditional idempotency marker Put as its first action",
            )
        try:
            self._get_client().transact_write_items(TransactItems=cast(Any, items))
        except (ClientError, BotoCoreError) as exc:
            classified = classify_transaction_error(exc, operation=operation)
            if classified.error_code == ErrorCode.CONFLICT and _is_marker_condition_rejection(exc):
                # A concurrent identical request committed first. Replaying it
                # is correct only once its marker is visible; until then the
                # caller retries.
                logger.warning("Idempotency marker raced", operation=operation, table_name=keys.table_name)
                raise AppError(
                    ErrorCode.RESOURCE_BUSY,
                    "An earlier attempt with this idempotencyKey is still finishing. Retry shortly.",
                    details={"subcode": "IDEMPOTENCY_KEY_RACE"},
                ) from exc
            raise classified from exc
        if backfill_marker and result_id is not None:
            self.complete_marker(keys, fingerprint=fingerprint, result_id=result_id)
        return result_id

    def stage_marker(self, plan: WritePlan, keys: MarkerKeys, *, fingerprint: str, result_id: str) -> None:
        """Stage the marker's conditional insert as the plan's first action.

        The condition is what makes the marker insertion the uniqueness guard,
        and the reason it must be staged before the business writes: DynamoDB
        applies a transaction atomically, so a retry can never observe a marker
        whose business rows are missing.

        ``result_id`` is required and must be known BEFORE the write (every Show
        & Sell mutation generates its row id up front). Recording it in the
        inserted marker - not only in the post-commit back-fill - is what makes
        a replay answerable even if the process dies between the transaction and
        the back-fill; a marker without a result reference would leave the
        caller unable to answer its own retry for seven days, and re-running the
        mutation would double-apply it.
        """
        if not isinstance(result_id, str) or not result_id.strip():
            raise AppError(ErrorCode.INVALID_INPUT, "an idempotency marker needs its result id before writing")
        plan.add(
            "Put",
            {
                "TableName": keys.table_name,
                "Item": build_marker_item(keys, fingerprint=fingerprint, result_id=result_id),
                "ConditionExpression": MARKER_PUT_CONDITION,
                "ExpressionAttributeNames": {"#pk": MARKER_GUARD_ATTRIBUTE},
                "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
            },
        )

    def complete_marker(self, keys: MarkerKeys, *, fingerprint: str, result_id: str) -> None:
        """Flip a marker to COMPLETED with its result reference.

        Conditional on the fingerprint and the in-flight status, so a concurrent
        writer that replaced the marker can never be overwritten by this
        back-fill.
        """
        try:
            self._get_client().update_item(
                TableName=keys.table_name,
                Key={"pk": {"S": keys.pk}, "sk": {"S": keys.sk}},
                UpdateExpression="SET #status = :completed, #resultId = :resultId, #updatedAt = :now",
                ExpressionAttributeNames={
                    "#status": "status",
                    "#resultId": "resultId",
                    "#updatedAt": "updatedAt",
                    "#fingerprint": "fingerprint",
                },
                ExpressionAttributeValues={
                    ":completed": {"S": MARKER_STATUS_COMPLETED},
                    ":in_flight": {"S": MARKER_STATUS_IN_FLIGHT},
                    ":resultId": {"S": result_id},
                    ":now": {"S": utc_now_iso()},
                    ":fingerprint": {"S": fingerprint},
                },
                ConditionExpression="#fingerprint = :fingerprint AND #status = :in_flight",
            )
        except (ClientError, BotoCoreError) as exc:
            raise classify_transaction_error(exc, operation="completeIdempotencyMarker") from exc
