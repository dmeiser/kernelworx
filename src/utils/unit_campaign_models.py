"""UnitCampaign, membership, and join-guard persistence (delivery checklist §1.4).

Stage 1 lays the Unit Campaign down at the physical key shapes of data model
§6.2, all on the ``unit_campaigns`` table::

    UNIT_CAMPAIGN#<unitCampaignId>            / METADATA          (§5.5)
    UNIT_CAMPAIGN#<unitCampaignId>            / MEMBERSHIP#<profileId>   (§5.6)
    JOIN_CODE#<joinCode>                      / UNIT_CAMPAIGN#<id>       (§5.5)
    SCOUT_CAMPAIGN#<campaignId>               / MEMBERSHIP_GUARD  (§5.6)

This module owns the persistence rules §1.4 names — identity, join-code
uniqueness, the immutable fields, membership status and audit, and the guard
that makes "one ACTIVE membership per Scout Campaign" an enforced condition
rather than a convention. It reads and writes no decision about WHO may call it;
authorization lives with the resolvers (§1.5) and :mod:`src.utils.unit_auth`.

The invariants enforced here:

- A join code is a reusable 16-character credential whose uniqueness is a real
  constraint: the pointer item is created and deleted in the SAME transaction as
  the campaign row; a consistent pointer read rejects a code that already names
  another campaign, and the pair's conditional inserts keep the winning create
  single (§5.5, §6.2).
- ``catalogId`` is immutable after creation. Inventory, Order origin, and event
  product identity all key on it, so moving a campaign between catalogs
  implicitly would corrupt all three (:data:`IMMUTABLE_CAMPAIGN_FIELDS`).
- Membership identity is ``(unitCampaignId, profileId)`` and its ``campaignId``
  never changes; a rejoin reactivates that same record rather than starting a
  second participation history (§5.6).
- The guard, not the historical ``Campaign.unitCampaignId`` link, decides whether
  a Scout Campaign is currently joined. ``activeUnitCampaignId`` is absent when
  nothing is active, and removal clears it while leaving the Campaign's latest
  link in place for history (§8.2, API-FIX-05).
"""

from __future__ import annotations

import secrets
import uuid
from decimal import Decimal
from string import ascii_uppercase, digits
from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .mutations import wire_key, wire_value
from .pagination import query_all_items
from .unit_models import MAX_ID_LENGTH, METADATA_SK, normalize_required_text

# --- Key layout (data model §6.2) ------------------------------------------------

UNIT_CAMPAIGN_PK_PREFIX = "UNIT_CAMPAIGN"
MEMBERSHIP_SK_PREFIX = "MEMBERSHIP"
JOIN_CODE_PK_PREFIX = "JOIN_CODE"
SCOUT_CAMPAIGN_PK_PREFIX = "SCOUT_CAMPAIGN"
MEMBERSHIP_GUARD_SK = "MEMBERSHIP_GUARD"

# --- Membership vocabulary (data model §5.6, SDL MembershipStatus) ---------------

MEMBERSHIP_STATUS_ACTIVE = "ACTIVE"
MEMBERSHIP_STATUS_REMOVED = "REMOVED"
MEMBERSHIP_STATUSES: frozenset[str] = frozenset({MEMBERSHIP_STATUS_ACTIVE, MEMBERSHIP_STATUS_REMOVED})

# --- Join-code credential shape --------------------------------------------------

JOIN_CODE_LENGTH = 16
# Join codes are handed out in chat and printed on flyers, so they stay upper-case
# alphanumeric (a Scout retyping one from a phone has no case to preserve). Unlike
# the Unit-invite bearer code they are reusable and public-ish: the pointer row
# (its read and its conditional insert), not the alphabet, is what makes a
# collision impossible — a 16-character code is only unique because it is looked
# up before it is written.
JOIN_CODE_ALPHABET = ascii_uppercase + digits

# Campaign years are validated as years, not as arbitrary integers: a transposed
# "2206" would otherwise create a campaign that lists in every season view forever.
MIN_CAMPAIGN_YEAR = 1900
MAX_CAMPAIGN_YEAR = 2100

# Fields a Unit Campaign update may never change (§5.5, §1.4.1). ``catalogId`` is
# the load-bearing one: inventory balances, Order origin, and event product
# identity all key on it, so a silent catalog move would strand all three.
IMMUTABLE_CAMPAIGN_FIELDS: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "unitCampaignId",
        "unitId",
        "catalogId",
        "joinCode",
        "createdAt",
        "createdByAccountId",
        "version",
    }
)


# --- Key builders ----------------------------------------------------------------


def unit_campaign_pk(unit_campaign_id: str) -> str:
    """Partition key holding a Unit Campaign's metadata and its memberships."""
    return f"{UNIT_CAMPAIGN_PK_PREFIX}#{unit_campaign_id}"


def unit_campaign_metadata_key(unit_campaign_id: str) -> Dict[str, str]:
    """The Unit Campaign metadata item's key pair."""
    return {"pk": unit_campaign_pk(unit_campaign_id), "sk": METADATA_SK}


def membership_sk(profile_id: str) -> str:
    """Sort key of one Scout's membership on a Unit Campaign."""
    return f"{MEMBERSHIP_SK_PREFIX}#{profile_id}"


def membership_key(unit_campaign_id: str, profile_id: str) -> Dict[str, str]:
    """The membership item's key pair: one identity per ``(campaign, Scout)``."""
    return {"pk": unit_campaign_pk(unit_campaign_id), "sk": membership_sk(profile_id)}


def join_code_pk(join_code: str) -> str:
    """Partition key of a join-code pointer, addressed by the credential alone.

    ``joinUnitCampaign`` and ``unitCampaignJoinInfo`` know only the code, so the
    pointer is read through a Query on this key (§5.5).
    """
    return f"{JOIN_CODE_PK_PREFIX}#{join_code}"


def join_code_pointer_key(join_code: str, unit_campaign_id: str) -> Dict[str, str]:
    """The pointer item's key pair."""
    return {"pk": join_code_pk(join_code), "sk": unit_campaign_pk(unit_campaign_id)}


def guard_key(campaign_id: str) -> Dict[str, str]:
    """The Scout Campaign's authoritative active-join lock (§5.6)."""
    return {"pk": f"{SCOUT_CAMPAIGN_PK_PREFIX}#{campaign_id}", "sk": MEMBERSHIP_GUARD_SK}


# --- Normalization and validation ------------------------------------------------


def _invalid(field: str, rule: str) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


def normalize_campaign_year(value: Any) -> int:
    """Validate ``campaignYear`` as a year.

    A ``Decimal`` arrives from DynamoDB reads, and a bool is rejected explicitly:
    ``True`` is an ``int`` in Python, and accepting it would store year 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid("campaignYear", "must be an integer year")
    year = int(value)
    if year < MIN_CAMPAIGN_YEAR or year > MAX_CAMPAIGN_YEAR:
        raise _invalid("campaignYear", f"must be between {MIN_CAMPAIGN_YEAR} and {MAX_CAMPAIGN_YEAR}")
    return year


def new_join_code() -> str:
    """A fresh 16-character join code, generated where the campaign is created."""
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


def new_unit_campaign_id() -> str:
    """A stable Unit Campaign identity, generated before any write.

    Never derived from name, year, or join code: renaming a campaign or
    re-issuing its code must not move its inventory, roster, or Order origin
    (§5.5, and the same law the Unit identity follows).
    """
    return str(uuid.uuid4())


def is_valid_join_code(value: Any) -> bool:
    """True only for a well-formed join code.

    Shape-checking is not authorization and discloses nothing: an oversized or
    mistyped string cannot be a code this server issued, and rejecting it here
    keeps the pointer Query off an impossible key.
    """
    return isinstance(value, str) and len(value) == JOIN_CODE_LENGTH and set(value) <= set(JOIN_CODE_ALPHABET)


def normalize_join_code(value: Any) -> str:
    """Validate a join code as issued by this server."""
    if not is_valid_join_code(value):
        raise _invalid("joinCode", f"must be {JOIN_CODE_LENGTH} characters from A-Z and 0-9")
    return str(value)


def normalize_membership_status(value: Any) -> str:
    """Validate ``MembershipStatus``; anything else is a programming error surface.

    Omitting the field is the builder's default; passing null is not the same
    thing as omitting it, so it is refused rather than quietly defaulted.
    """
    if not isinstance(value, str) or value not in MEMBERSHIP_STATUSES:
        raise _invalid("status", "must be ACTIVE or REMOVED")
    return value


def normalize_campaign_id(value: Any, field: str) -> str:
    """Validate an identifier that is stored, not derived."""
    return normalize_required_text(value, field, MAX_ID_LENGTH)


# --- Item builders (the only place these items are built) ------------------------


def build_unit_campaign_item(
    *,
    unit_campaign_id: Any,
    unit_id: Any,
    campaign_name: Any,
    campaign_year: Any,
    catalog_id: Any,
    join_code: Any,
    created_by_account_id: Any,
    now_iso: Any,
    is_active: Any = True,
) -> Dict[str, Any]:
    """Build a new Unit Campaign item; every field is validated here.

    ``version`` starts at 1 and ``isActive`` is a real DynamoDB boolean: unlike
    the Unit rows, the campaign's active state is read as a predicate by join and
    listing paths, not inferred from a counter.
    """
    return {
        "pk": unit_campaign_pk(normalize_campaign_id(unit_campaign_id, "unitCampaignId")),
        "sk": METADATA_SK,
        "unitCampaignId": normalize_campaign_id(unit_campaign_id, "unitCampaignId"),
        "unitId": normalize_campaign_id(unit_id, "unitId"),
        "campaignName": normalize_required_text(campaign_name, "campaignName"),
        "campaignYear": normalize_campaign_year(campaign_year),
        "catalogId": normalize_campaign_id(catalog_id, "catalogId"),
        "joinCode": normalize_join_code(join_code),
        "isActive": bool(is_active),
        "version": 1,
        "createdAt": normalize_required_text(now_iso, "nowIso", 40),
        "updatedAt": normalize_required_text(now_iso, "nowIso", 40),
        "createdByAccountId": normalize_campaign_id(created_by_account_id, "createdByAccountId"),
        "updatedByAccountId": normalize_campaign_id(created_by_account_id, "createdByAccountId"),
    }


def build_join_code_pointer_item(*, join_code: Any, unit_campaign_id: Any, now_iso: Any) -> Dict[str, Any]:
    """The ``joinCode -> unitCampaignId`` pointer that makes a code resolvable.

    It carries no campaign data on purpose: the resolver reads the campaign
    itself consistently after this read, so a pointer can never serve a stale
    name, catalog, or active state.
    """
    code = normalize_join_code(join_code)
    campaign_id = normalize_campaign_id(unit_campaign_id, "unitCampaignId")
    return {
        "pk": join_code_pk(code),
        "sk": unit_campaign_pk(campaign_id),
        "unitCampaignId": campaign_id,
        "createdAt": normalize_required_text(now_iso, "nowIso", 40),
    }


def build_membership_item(
    *,
    unit_campaign_id: Any,
    unit_id: Any,
    campaign_id: Any,
    profile_id: Any,
    joined_by_account_id: Any,
    now_iso: Any,
    status: Any = MEMBERSHIP_STATUS_ACTIVE,
) -> Dict[str, Any]:
    """Build a new membership item (§5.6).

    ``unitId`` is denormalized so a read can confirm tenancy without a second
    lookup, and removal audit is simply absent until removal happens — a rejoin
    overwrites ``joinedAt``/``joinedByAccountId`` while the record's identity and
    immutable ``campaignId`` stay put.
    """
    return {
        "pk": unit_campaign_pk(normalize_campaign_id(unit_campaign_id, "unitCampaignId")),
        "sk": membership_sk(normalize_campaign_id(profile_id, "profileId")),
        "unitCampaignId": normalize_campaign_id(unit_campaign_id, "unitCampaignId"),
        "unitId": normalize_campaign_id(unit_id, "unitId"),
        "campaignId": normalize_campaign_id(campaign_id, "campaignId"),
        "profileId": normalize_campaign_id(profile_id, "profileId"),
        "status": normalize_membership_status(status),
        "joinedByAccountId": normalize_campaign_id(joined_by_account_id, "joinedByAccountId"),
        "joinedAt": normalize_required_text(now_iso, "nowIso", 40),
        "version": 1,
    }


def build_membership_guard_item(
    *,
    campaign_id: Any,
    profile_id: Any,
    active_unit_campaign_id: Optional[str],
    membership_version: Any,
    now_iso: Any,
) -> Dict[str, Any]:
    """Build a guard row.

    ``activeUnitCampaignId`` is written only when one is active: the attribute
    being absent is the removed/independent shape, so no read has to distinguish
    an absent attribute from a stored null.
    """
    version = (
        membership_version if isinstance(membership_version, int) and not isinstance(membership_version, bool) else 0
    )
    if version < 1:
        raise _invalid("membershipVersion", "must be a positive integer")
    item: Dict[str, Any] = {
        "pk": guard_key(normalize_campaign_id(campaign_id, "campaignId"))["pk"],
        "sk": MEMBERSHIP_GUARD_SK,
        "campaignId": normalize_campaign_id(campaign_id, "campaignId"),
        "profileId": normalize_campaign_id(profile_id, "profileId"),
        "membershipVersion": version,
        "updatedAt": normalize_required_text(now_iso, "nowIso", 40),
    }
    if active_unit_campaign_id is not None:
        item["activeUnitCampaignId"] = normalize_campaign_id(active_unit_campaign_id, "activeUnitCampaignId")
    return item


# --- Reads (consistent where a mutation conditions on the result) ----------------


def read_unit_campaign(unit_campaign_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of a Unit Campaign metadata row."""
    response = tables.unit_campaigns.get_item(Key=unit_campaign_metadata_key(unit_campaign_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def load_unit_campaign_or_not_found(unit_campaign_id: str) -> Dict[str, Any]:
    """Read a Unit Campaign, answering ``NOT_FOUND`` when it does not exist."""
    campaign = read_unit_campaign(unit_campaign_id)
    if campaign is None:
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    return campaign


def list_unit_campaigns(unit_id: str) -> List[Dict[str, Any]]:
    """A Unit's Unit Campaigns, newest first (``unitId-createdAt-index``)."""
    return list(
        query_all_items(
            tables.unit_campaigns,
            {
                "IndexName": "unitId-createdAt-index",
                "KeyConditionExpression": "unitId = :unit_id",
                "FilterExpression": "#sk = :metadata",
                "ExpressionAttributeNames": {"#sk": "sk"},
                "ExpressionAttributeValues": {":unit_id": unit_id, ":metadata": METADATA_SK},
                "ScanIndexForward": False,
            },
        )
    )


def find_unit_campaigns_using_catalog(catalog_id: str) -> List[Dict[str, Any]]:
    """Unit Campaigns referencing a catalog — the catalog-usage guard read (§6.2).

    Advisory by contract: it prevents soft-deleting a referenced catalog and is
    never an authorization or tenancy check.
    """
    return list(
        query_all_items(
            tables.unit_campaigns,
            {
                "IndexName": "catalogId-index",
                "KeyConditionExpression": "catalogId = :catalog_id",
                "FilterExpression": "#sk = :metadata",
                "ExpressionAttributeNames": {"#sk": "sk"},
                "ExpressionAttributeValues": {":catalog_id": catalog_id, ":metadata": METADATA_SK},
            },
        )
    )


def find_join_code_pointers(join_code: str) -> List[Dict[str, Any]]:
    """Every pointer for a code, from a consistent base-table read (§5.5).

    DynamoDB conditions are per-item, so a ``pk``-scoped uniqueness rule cannot be
    expressed as a conditional write: this read is what makes "one campaign per
    join code" enforceable, and the pointer's conditional insert below is what
    keeps the winning write single. A malformed code reads as no pointers rather
    than querying an impossible key.
    """
    if not is_valid_join_code(join_code):
        return []
    response = tables.unit_campaigns.query(
        KeyConditionExpression=Key("pk").eq(join_code_pk(join_code)),
        ConsistentRead=True,
    )
    return [dict(item) for item in response.get("Items", [])]


def join_code_taken(join_code: str, *, except_unit_campaign_id: Optional[str] = None) -> bool:
    """True when this join code already names a different Unit Campaign.

    The exception parameter exists for the code's owner: re-saving or re-issuing
    against the same campaign is not a collision with itself.
    """
    return any(
        str(pointer.get("unitCampaignId")) != except_unit_campaign_id for pointer in find_join_code_pointers(join_code)
    )


def resolve_join_code(join_code: str, *, require_active: bool = True) -> Optional[Dict[str, Any]]:
    """Resolve a join code to its campaign, or None when the code is unusable.

    Two consistent base-table reads, exactly as §5.5 specifies: the pointer first,
    then the campaign it names. A malformed code, an unknown code, a pointer whose
    campaign is gone, and (by default) an inactive campaign all answer ``None``
    identically, so the caller learns nothing about which case it hit. The pointer
    carries no campaign fields, so the second read is what makes the result
    current rather than a copy taken at creation time.
    """
    pointers = find_join_code_pointers(join_code)
    if not pointers:
        return None
    campaign = read_unit_campaign(str(pointers[0]["unitCampaignId"]))
    if campaign is None:
        return None
    if require_active and not campaign.get("isActive", False):
        return None
    return campaign


def read_membership(unit_campaign_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one Scout's membership on one Unit Campaign."""
    response = tables.unit_campaigns.get_item(Key=membership_key(unit_campaign_id, profile_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def list_memberships(unit_campaign_id: str, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """A Unit Campaign's roster; ``status`` narrows it to ACTIVE or REMOVED."""
    query_kwargs: Dict[str, Any] = {
        # The sort-key prefix sits in a KeyConditionExpression, matching how the
        # other roster reads in this codebase are written.
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": unit_campaign_pk(unit_campaign_id), ":prefix": f"{MEMBERSHIP_SK_PREFIX}#"},
    }
    if status is not None:
        query_kwargs["FilterExpression"] = "#status = :status"
        query_kwargs["ExpressionAttributeNames"] = {"#status": "status"}
        query_kwargs["ExpressionAttributeValues"][":status"] = normalize_membership_status(status)
    return list(query_all_items(tables.unit_campaigns, query_kwargs))


def list_memberships_for_campaign(campaign_id: str) -> List[Dict[str, Any]]:
    """Memberships of one Scout Campaign across Unit Campaigns (``campaignId-index``)."""
    return list(
        query_all_items(
            tables.unit_campaigns,
            {
                "IndexName": "campaignId-index",
                "KeyConditionExpression": "campaignId = :campaign_id",
                "ExpressionAttributeValues": {":campaign_id": campaign_id},
            },
        )
    )


def read_scout_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    """The existing-application Scout Campaign row behind a ``campaignId``.

    Read through ``campaignId-index``, which is eventually consistent — that is
    acceptable only because it answers "which Profile owns this Campaign", and
    every write that follows conditions on the base-row item existing
    (:func:`campaign_latest_link_action`). A deleted Campaign therefore cancels
    the join transaction whole rather than producing a membership with no owner.
    """
    rows = list(
        query_all_items(
            tables.campaigns,
            {
                "IndexName": "campaignId-index",
                "KeyConditionExpression": "campaignId = :campaign_id",
                "ExpressionAttributeValues": {":campaign_id": campaign_id},
            },
        )
    )
    return dict(rows[0]) if rows else None


def read_catalog(catalog_id: str) -> Optional[Dict[str, Any]]:
    """The existing-application catalog a Unit Campaign references (§5.5).

    Read consistently because a create validates usability against it: a
    recently deleted catalog must not slip through on a stale read.
    """
    response = tables.catalogs.get_item(Key={"catalogId": catalog_id}, ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def catalog_is_usable(catalog: Optional[Dict[str, Any]]) -> bool:
    """Whether a new campaign may point at this catalog: it exists, undeleted.

    A soft-deleted catalog stays readable for campaigns already using it — their
    printed materials and Order history keep their product names — but it cannot
    be chosen by a new campaign (§1.5.1).
    """
    return catalog is not None and not catalog.get("isDeleted")


def read_membership_guard(campaign_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of the authoritative active-join lock."""
    response = tables.unit_campaigns.get_item(Key=guard_key(campaign_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def guard_active_unit_campaign_id(guard: Optional[Dict[str, Any]]) -> Optional[str]:
    """The Unit Campaign a Scout Campaign is currently joined to, or None.

    The guard is the only source of this answer: the historical
    ``Campaign.unitCampaignId`` link is retained through removal and must never be
    read as current membership (§5.6).
    """
    if guard is None:
        return None
    active = guard.get("activeUnitCampaignId")
    return str(active) if active else None


# --- Update policy (§1.4.1) ------------------------------------------------------


def reject_immutable_campaign_changes(changes: Any) -> None:
    """Refuse any attempt to change an immutable Unit Campaign field.

    The join path, inventory, and Order origin all key on ``catalogId``; making
    the immutability a check rather than a convention is what stops a metadata
    update from quietly relocating a campaign's whole product identity.
    """
    if not isinstance(changes, dict):
        raise _invalid("changes", "must be an object of field names to values")
    offenders = sorted(IMMUTABLE_CAMPAIGN_FIELDS.intersection(changes))
    if offenders:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "These Unit Campaign fields cannot be changed: " + ", ".join(offenders),
        )


# --- Transaction actions ---------------------------------------------------------
#
# Each helper returns a ``WritePlan``-shaped pair, ``(action, body)``, with the
# body already in DynamoDB wire form, so a resolver composes them without
# re-deriving which operation a guard belongs to::
#
#     for action, body in ucm.create_campaign_actions(campaign, pointer):
#         plan.add(action, body)
#
# That keeps the 90-action budget (data model §8.10) measured against the plan
# DynamoDB will actually run, and it keeps every condition below the one place
# where it can be audited.

Action = tuple[str, Dict[str, Any]]

# The two conditional-insert/delete guards every pair below rides on. ``_ABSENT``
# is what makes a join-code collision, a duplicate membership, and a duplicate
# guard row fail instead of overwrite; ``_PRESENT`` is what makes a delete that
# would silently miss its row fail instead.
_ABSENT = "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"
_PRESENT = "attribute_exists(#pk) AND attribute_exists(#sk)"


def _put(item: Dict[str, Any], *, condition: str) -> Action:
    """A conditional Put carrying its key inside the item, in wire form."""
    return (
        "Put",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Item": {name: wire_value(value) for name, value in item.items()},
            "ConditionExpression": condition,
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def _delete(key: Dict[str, str], *, condition: str) -> Action:
    """A conditional Delete in wire form."""
    return (
        "Delete",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(key),
            "ConditionExpression": condition,
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def create_campaign_actions(campaign: Dict[str, Any], pointer: Dict[str, Any]) -> List[Action]:
    """Write the campaign row and its join-code pointer as one atomic pair (§5.5).

    Both inserts are conditional, so a retry of the same create cannot double the
    campaign or its pointer. Cross-campaign code collisions are caught by
    :func:`join_code_taken`, which is the read that :func:`create_campaign_actions`
    callers run before staging this pair (§5.5).
    """
    return [
        _put(campaign, condition=_ABSENT),
        _put(pointer, condition=_ABSENT),
    ]


def delete_campaign_actions(campaign: Dict[str, Any]) -> List[Action]:
    """Remove a campaign row and its join-code pointer as one atomic pair.

    A live pointer left behind would let ``unitCampaignJoinInfo`` resolve a code
    to a campaign that no longer exists.
    """
    return [
        _delete(unit_campaign_metadata_key(str(campaign["unitCampaignId"])), condition=_PRESENT),
        _delete(
            join_code_pointer_key(str(campaign["joinCode"]), str(campaign["unitCampaignId"])),
            condition=_PRESENT,
        ),
    ]


def put_membership_action(membership: Dict[str, Any]) -> Action:
    """Create a membership that does not exist yet.

    An existing record — including a REMOVED one — fails this condition, so a
    rejoin must go through :func:`reactivate_membership_action` and keep the
    record's immutable ``campaignId`` and participation history.
    """
    return _put(membership, condition=_ABSENT)


def reactivate_membership_action(membership: Dict[str, Any], *, expected_version: int) -> Action:
    """Reactivate the same ``(unitCampaignId, profileId)`` record (§5.6).

    The version guard and the REMOVED-status guard ride in the condition, and the
    removal audit is REMOVEd rather than nulled. A rejoin that lost a race to
    another join sees the newer version and is cancelled whole, instead of
    writing a second participation history over the first or resurrecting a row
    that is still ACTIVE.
    """
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(membership_key(str(membership["unitCampaignId"]), str(membership["profileId"]))),
            "UpdateExpression": (
                "SET #status = :status, #joinedAt = :joinedAt, #joinedBy = :joinedBy, "
                "#version = #version + :one REMOVE #removedAt, #removedBy"
            ),
            "ExpressionAttributeNames": {
                "#status": "status",
                "#joinedAt": "joinedAt",
                "#joinedBy": "joinedByAccountId",
                "#version": "version",
                "#removedAt": "removedAt",
                "#removedBy": "removedByAccountId",
            },
            "ExpressionAttributeValues": {
                ":status": wire_value(MEMBERSHIP_STATUS_ACTIVE),
                ":joinedAt": wire_value(membership["joinedAt"]),
                ":joinedBy": wire_value(membership["joinedByAccountId"]),
                ":version": wire_value(expected_version),
                ":one": wire_value(1),
                ":removed": wire_value(MEMBERSHIP_STATUS_REMOVED),
            },
            "ConditionExpression": "#version = :version AND #status = :removed",
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def remove_membership_action(
    *, unit_campaign_id: str, profile_id: str, expected_version: int, removed_by_account_id: str, now_iso: str
) -> Action:
    """Set REMOVED plus removal audit; nothing is deleted (§5.6).

    Signups, work, allocations, credit, custody, and Orders keep pointing at this
    record, which is why removal is a status transition. Requiring ACTIVE in the
    condition also makes a second removal a conflict instead of a no-op that
    quietly bumps the version.
    """
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(membership_key(unit_campaign_id, profile_id)),
            "UpdateExpression": (
                "SET #status = :removed, #removedAt = :removedAt, #removedBy = :removedBy, #version = #version + :one"
            ),
            "ExpressionAttributeNames": {
                "#status": "status",
                "#removedAt": "removedAt",
                "#removedBy": "removedByAccountId",
                "#version": "version",
            },
            "ExpressionAttributeValues": {
                ":removed": wire_value(MEMBERSHIP_STATUS_REMOVED),
                ":removedAt": wire_value(now_iso),
                ":removedBy": wire_value(removed_by_account_id),
                ":version": wire_value(expected_version),
                ":one": wire_value(1),
                ":active": wire_value(MEMBERSHIP_STATUS_ACTIVE),
            },
            "ConditionExpression": "#version = :version AND #status = :active",
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def guard_claim_action(
    *,
    campaign_id: str,
    profile_id: str,
    active_unit_campaign_id: str,
    expected_membership_version: Optional[int],
    now_iso: str,
) -> Action:
    """Claim the Scout Campaign's active-join slot for one Unit Campaign (§8.2).

    With no guard row, the insert is conditional on there being none, so two
    concurrent first joins cannot both create one. With a guard row, the update
    conditions on the version the caller read AND on the slot being free or
    already pointed at the same target: §8.2's "guard target null or same" rule
    as a DynamoDB condition rather than a pre-check, which is what makes it hold
    under concurrency.

    ``expected_membership_version`` is None only when the caller's consistent read
    found no guard row; that read and this write are the same pair of eyes on one
    key.
    """
    if expected_membership_version is None:
        item = build_membership_guard_item(
            campaign_id=campaign_id,
            profile_id=profile_id,
            active_unit_campaign_id=active_unit_campaign_id,
            membership_version=1,
            now_iso=now_iso,
        )
        return _put(item, condition=_ABSENT)
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(guard_key(campaign_id)),
            "UpdateExpression": (
                "SET #active = :active, #membershipVersion = #membershipVersion + :one, #updatedAt = :updatedAt"
            ),
            "ExpressionAttributeNames": {
                "#pk": "pk",
                "#active": "activeUnitCampaignId",
                "#membershipVersion": "membershipVersion",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":active": wire_value(active_unit_campaign_id),
                ":one": wire_value(1),
                ":updatedAt": wire_value(now_iso),
                ":version": wire_value(expected_membership_version),
            },
            "ConditionExpression": (
                "attribute_exists(#pk) AND #membershipVersion = :version "
                "AND (attribute_not_exists(#active) OR #active = :active)"
            ),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def guard_release_action(
    *, campaign_id: str, expected_membership_version: int, expected_unit_campaign_id: str, now_iso: str
) -> Action:
    """Free the active-join slot: clear the target, bump the version (§8.2).

    ``activeUnitCampaignId`` is REMOVEd rather than set to null, keeping "no
    active join" a single representable shape. Naming the expected target in the
    condition is what stops a removal from clearing a slot a newer join already
    took.
    """
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(guard_key(campaign_id)),
            "UpdateExpression": (
                "SET #membershipVersion = #membershipVersion + :one, #updatedAt = :updatedAt REMOVE #active"
            ),
            "ExpressionAttributeNames": {
                "#pk": "pk",
                "#active": "activeUnitCampaignId",
                "#membershipVersion": "membershipVersion",
                "#updatedAt": "updatedAt",
            },
            "ExpressionAttributeValues": {
                ":one": wire_value(1),
                ":updatedAt": wire_value(now_iso),
                ":version": wire_value(expected_membership_version),
                ":target": wire_value(expected_unit_campaign_id),
            },
            "ConditionExpression": "attribute_exists(#pk) AND #membershipVersion = :version AND #active = :target",
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def campaign_latest_link_action(*, profile_id: str, campaign_id: str, unit_id: str, unit_campaign_id: str) -> Action:
    """Point the existing Scout Campaign at the Unit Campaign it just joined.

    Written on the legacy ``campaigns`` table inside the same transaction as the
    membership and the guard (§8.2), so a Scout Campaign is never joined in one
    row and unjoined in the other. Removal never writes this pair again: the link
    is history, and only the guard says whether it is current (§5.6, API-FIX-05).
    """
    return (
        "Update",
        {
            "TableName": tables.campaigns.table_name,
            "Key": wire_key({"profileId": profile_id, "campaignId": campaign_id}),
            "UpdateExpression": "SET #unitId = :unitId, #unitCampaignId = :unitCampaignId",
            "ExpressionAttributeNames": {
                "#unitId": "unitId",
                "#unitCampaignId": "unitCampaignId",
                "#campaignId": "campaignId",
            },
            "ExpressionAttributeValues": {
                ":unitId": wire_value(unit_id),
                ":unitCampaignId": wire_value(unit_campaign_id),
            },
            "ConditionExpression": "attribute_exists(#campaignId)",
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )
