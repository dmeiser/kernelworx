"""Show & Sell Stage 1 lane-safe personas and cross-lane fixtures (leaf 1.7.4).

Six concrete personas with cross-lane data, per the delivery checklist and the
data model (SHOW_AND_SELL_DATA_MODEL.md §5.1-5.3, §6.1):

- **Blake**  - removed admin: created Pack 3149, then lost the grant; the unit
  survives with Avery as its only admin (``adminCount == 1``).
- **Taylor** - non-owner with WRITE: holds a WRITE share on Devon's profile but
  owns no Unit access.
- **Riley**  - READ-only share on Avery's profile; sole Unit Admin of a
  different Unit (Troop 7150) with no access to Pack 3149.
- **Avery**  - multi-unit owner: Unit Admin of Pack 3149 (Aurora) and Crew 529
  (Denver); owns a SellerProfile and Scout Campaign.
- **Devon**  - campaign joiner: owns a Scout Campaign that batch B joins to a
  Unit Campaign; Taylor holds WRITE on Devon's profile.
- **Emery**  - independent: own profile/campaign, no shares, no Unit data.

Every item this module builds uses the physical key shapes from data model
§6.1 (``UNIT#<unitId> / METADATA``, ``UNIT#<unitId> / GRANT#<accountId>``,
``INVITE#<inviteCode> / UNIT#<unitId>``) and the existing application tables'
key shapes for profiles/campaigns/shares. FIX-AC-01..06
(``test_show_sell_fixtures.py``) consume these personas and prove the
cross-lane non-deletion guarantee: the test-only Unit cascade never touches
another lane's data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Persona identities (deterministic Cognito subs, emails, display names).
# ---------------------------------------------------------------------------

_ACCOUNTS: Dict[str, Dict[str, str]] = {
    "Blake": {
        "accountId": "22222222-2222-4222-8222-222222222222",
        "email": "blake@fixtures.kernelworx.test",
        "name": "Blake Fixture",
    },
    "Taylor": {
        "accountId": "33333333-3333-4333-8333-333333333333",
        "email": "taylor@fixtures.kernelworx.test",
        "name": "Taylor Fixture",
    },
    "Riley": {
        "accountId": "44444444-4444-4444-8444-444444444444",
        "email": "riley@fixtures.kernelworx.test",
        "name": "Riley Fixture",
    },
    "Avery": {
        "accountId": "11111111-1111-4111-8111-111111111111",
        "email": "avery@fixtures.kernelworx.test",
        "name": "Avery Fixture",
    },
    "Devon": {
        "accountId": "55555555-5555-4555-8555-555555555555",
        "email": "devon@fixtures.kernelworx.test",
        "name": "Devon Fixture",
    },
    "Emery": {
        "accountId": "66666666-6666-4666-8666-666666666666",
        "email": "emery@fixtures.kernelworx.test",
        "name": "Emery Fixture",
    },
}

_ROLES = {
    "Blake": "removed_admin",
    "Taylor": "non_owner_write",
    "Riley": "read_only_share_on_avery",
    "Avery": "multi_unit_owner",
    "Devon": "campaign_joiner",
    "Emery": "independent",
}

# ---------------------------------------------------------------------------
# Unit / grant / invite identities (16-character invite codes, data model §5.3).
# ---------------------------------------------------------------------------

PACK_3149 = "unit-pack-3149-aurora"
CREW_529 = "unit-crew-529-denver"
TROOP_7150 = "unit-troop-7150-boulder"

UNITS: Dict[str, Dict[str, Any]] = {
    PACK_3149: {
        "unitId": PACK_3149,
        "unitType": "Pack",
        "unitNumber": 3149,
        "city": "Aurora",
        "state": "CO",
        "timezone": "America/Denver",
        "splitDefault": "EQUAL",
        "councilNeedBasis": "PHYSICAL_STOCK",
        "createdBy": "Blake",  # Blake created it, then was removed as admin.
        "admins": ["Avery"],  # Blake's GRANT# row is deliberately absent.
        "removedAdmins": ["Blake"],
    },
    CREW_529: {
        "unitId": CREW_529,
        "unitType": "Crew",
        "unitNumber": 529,
        "city": "Denver",
        "state": "CO",
        "timezone": "America/Denver",
        "splitDefault": "TIME_WORKED",
        "councilNeedBasis": "AFTER_ASSIGNMENTS",
        "createdBy": "Avery",
        "admins": ["Avery"],
        "removedAdmins": [],
    },
    TROOP_7150: {
        "unitId": TROOP_7150,
        "unitType": "Troop",
        "unitNumber": 7150,
        "city": "Boulder",
        "state": "CO",
        "timezone": "America/Denver",
        "splitDefault": "EQUAL",
        "councilNeedBasis": "PHYSICAL_STOCK",
        "createdBy": "Riley",
        "admins": ["Riley"],
        "removedAdmins": [],
    },
}

# Invite codes are exactly 16 characters (data model §5.3). Consumed/revoked
# codes are single-use deleted rows: they appear here only as fixture
# metadata, never as table items.
INVITES: Dict[str, Dict[str, Any]] = {
    "PKT3149ACTIVE001": {"unit": PACK_3149, "createdBy": "Avery", "state": "active"},
    "PKT3149EXPIRED01": {"unit": PACK_3149, "createdBy": "Avery", "state": "expired"},
    "PKT3149CONSUMED1": {"unit": PACK_3149, "createdBy": "Avery", "state": "consumed"},
    "TRP7150ACTIVE001": {"unit": TROOP_7150, "createdBy": "Riley", "state": "active"},
    "TRP7150EXPIRED01": {"unit": TROOP_7150, "createdBy": "Riley", "state": "expired"},
}

# Scout profiles/campaigns per persona (existing application tables).
PROFILES: Dict[str, Dict[str, Any]] = {
    name: {
        "profileId": f"PROFILE#prof-{name.lower()}-fixture",
        "campaignId": f"CAMPAIGN#camp-{name.lower()}-fixture",
        "sellerName": f"{name} Scout Fixture",
    }
    for name in ("Avery", "Blake", "Devon", "Emery", "Riley", "Taylor")
}

# Profile shares: Riley READ on Avery; Taylor non-owner WRITE on Devon.
SHARES: List[Dict[str, str]] = [
    {"owner": "Avery", "target": "Riley", "permissions": "READ"},
    {"owner": "Devon", "target": "Taylor", "permissions": "WRITE"},
]

# ---------------------------------------------------------------------------
# Unit Campaign fixtures (batch B, KW-SS-S1-B-CAMPAIGNS, data model §6.2):
# Unit Campaign metadata rows, join-code pointers, memberships, and the
# Scout-campaign guards. Join codes are exactly 16 characters (§6.6).
# ---------------------------------------------------------------------------

PACK_3149_FALL = "uc-pack-3149-fall-2026"
CREW_529_SPRING = "uc-crew-529-spring-2027"
PACK_3149_OLD = "uc-pack-3149-spring-2025"

UNIT_CAMPAIGNS: Dict[str, Dict[str, Any]] = {
    PACK_3149_FALL: {
        "unitId": PACK_3149,
        "campaignName": "Pack 3149 Fall Show & Sell",
        "campaignYear": 2026,
        "catalogId": "CATALOG#fixture-default",
        "joinCode": "JOINPK3149FALL01",
        "isActive": True,
        "createdBy": "Avery",
    },
    CREW_529_SPRING: {
        "unitId": CREW_529,
        "campaignName": "Crew 529 Spring Show & Sell",
        "campaignYear": 2027,
        "catalogId": "CATALOG#fixture-public",
        "joinCode": "JOINCRW529SPRNG1",
        "isActive": True,
        "createdBy": "Avery",
    },
    PACK_3149_OLD: {
        "unitId": PACK_3149,
        "campaignName": "Pack 3149 Spring 2025 Show & Sell",
        "campaignYear": 2025,
        "catalogId": "CATALOG#fixture-default",
        "joinCode": "JOINPK3149OLD001",
        "isActive": False,
        "createdBy": "Avery",
        # Distinct createdAt so newest-first listing order is deterministic
        # (T0 is defined below this table; the literal keeps module order safe).
        "createdAt": "2025-09-27T00:00:00+00:00",
    },
}

# Scout campaigns already carrying the joined-scope link. Emery's renders the
# removal case: the membership is REMOVED but the Campaign link is retained
# (removal never rewrites history, API-FIX-05).
JOINED_SCOUT_CAMPAIGNS: Dict[str, Any] = {
    "Devon": (PACK_3149, PACK_3149_FALL),
    "Riley": (CREW_529, CREW_529_SPRING),
    "Emery": (PACK_3149, PACK_3149_OLD),
}

# Memberships keyed ``(unitCampaignId, owner)``.
UNIT_CAMPAIGN_MEMBERSHIPS: Dict[Any, Dict[str, Any]] = {
    (PACK_3149_FALL, "Devon"): {"status": "ACTIVE", "joinedBy": "Devon"},
    (CREW_529_SPRING, "Riley"): {"status": "ACTIVE", "joinedBy": "Riley"},
    (PACK_3149_OLD, "Emery"): {
        "status": "REMOVED",
        "joinedBy": "Emery",
        "removedBy": "Avery",
        "version": 2,
    },
}

# Catalog fixtures behind the Unit Campaigns and the usability checks.
CATALOGS: Dict[str, Dict[str, Any]] = {
    "CATALOG#fixture-default": {
        "catalogId": "CATALOG#fixture-default",
        "catalogName": "Fixture Default Catalog",
        "owner": "Avery",
        "isPublic": False,
    },
    "CATALOG#fixture-public": {
        "catalogId": "CATALOG#fixture-public",
        "catalogName": "Fixture Public Catalog",
        "isPublic": True,
    },
    "CATALOG#fixture-admin": {
        "catalogId": "CATALOG#fixture-admin",
        "catalogName": "Fixture Admin Catalog",
        "catalogType": "ADMIN_MANAGED",
    },
    "CATALOG#fixture-deleted": {
        "catalogId": "CATALOG#fixture-deleted",
        "catalogName": "Fixture Deleted Catalog",
        "isDeleted": True,
    },
}

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
INVITE_TTL_DAYS = 14


# ---------------------------------------------------------------------------
# Public persona API (stable for batch B/C consumers).
# ---------------------------------------------------------------------------


def persona(name: str) -> Dict[str, Any]:
    """One persona's identity and role."""
    if name not in _ACCOUNTS:
        raise KeyError(f"unknown persona: {name}")
    return {**_ACCOUNTS[name], "name": name, "role": _ROLES[name]}


def persona_blake() -> Dict[str, Any]:
    return persona("Blake")


def persona_taylor() -> Dict[str, Any]:
    return persona("Taylor")


def persona_riley() -> Dict[str, Any]:
    return persona("Riley")


def persona_avery() -> Dict[str, Any]:
    return persona("Avery")


def persona_devon() -> Dict[str, Any]:
    return persona("Devon")


def persona_emery() -> Dict[str, Any]:
    return persona("Emery")


PERSONAS: Dict[str, Dict[str, Any]] = {name: persona(name) for name in _ACCOUNTS}


def all_personas() -> Dict[str, Dict[str, Any]]:
    return {name: dict(p) for name, p in PERSONAS.items()}


def account_id(name: str) -> str:
    """The Cognito sub / account id for one persona."""
    return _ACCOUNTS[name]["accountId"]


# ---------------------------------------------------------------------------
# Item builders (data model §5.1-5.3 / §6.1 key shapes).
# ---------------------------------------------------------------------------


def metadata_key(unit_type: str, unit_number: Any, city: str, state: str) -> str:
    """Normalized unitType#unitNumber#city#state fingerprint (lowercased)."""
    return f"{unit_type}#{unit_number}#{city.strip()}#{state.strip()}".lower()


def generated_display_name(unit_type: str, unit_number: Any, city: str, state: str) -> str:
    """Display name generated from metadata when the caller omits one."""
    return f"{unit_type} {unit_number} - {city.strip()}, {state.strip()}"


def unit_item(
    unit_id: str,
    unit_type: str,
    unit_number: Any,
    city: str,
    state: str,
    *,
    timezone_name: str = "America/Denver",
    split_default: str = "EQUAL",
    council_need_basis: str = "PHYSICAL_STOCK",
    display_name: Optional[str] = None,
    created_by: Optional[str] = None,
    admin_count: int = 1,
    version: int = 1,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Unit METADATA item at UNIT#<unitId> / METADATA."""
    now = created_at or T0.isoformat()
    return {
        "pk": f"UNIT#{unit_id}",
        "sk": "METADATA",
        "unitId": unit_id,
        "unitType": unit_type,
        "unitNumber": unit_number,
        "city": city.strip(),
        "state": state.strip(),
        "displayName": display_name or generated_display_name(unit_type, unit_number, city, state),
        "metadataKey": metadata_key(unit_type, unit_number, city, state),
        "timezone": timezone_name,
        "splitDefault": split_default,
        "councilNeedBasis": council_need_basis,
        "adminCount": admin_count,
        "version": version,
        "createdAt": now,
        "updatedAt": now,
        "createdByAccountId": created_by,
    }


def grant_item(
    unit_id: str, account: str, *, created_by: Optional[str] = None, created_at: Optional[str] = None
) -> Dict[str, Any]:
    """Build a UnitAccessGrant at UNIT#<unitId> / GRANT#<accountId>.

    ``account`` may be a persona name or a raw account id. ``role`` is always
    the only stored role, UNIT_ADMIN (data model §5.2).
    """
    acct = _ACCOUNTS.get(account, {}).get("accountId", account)
    creator = _ACCOUNTS.get(created_by, {}).get("accountId", created_by) if created_by else acct
    return {
        "pk": f"UNIT#{unit_id}",
        "sk": f"GRANT#{acct}",
        "unitId": unit_id,
        "accountId": acct,
        "role": "UNIT_ADMIN",
        "createdByAccountId": creator,
        "createdAt": created_at or T0.isoformat(),
    }


def invite_item(
    code: str,
    unit_id: str,
    created_by: str,
    *,
    created_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a UnitInvite at INVITE#<inviteCode> / UNIT#<unitId>.

    ``expiresAtEpoch`` is the numeric epoch-seconds DynamoDB TTL attribute
    (data model §5.3); it must agree with ``expiresAt``.
    """
    if len(code) != 16:
        raise ValueError(f"inviteCode must be exactly 16 characters, got {len(code)}")
    created = created_at or T0
    expires = expires_at or (created + timedelta(days=INVITE_TTL_DAYS))
    return {
        "pk": f"INVITE#{code}",
        "sk": f"UNIT#{unit_id}",
        "inviteCode": code,
        "unitId": unit_id,
        "createdByAccountId": account_id(created_by),
        "createdAt": created.isoformat(),
        "expiresAt": expires.isoformat(),
        "expiresAtEpoch": int(expires.timestamp()),
    }


def profile_item(owner: str, *, seller_name: Optional[str] = None) -> Dict[str, Any]:
    """A SellerProfile row in the profiles table (PK ownerAccountId, SK profileId)."""
    info = PROFILES[owner]
    now = T0.isoformat()
    return {
        "ownerAccountId": f"ACCOUNT#{account_id(owner)}",
        "profileId": info["profileId"],
        "sellerName": seller_name or info["sellerName"],
        "createdAt": now,
        "updatedAt": now,
    }


def campaign_item(
    owner: str,
    *,
    campaign_name: Optional[str] = None,
    unit_id: Optional[str] = None,
    unit_campaign_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A Scout Campaign row in the campaigns table (PK profileId, SK campaignId).

    ``unit_id``/``unit_campaign_id`` render the post-join joined-scope link the
    join transaction writes (data model §6.1); omit both for an independent
    campaign. Removal does not clear them, so a joined-history fixture keeps
    them set.
    """
    info = PROFILES[owner]
    now = T0.isoformat()
    item = {
        "profileId": info["profileId"],
        "campaignId": info["campaignId"],
        "campaignName": campaign_name or f"{owner}'s Fixture Campaign",
        "campaignYear": T0.year,
        "startDate": T0.date().isoformat(),
        "catalogId": "CATALOG#fixture-default",
        "createdAt": now,
    }
    if unit_id is not None and unit_campaign_id is not None:
        item["unitId"] = unit_id
        item["unitCampaignId"] = unit_campaign_id
    return item


def share_item(owner: str, target: str, permissions: str) -> Dict[str, Any]:
    """A profile share row in the shares table (PK profileId, SK ACCOUNT#<target>)."""
    return {
        "profileId": PROFILES[owner]["profileId"],
        "targetAccountId": f"ACCOUNT#{account_id(target)}",
        "permissions": [permissions],
    }


# ---------------------------------------------------------------------------
# Seeding and the test-only Unit cascade (FIX-AC cross-lane non-deletion).
# ---------------------------------------------------------------------------


def seed_show_sell_fixtures(
    units_table: Any,
    *,
    profiles_table: Any = None,
    campaigns_table: Any = None,
    shares_table: Any = None,
    unit_campaigns_table: Any = None,
    catalogs_table: Any = None,
) -> Dict[str, Any]:
    """Write every persona's fixture data and return a manifest.

    Units, grants, and invites land in the ``units`` table; profiles,
    campaigns, and shares land in their existing application tables when the
    caller passes them. The manifest records exactly what was written so
    FIX-AC tests can prove a cascade removes all and only one lane's items.
    """
    written_units: List[Dict[str, Any]] = []
    for spec in UNITS.values():
        admins = spec["admins"]
        item = unit_item(
            spec["unitId"],
            spec["unitType"],
            spec["unitNumber"],
            spec["city"],
            spec["state"],
            timezone_name=spec["timezone"],
            split_default=spec["splitDefault"],
            council_need_basis=spec["councilNeedBasis"],
            created_by=account_id(spec["createdBy"]),
            admin_count=len(admins),
        )
        units_table.put_item(Item=item)
        written_units.append(item)
        for admin in admins:
            grant = grant_item(spec["unitId"], admin, created_by=spec["createdBy"])
            units_table.put_item(Item=grant)
            written_units.append(grant)

    written_invites: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for code, spec in INVITES.items():
        if spec["state"] == "consumed":
            continue  # single-use consumed invites are deleted rows
        if spec["state"] == "expired":
            item = invite_item(
                code,
                spec["unit"],
                spec["createdBy"],
                created_at=now - timedelta(days=20),
                expires_at=now - timedelta(days=6),
            )
        else:
            item = invite_item(code, spec["unit"], spec["createdBy"], created_at=now)
        units_table.put_item(Item=item)
        written_invites.append(item)

    written_profiles: List[Dict[str, Any]] = []
    if profiles_table is not None:
        for owner in PROFILES:
            item = profile_item(owner)
            profiles_table.put_item(Item=item)
            written_profiles.append(item)

    written_campaigns: List[Dict[str, Any]] = []
    if campaigns_table is not None:
        for owner in PROFILES:
            joined = JOINED_SCOUT_CAMPAIGNS.get(owner)
            item = campaign_item(
                owner,
                unit_id=joined[0] if joined else None,
                unit_campaign_id=joined[1] if joined else None,
            )
            campaigns_table.put_item(Item=item)
            written_campaigns.append(item)

    written_shares: List[Dict[str, Any]] = []
    if shares_table is not None:
        for spec in SHARES:
            item = share_item(spec["owner"], spec["target"], spec["permissions"])
            shares_table.put_item(Item=item)
            written_shares.append(item)

    written_unit_campaigns: List[Dict[str, Any]] = []
    if unit_campaigns_table is not None:
        written_unit_campaigns = seed_unit_campaign_fixtures(unit_campaigns_table)

    written_catalogs: List[Dict[str, Any]] = []
    if catalogs_table is not None:
        for spec in CATALOGS.values():
            item = catalog_item(
                spec["catalogId"],
                spec["catalogName"],
                owner=spec.get("owner"),
                is_public=spec.get("isPublic", False),
                catalog_type=spec.get("catalogType"),
                is_deleted=spec.get("isDeleted", False),
            )
            catalogs_table.put_item(Item=item)
            written_catalogs.append(item)

    return {
        "units": written_units,
        "invites": written_invites,
        "profiles": written_profiles,
        "campaigns": written_campaigns,
        "shares": written_shares,
        "unit_campaigns": written_unit_campaigns,
        "catalogs": written_catalogs,
    }


def cascade_delete_unit(units_table: Any, unit_id: str) -> None:
    """Test-only Unit cascade: delete a Unit with its grants and invites together.

    The product's ``revokeUnitAccessGrant`` refuses to remove the final grant
    (``adminCount > 1`` precondition), so fixture cleanup can never go through
    ordinary revocation. This cascade removes the METADATA row, every
    ``GRANT#`` row, every invite for the Unit (via the ``unitId-createdAt``
    GSI), and any ``IDEM#`` marker scoped to the Unit in one pass. It is the
    FIX-AC cleanup primitive and must never touch another Unit's items.
    """
    units_table.delete_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"})
    grants = units_table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": f"UNIT#{unit_id}", ":prefix": "GRANT#"},
    )
    for item in grants.get("Items", []):
        units_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    invites = units_table.query(
        IndexName="unitId-createdAt-index",
        KeyConditionExpression="unitId = :u",
        ExpressionAttributeValues={":u": unit_id},
    )
    for item in invites.get("Items", []):
        units_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    # Markers are keyed IDEM#<actorId>#<operation>#<scope> / IDEM#<key> with the
    # unitId embedded as the scope segment, so a scan filtered on the pk is the
    # precise-enough test cleanup (fixture tables are small).
    markers = units_table.scan(
        FilterExpression="begins_with(pk, :prefix) AND contains(pk, :unit)",
        ExpressionAttributeValues={":prefix": "IDEM#", ":unit": unit_id},
    )
    for item in markers.get("Items", []):
        units_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})


def snapshot_units(units_table: Any) -> Dict[str, Dict[str, Any]]:
    """Full contents of the units table keyed by ``pk/sk`` for isolation assertions."""
    snapshot: Dict[str, Dict[str, Any]] = {}
    resp = units_table.scan()
    for item in resp.get("Items", []):
        snapshot[f"{item['pk']}|{item['sk']}"] = item
    return snapshot


# ---------------------------------------------------------------------------
# Unit Campaign builders and seeding (batch B, data model §6.2 key shapes).
# ---------------------------------------------------------------------------


def unit_campaign_item(
    unit_campaign_id: str,
    *,
    unit_id: str,
    campaign_name: str,
    campaign_year: int,
    catalog_id: str,
    join_code: str,
    is_active: bool = True,
    created_by: str,
    version: int = 1,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """A Unit Campaign at ``UNIT_CAMPAIGN#<id>`` / ``METADATA``."""
    now = created_at or T0.isoformat()
    return {
        "pk": f"UNIT_CAMPAIGN#{unit_campaign_id}",
        "sk": "METADATA",
        "unitCampaignId": unit_campaign_id,
        "unitId": unit_id,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "catalogId": catalog_id,
        "joinCode": join_code,
        "isActive": is_active,
        "version": version,
        "createdByAccountId": account_id(created_by),
        "updatedByAccountId": account_id(created_by),
        "createdAt": now,
        "updatedAt": now,
    }


def join_code_pointer_item(
    join_code: str, unit_campaign_id: str, *, created_at: Optional[str] = None
) -> Dict[str, Any]:
    """The join-code pointer at ``JOIN_CODE#<code>`` / ``UNIT_CAMPAIGN#<id>`` (§6.2)."""
    if len(join_code) != 16:
        raise ValueError(f"joinCode must be exactly 16 characters, got {len(join_code)}")
    return {
        "pk": f"JOIN_CODE#{join_code}",
        "sk": f"UNIT_CAMPAIGN#{unit_campaign_id}",
        "unitCampaignId": unit_campaign_id,
        "createdAt": created_at or T0.isoformat(),
    }


def unit_campaign_membership_item(
    unit_campaign_id: str,
    unit_id: str,
    campaign_id: str,
    profile_id: str,
    *,
    status: str = "ACTIVE",
    joined_by: str,
    joined_at: Optional[str] = None,
    removed_by: Optional[str] = None,
    removed_at: Optional[str] = None,
    version: int = 1,
) -> Dict[str, Any]:
    """A membership at ``UNIT_CAMPAIGN#<id>`` / ``MEMBERSHIP#<profileId>`` (§6.2)."""
    joined = joined_at or T0.isoformat()
    item: Dict[str, Any] = {
        "pk": f"UNIT_CAMPAIGN#{unit_campaign_id}",
        "sk": f"MEMBERSHIP#{profile_id}",
        "unitCampaignId": unit_campaign_id,
        "unitId": unit_id,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "status": status,
        "joinedByAccountId": account_id(joined_by),
        "joinedAt": joined,
        "version": version,
    }
    if removed_by is not None:
        item["removedByAccountId"] = account_id(removed_by)
        item["removedAt"] = removed_at or T0.isoformat()
    return item


def membership_guard_item(
    campaign_id: str,
    profile_id: str,
    *,
    active_unit_campaign_id: Optional[str] = None,
    membership_version: int = 1,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """The join guard at ``SCOUT_CAMPAIGN#<campaignId>`` / ``MEMBERSHIP_GUARD`` (§6.2).

    ``active_unit_campaign_id=None`` is the removed/independent shape: the
    attribute is absent (nullable), never a null value.
    """
    item: Dict[str, Any] = {
        "pk": f"SCOUT_CAMPAIGN#{campaign_id}",
        "sk": "MEMBERSHIP_GUARD",
        "campaignId": campaign_id,
        "profileId": profile_id,
        "membershipVersion": membership_version,
        "updatedAt": updated_at or T0.isoformat(),
    }
    if active_unit_campaign_id is not None:
        item["activeUnitCampaignId"] = active_unit_campaign_id
    return item


def unit_membership_item(account: str, unit_id: str, *, status: str = "ACTIVE") -> Dict[str, Any]:
    """A units-table membership at ``UNIT#<unitId>`` / ``MEMBERSHIP#<accountId>`` (§5.2).

    NOT part of ``seed_show_sell_fixtures``: batch A cascade tests assert the
    units table is empty afterwards, so batch B seeds these rows explicitly.
    """
    return {
        "pk": f"UNIT#{unit_id}",
        "sk": f"MEMBERSHIP#{account_id(account)}",
        "accountId": account_id(account),
        "unitId": unit_id,
        "status": status,
        "createdAt": T0.isoformat(),
    }


def seed_unit_memberships(units_table: Any) -> None:
    """Units-table memberships the batch B join tests rely on (see UNITS)."""
    for account, unit_id in (
        ("Devon", "unit-pack-3149-aurora"),
        ("Riley", "unit-pack-3149-aurora"),
        ("Emery", "unit-pack-3149-aurora"),
        ("Taylor", "unit-pack-3149-aurora"),
    ):
        units_table.put_item(Item=unit_membership_item(account, unit_id))


def catalog_item(
    catalog_id: str,
    catalog_name: str,
    *,
    owner: Optional[str] = None,
    is_public: bool = False,
    catalog_type: Optional[str] = None,
    is_deleted: bool = False,
    products: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A catalog row in the catalogs table (PK catalogId)."""
    item: Dict[str, Any] = {
        "catalogId": catalog_id,
        "catalogName": catalog_name,
        "isPublic": is_public,
        "createdAt": T0.isoformat(),
        "updatedAt": T0.isoformat(),
    }
    if owner is not None:
        item["ownerAccountId"] = account_id(owner)
    if catalog_type is not None:
        item["catalogType"] = catalog_type
    if is_deleted:
        item["isDeleted"] = True
    item["products"] = (
        products
        if products is not None
        else [
            {
                "productId": f"{catalog_id}#prod-1",
                "productName": f"{catalog_name} Product 1",
                "description": "Fixture product",
                # Decimal: boto3's serializer rejects float; AppSync serves
                # the N attribute as the GraphQL Float price.
                "price": Decimal("25.00"),
                "sortOrder": 1,
            }
        ]
    )
    return item


def seed_unit_campaign_fixtures(unit_campaigns_table: Any) -> List[Dict[str, Any]]:
    """Write the Unit Campaign rows, join-code pointers, memberships, and guards.

    The guard set is derived from the membership fixtures so the two can never
    drift: one guard per Scout campaign that has (or had) a membership, its
    ``membershipVersion`` mirroring the membership's version and its
    ``activeUnitCampaignId`` set only while a membership is ACTIVE.
    """
    written: List[Dict[str, Any]] = []
    for unit_campaign_id, spec in UNIT_CAMPAIGNS.items():
        item = unit_campaign_item(
            unit_campaign_id,
            unit_id=spec["unitId"],
            campaign_name=spec["campaignName"],
            campaign_year=spec["campaignYear"],
            catalog_id=spec["catalogId"],
            join_code=spec["joinCode"],
            is_active=spec["isActive"],
            created_by=spec["createdBy"],
            created_at=spec.get("createdAt"),
        )
        unit_campaigns_table.put_item(Item=item)
        written.append(item)
        pointer = join_code_pointer_item(spec["joinCode"], unit_campaign_id)
        unit_campaigns_table.put_item(Item=pointer)
        written.append(pointer)

    guards: Dict[str, Dict[str, Any]] = {}
    for (unit_campaign_id, owner), spec in UNIT_CAMPAIGN_MEMBERSHIPS.items():
        info = PROFILES[owner]
        membership = unit_campaign_membership_item(
            unit_campaign_id,
            UNIT_CAMPAIGNS[unit_campaign_id]["unitId"],
            info["campaignId"],
            info["profileId"],
            status=spec["status"],
            joined_by=spec["joinedBy"],
            removed_by=spec.get("removedBy"),
            version=spec.get("version", 1),
        )
        unit_campaigns_table.put_item(Item=membership)
        written.append(membership)
        guards[info["campaignId"]] = {
            "profileId": info["profileId"],
            "active": unit_campaign_id if spec["status"] == "ACTIVE" else None,
            "membershipVersion": membership["version"],
        }

    for campaign_id, guard in guards.items():
        item = membership_guard_item(
            campaign_id,
            guard["profileId"],
            active_unit_campaign_id=guard["active"],
            membership_version=guard["membershipVersion"],
        )
        unit_campaigns_table.put_item(Item=item)
        written.append(item)

    return written


def cascade_delete_unit_campaign(
    unit_campaigns_table: Any,
    unit_campaign_id: str,
    *,
    join_code: Optional[str] = None,
    campaign_ids: Optional[List[str]] = None,
) -> None:
    """Test-only Unit Campaign cascade: metadata, memberships, pointer, guards.

    Mirrors what the Stage 3 product cascade will own; fixture cleanup cannot
    go through the product's guarded removal path. Must never touch another
    Unit Campaign's items.
    """
    unit_campaigns_table.delete_item(Key={"pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", "sk": "METADATA"})
    memberships = unit_campaigns_table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", ":prefix": "MEMBERSHIP#"},
    )
    for item in memberships.get("Items", []):
        unit_campaigns_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    if join_code is not None:
        pointers = unit_campaigns_table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"JOIN_CODE#{join_code}"},
        )
        for item in pointers.get("Items", []):
            unit_campaigns_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    for campaign_id in campaign_ids or []:
        unit_campaigns_table.delete_item(Key={"pk": f"SCOUT_CAMPAIGN#{campaign_id}", "sk": "MEMBERSHIP_GUARD"})


def unit_campaign_operation_event(
    field: str,
    caller: Optional[str],
    *,
    input: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the AppSync event the ``unit_campaign_operations`` Lambda dispatches on.

    Same contract as :func:`unit_operation_event` for the batch B handler.
    """
    return unit_operation_event(field, caller, input=input, arguments=arguments)


# ---------------------------------------------------------------------------
# Handler-driving helpers for the batch A resolver tests.
# ---------------------------------------------------------------------------


def unit_operation_event(
    field: str,
    caller: Optional[str],
    *,
    input: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the AppSync event the ``unit_operations`` Lambda dispatches on.

    ``caller`` is a persona name or raw account id; ``None`` simulates an
    unauthenticated/API-key caller (``identity`` absent). Pass ``arguments``
    for query-style fields (``unit``, ``unitAdmins``) and ``input`` for
    mutation fields.
    """
    acct = _ACCOUNTS.get(caller, {}).get("accountId", caller) if caller else None
    if arguments is None:
        arguments = {"input": input} if input is not None else {}
    return {
        "arguments": arguments,
        "identity": {"sub": acct} if acct else None,
        "requestContext": {"requestId": "fixture-request"},
        "info": {"fieldName": field, "parentTypeName": "Mutation"},
    }


def assert_is_error(payload: Any, code: str) -> Dict[str, Any]:
    """Assert the #329 structured error payload carries ``code``; return it."""
    assert isinstance(payload, dict), f"expected error payload, got {payload!r}"
    assert payload.get("__isError") is True, f"expected __isError payload, got {payload!r}"
    assert payload.get("errorCode") == code, f"expected {code}, got {payload!r}"
    return payload
