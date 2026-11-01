"""Transfer profile ownership to another account.

This handler transfers ownership of a SellerProfile to a new owner who must already
have access via a share. The transfer involves:
1. Verifying caller is current owner (or admin)
2. Verifying new owner has existing share
3. Repairing the shares first (re-pointing third-party shares' ownerAccountId
   at the incoming owner)
4. Atomically deleting the old owner's base-table record and creating a new record
   with the updated ownerAccountId (the hash key cannot be updated in place)
5. Idempotently deleting the new owner's inbound share, after the commit

Because ownership is encoded in the profile base-table hash key, deleting the old
owner's record invalidates any other shares that still reference the previous owner,
so stale shares are automatically rejected by subsequent authorization checks. That
makes the share repair load-bearing rather than cleanup, and it is the only thing
that re-points those shares at the new owner. It therefore runs before the
destructive step and is rolled back if anything after it fails, so the transfer
either lands with every share repaired or leaves the pre-transfer state untouched
for a retry to converge (#549).
"""

import os
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id, require_str
    from utils.auth import has_mfa, is_admin
    from utils.dynamodb import is_transient_client_error, tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.pagination import query_all_items
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id, require_str
    from ..utils.auth import has_mfa, is_admin
    from ..utils.dynamodb import is_transient_client_error, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id, ensure_profile_id
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling


logger = get_logger(__name__)
_type_serializer = TypeSerializer()


def _confirm_ownership_strongly_consistently(db_profile_id: str, db_caller_id: str) -> Optional[Dict[str, Any]]:
    """Return the profile iff a strongly consistent base-table read proves ownership.

    Ownership is encoded in the base-table hash key (ownerAccountId), so an item
    returned by a consistent GetItem under the caller's key proves the caller is
    the current owner. The profileId-index GSI is eventually consistent and can
    keep projecting the previous owner immediately after a transfer, so it is
    never used as the authoritative owner signal (#438).
    """
    response = tables.profiles.get_item(
        Key={"ownerAccountId": db_caller_id, "profileId": db_profile_id}, ConsistentRead=True
    )
    item: Optional[Dict[str, Any]] = response.get("Item")
    return item


def _get_and_verify_profile(db_profile_id: str, db_caller_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Get profile and verify caller is owner or admin."""
    # Strongly consistent owner confirmation first; only fall back to the
    # eventually consistent GSI query when the base-table read is negative.
    profile = _confirm_ownership_strongly_consistently(db_profile_id, db_caller_id)
    if profile is not None:
        # A consistent read under the caller's key proves ownership.
        caller_is_owner = True
    else:
        # Ownership could not be established. The GSI query is used only to
        # locate the profile (NOT_FOUND vs forbidden); its stale projection
        # must never be treated as proof of ownership (#438).
        profile_response = tables.profiles.query(
            IndexName="profileId-index", KeyConditionExpression=Key("profileId").eq(db_profile_id)
        )
        if not profile_response.get("Items"):
            raise AppError(ErrorCode.NOT_FOUND, f"Profile not found: {db_profile_id}")
        profile = profile_response["Items"][0]
        caller_is_owner = False

    if not caller_is_owner:
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Only the profile owner or an admin can transfer ownership")
        # An admin (not the owner) may transfer any profile, but only with MFA (#336).
        if not has_mfa(event):
            raise AppError(ErrorCode.MFA_REQUIRED, "MFA required")

    return profile


def _verify_new_owner_has_share(db_profile_id: str, db_new_owner_id: str, caller_is_admin: bool) -> None:
    """Verify new owner has existing share (skip for admin transfers)."""
    if not caller_is_admin:
        share_response = tables.shares.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
        if "Item" not in share_response:
            raise AppError(ErrorCode.INVALID_INPUT, "New owner must have existing access to the profile")


def _resolve_transfer_input(event: Dict[str, Any]) -> Tuple[str, str, str]:
    """Resolve and validate the transfer input into database-form ids.

    Returns the ``(db_profile_id, db_new_owner_id, db_caller_id)`` triple the
    transfer runs on. Raises ``UNAUTHORIZED`` when the caller identity is
    missing and ``AppError`` (via ``require_str``/``ensure_*``) when an argument
    is absent or malformed.
    """
    caller_account_id = get_caller_id(event)
    if not caller_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    input_args = event.get("arguments", {}).get("input", {})
    profile_id = require_str(input_args, "profileId")
    new_owner_account_id = require_str(input_args, "newOwnerAccountId")

    db_profile_id = ensure_profile_id(profile_id) or ""
    db_new_owner_id = ensure_account_id(new_owner_account_id) or ""
    db_caller_id = ensure_account_id(caller_account_id) or ""
    return db_profile_id, db_new_owner_id, db_caller_id


def _transfer_ownership(profile: Dict[str, Any], db_profile_id: str, db_new_owner_id: str) -> None:
    """Transfer ownership atomically using a DynamoDB transaction.

    The old profile record is deleted and the new record (with the updated owner)
    is written in a single transact_write_items call so the profile cannot be lost
    if one of the operations fails. The step is idempotent: an attempt whose
    transaction already committed (the profile is under the new owner) has nothing
    left to change, so a client retry converges instead of erroring.
    """
    old_owner_id = profile["ownerAccountId"]
    if old_owner_id == db_new_owner_id:
        return
    new_profile = {**profile, "ownerAccountId": db_new_owner_id}

    old_key = {"ownerAccountId": old_owner_id, "profileId": db_profile_id}

    endpoint_url = os.getenv("DYNAMODB_ENDPOINT")
    dynamodb_client = boto3.client("dynamodb", endpoint_url=endpoint_url)
    table_name = tables.profiles.name
    try:
        dynamodb_client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": table_name,
                        "Key": {k: _type_serializer.serialize(v) for k, v in old_key.items()},
                        "ConditionExpression": "attribute_exists(ownerAccountId)",
                    }
                },
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": {k: _type_serializer.serialize(v) for k, v in new_profile.items()},
                        "ConditionExpression": "attribute_not_exists(ownerAccountId)",
                    }
                },
            ]
        )
    except ClientError as e:
        logger.error(
            "Failed to transfer profile ownership in DynamoDB",
            profile_id=db_profile_id,
            new_owner_account_id=db_new_owner_id,
            error=str(e),
            exc_info=True,
        )
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Failed to transfer profile ownership",
        ) from e

    # Keep the returned profile dict in sync with the persisted record.
    profile["ownerAccountId"] = db_new_owner_id


def _remove_new_owner_share_after_commit(db_profile_id: str, db_new_owner_id: str) -> None:
    """Delete the new owner's inbound share once ownership has committed.

    The deletion runs after the commit so the destructive profile step no longer
    depends on it: deleting beforehand would strand the verify step for any
    attempt that died between the repair and the commit, for which a plain retry
    is blocked by the (deliberately intact) new-owner-access check. A plain delete
    is idempotent, so a lost or repeated deletion converges on the next attempt.
    The transfer cannot be undone at this point, so a failed deletion is logged for
    the operator (naming the affected account) and the committed transfer reports
    success.
    """
    try:
        tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
    except Exception as e:
        logger.error(
            "Failed to delete the new owner's share after ownership transfer",
            profile_id=db_profile_id,
            target_account_id=db_new_owner_id,
            error=str(e),
            exc_info=True,
        )


def _transfer_without_commit_confirmed(db_profile_id: str, db_old_owner_id: str) -> bool:
    """Confirm via consistent read that the transfer has not committed.

    A precondition is that the old owner's base-table record is still in place. If
    the confirm read itself fails, the pre-transfer state is unknown, so the
    answer is treated as "committed" and no rollback is attempted: undoing a
    committed transfer would strand every collaborator just the same.
    """
    try:
        return _confirm_ownership_strongly_consistently(db_profile_id, db_old_owner_id) is not None
    except Exception as e:
        logger.error(
            "Failed to confirm pre-transfer profile state; skipping rollback",
            profile_id=db_profile_id,
            error=str(e),
            exc_info=True,
        )
        return False


class _ShareRepairFailures(NamedTuple):
    """Counts of shares the repair step could not fix, split by whether a retry helps.

    ``transient`` is an AWS condition that may clear on its own (throttling), so
    a retry is meaningful. ``permanent`` is a condition that will fail
    identically forever (a failed ``ConditionExpression`` on a share revoked
    mid-transfer, a missing table, a denied permission), so the caller must not
    be invited to retry (#549).
    """

    transient: int
    permanent: int


class _ShareRepair(NamedTuple):
    """The share mutations a repair applied, recorded so they can be undone.

    The repair runs before the ownership transfer commits, so a failure of the
    transfer (or of the repair itself) can be rolled back to the exact
    pre-transfer share state instead of leaving shares pointing at an owner whose
    profile record does not exist, which would lock out every collaborator (#549).
    """

    reassigned: List[Tuple[str, str]]  # (targetAccountId, ownerAccountId before the repair)
    repaired_owner_id: str


_SHARE_REPAIR_RETRYABLE = "Temporarily unable to update profile shares. Please retry."
_SHARE_REPAIR_PERMANENT = "Failed to update profile shares. Please contact support."


def _undo_share_repair(db_profile_id: str, repair: _ShareRepair) -> None:
    """Roll an applied share repair back to the pre-transfer state.

    Best effort by design: it runs on a path that is already raising, and a
    rollback failure is an operator problem (logged with the affected
    collaborator), not something the caller can act on.
    """
    for target_account_id, previous_owner_id in repair.reassigned:
        try:
            tables.shares.update_item(
                Key={"profileId": db_profile_id, "targetAccountId": target_account_id},
                UpdateExpression="SET ownerAccountId = :previous_owner",
                ConditionExpression="attribute_exists(targetAccountId) AND ownerAccountId = :repaired_owner",
                ExpressionAttributeValues={
                    ":previous_owner": previous_owner_id,
                    ":repaired_owner": repair.repaired_owner_id,
                },
            )
        except Exception as e:
            if (
                isinstance(e, ClientError)
                and e.response.get("Error", {}).get("Code", "") == "ConditionalCheckFailedException"
            ):
                # The share was revoked after the repair applied it, or a concurrent
                # committed transfer has since repaired it to another owner.
                # Its rollback target is no longer in the state this repair produced,
                # so overwriting it would be wrong; treat the conflict as the
                # rollback already being done.
                continue
            logger.error(
                "Failed to roll back share after aborted ownership transfer",
                profile_id=db_profile_id,
                target_account_id=target_account_id,
                error=str(e),
                exc_info=True,
            )


def _repair_shares(
    db_profile_id: str, db_new_owner_id: str, old_owner_id: str
) -> Tuple[_ShareRepair, _ShareRepairFailures]:
    """Point every share of the profile at the incoming owner, before the transfer commits.

    - Re-points every share's ownerAccountId (including the incoming owner's own
      inbound share) at the new owner; the new owner's share is not deleted here.

    This step is load-bearing, not cleanup: the authorization layer re-validates a
    share against the owner recorded on the share (see ``_is_share_valid`` in
    ``src/utils/auth.py``). A share recording the wrong owner is dead, so every
    collaborator it covers is locked out, and this is the only code that re-points
    those shares. It therefore runs first and is rolled back by the caller if the
    transfer does not commit, so no retry of this mutation can end in a silently
    broken share graph (#549).

    Returns:
        The changes actually applied (for rollback) and the shares that could not
        be updated, split into transient failures (retrying may help) and
        permanent ones (retrying cannot help).

    Raises:
        AppError: when the share query itself fails, since without it no share can
            be repaired and nothing has been changed yet. A throttled query is a
            retryable RESOURCE_BUSY; any other client error is INTERNAL_ERROR, and
            anything that is not a client error at all is a bug and propagates.
    """
    try:
        shares = query_all_items(
            tables.shares,
            {"KeyConditionExpression": Key("profileId").eq(db_profile_id)},
        )
    except ClientError as e:
        if is_transient_client_error(e):
            logger.warning(
                "Share query before ownership transfer throttled",
                profile_id=db_profile_id,
                error=str(e),
                exc_info=True,
            )
            raise AppError(ErrorCode.RESOURCE_BUSY, _SHARE_REPAIR_RETRYABLE) from e
        logger.error(
            "Failed to query shares before ownership transfer",
            profile_id=db_profile_id,
            error=str(e),
            exc_info=True,
        )
        raise AppError(ErrorCode.INTERNAL_ERROR, _SHARE_REPAIR_PERMANENT) from e

    reassigned: List[Tuple[str, str]] = []
    transient_failures = 0
    permanent_failures = 0
    for share in shares:
        target_account_id = share.get("targetAccountId")
        if not target_account_id:
            continue
        try:
            tables.shares.update_item(
                Key={"profileId": db_profile_id, "targetAccountId": target_account_id},
                UpdateExpression="SET ownerAccountId = :new_owner",
                ExpressionAttributeValues={":new_owner": db_new_owner_id},
                ConditionExpression="attribute_exists(profileId) AND attribute_exists(targetAccountId)",
            )
            reassigned.append((target_account_id, share.get("ownerAccountId") or old_owner_id))
        except Exception as e:
            # Any exception aborts the repair into the failure-count path so the
            # caller rolls back every write applied so far; a raw non-client error
            # (a bug or a dropped connection) is a permanent failure, exactly like
            # an unretryable client error.
            transient = isinstance(e, ClientError) and is_transient_client_error(e)
            if transient:
                transient_failures += 1
            else:
                permanent_failures += 1
            logger.error(
                "Failed to update share before ownership transfer",
                profile_id=db_profile_id,
                target_account_id=target_account_id,
                transient=transient,
                error=str(e),
                exc_info=True,
            )
    return (
        _ShareRepair(reassigned=reassigned, repaired_owner_id=db_new_owner_id),
        _ShareRepairFailures(transient=transient_failures, permanent=permanent_failures),
    )


@with_error_handling(error_message="Failed to transfer profile ownership")
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Transfer profile ownership."""
    db_profile_id, db_new_owner_id, db_caller_id = _resolve_transfer_input(event)

    profile = _get_and_verify_profile(db_profile_id, db_caller_id, event)
    # Only an MFA-verified admin skips the share check; everyone else (including a
    # plain owner) must transfer to a user who already has a share (#336).
    caller_is_admin = is_admin(event) and has_mfa(event)
    _verify_new_owner_has_share(db_profile_id, db_new_owner_id, caller_is_admin)

    # The third-party share repair runs before the destructive profile
    # transaction, so a failure of either leaves the pre-transfer state intact and
    # the caller's retry takes the ordinary path again (#549). The new owner's own
    # share is deleted only after the commit, idempotently, so a crash or failure
    # at that step converges on a retry instead of stranding the verify step.
    repair, failures = _repair_shares(db_profile_id, db_new_owner_id, profile["ownerAccountId"])
    if failures.transient or failures.permanent:
        _undo_share_repair(db_profile_id, repair)
        logger.error(
            "Ownership transfer aborted; share repair rolled back",
            profile_id=db_profile_id,
            new_owner_account_id=db_new_owner_id,
            transient_failure_count=failures.transient,
            permanent_failure_count=failures.permanent,
        )
        # A permanent failure is never invited to retry: it would fail identically.
        if failures.transient:
            raise AppError(ErrorCode.RESOURCE_BUSY, _SHARE_REPAIR_RETRYABLE)
        raise AppError(ErrorCode.INTERNAL_ERROR, _SHARE_REPAIR_PERMANENT)

    try:
        _transfer_ownership(profile, db_profile_id, db_new_owner_id)
    except AppError:
        # The transaction is atomic, so a ClientError-turned-AppError proves the
        # transfer never committed and the profile still lives under the old
        # owner; shares re-pointed at the incoming owner would lock every
        # collaborator out until the next attempt, so roll them back.
        _undo_share_repair(db_profile_id, repair)
        raise
    except Exception as e:
        # A raw non-client error (a BotoCoreError from the transaction) took this
        # same rollback path too, so the repaired shares are never left on disk.
        # Unlike the ClientError case the commit state is unknown, so a consistent
        # read guards against un-doing an already-committed transfer.
        if _transfer_without_commit_confirmed(db_profile_id, profile["ownerAccountId"]):
            _undo_share_repair(db_profile_id, repair)
            logger.error(
                "Ownership transfer aborted; share repair rolled back",
                profile_id=db_profile_id,
                new_owner_account_id=db_new_owner_id,
            )
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to transfer profile ownership") from e

    _remove_new_owner_share_after_commit(db_profile_id, db_new_owner_id)

    return profile
