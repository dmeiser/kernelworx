"""Leaf 1.1.1 / 1.1.3 — Unit and UnitInvite persistence (checklist §1.1).

Covers the model tests the leaf names:

- identity retention (``unitId`` is generated, never derived from metadata);
- generated display names, and a caller-supplied name surviving verbatim;
- equal unit numbers in different cities (distinct ``metadataKey``, no
  number-only collision workaround — UNIT-M-01-03 at the persistence layer);
- invalid settings rejected with INVALID_INPUT;
- invite code shape, 14-day expiry, revoked/consumed/expired codes reading
  identically, and the ``expiresAtEpoch`` TTL mapping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from botocore.exceptions import ClientError

from src.utils.errors import AppError, ErrorCode
from src.utils.unit_models import (
    COUNCIL_NEED_BASES,
    DEFAULT_COUNCIL_NEED_BASIS,
    DEFAULT_SPLIT_METHOD,
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_TTL_DAYS,
    SPLIT_METHODS,
    build_grant_item,
    build_invite_item,
    build_unit_item,
    find_units_with_metadata,
    generated_display_name,
    grant_key,
    invite_is_active,
    invite_pk,
    is_valid_invite_code,
    list_active_invites,
    load_unit_or_not_found,
    new_invite_code,
    new_unit_id,
    normalize_enum,
    normalize_optional_text,
    normalize_required_text,
    normalize_timezone,
    normalize_unit_number,
    normalized_metadata_key,
    parse_timestamp,
    read_invite,
    read_unit,
    unit_metadata_key,
    unit_pk,
)

PACK_ID = "unit-pack-3149-aurora"
CREW_ID = "unit-crew-529-denver"
AVERY = "11111111-1111-4111-8111-111111111111"

CREATED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

# Codes drawn from the production alphabet, as production issues them (no I/O/0/1).
CODE_ACTIVE = INVITE_CODE_ALPHABET[:16]
CODE_UNKNOWN = INVITE_CODE_ALPHABET[16:]
CODE_FRESH = INVITE_CODE_ALPHABET[1:17]
CODE_STALE = INVITE_CODE_ALPHABET[2:18]
CODE_NEWEST = INVITE_CODE_ALPHABET[3:19]
CODE_OTHER_UNIT = INVITE_CODE_ALPHABET[4:20]
# Right length, digits from outside the alphabet, and one character too long.
CODE_WITH_DIGITS = f"{CODE_ACTIVE[:9]}01234567"
CODE_TOO_LONG = f"{CODE_ACTIVE}A"


def _unit_item(unit_id: str = PACK_ID, **overrides: Any) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "unit_id": unit_id,
        "unit_type": "Pack",
        "unit_number": 3149,
        "city": "Aurora",
        "state": "CO",
        "timezone_name": "America/Denver",
        "created_by_account_id": AVERY,
        "now_iso": CREATED_AT.isoformat(),
    }
    args.update(overrides)
    return build_unit_item(**args)


def _put(units_table: Any, item: Dict[str, Any]) -> None:
    units_table.put_item(Item=item)


# --- key layout (data model §6.1) ------------------------------------------------


def test_key_layout_matches_the_documented_shapes() -> None:
    """§6.1 physical keys: metadata, grant, and invite items are addressed by prefix."""
    assert unit_pk(PACK_ID) == f"UNIT#{PACK_ID}"
    assert unit_metadata_key(PACK_ID) == {"pk": f"UNIT#{PACK_ID}", "sk": "METADATA"}
    assert grant_key(PACK_ID, AVERY) == {"pk": f"UNIT#{PACK_ID}", "sk": f"GRANT#{AVERY}"}
    assert invite_pk(CODE_ACTIVE) == f"INVITE#{CODE_ACTIVE}"


# --- 1.1.1: Unit persistence -----------------------------------------------------


def test_unit_item_persists_every_required_field(units_table: Any) -> None:
    """A built Unit round-trips through DynamoDB with identity, settings, and audit."""
    item = _unit_item()
    _put(units_table, item)

    stored = read_unit(PACK_ID)
    assert stored is not None
    assert stored["unitId"] == PACK_ID
    assert stored["unitType"] == "Pack"
    assert stored["unitNumber"] == 3149
    assert stored["city"] == "Aurora"
    assert stored["state"] == "CO"
    assert stored["timezone"] == "America/Denver"
    assert stored["splitDefault"] == DEFAULT_SPLIT_METHOD
    assert stored["councilNeedBasis"] == DEFAULT_COUNCIL_NEED_BASIS
    assert stored["adminCount"] == 1
    assert stored["version"] == 1
    assert stored["createdAt"] == CREATED_AT.isoformat()
    assert stored["updatedAt"] == CREATED_AT.isoformat()
    assert stored["createdByAccountId"] == AVERY


def test_unit_identity_is_generated_and_never_derived_from_metadata(units_table: Any) -> None:
    """Two identical metadata submissions are two Units with distinct stable ids."""
    first_id, second_id = new_unit_id(), new_unit_id()
    assert first_id != second_id

    _put(units_table, _unit_item(first_id))
    _put(units_table, _unit_item(second_id))

    first, second = read_unit(first_id), read_unit(second_id)
    assert first is not None and second is not None
    # Same fingerprint, different identity: the id is not a metadata digest.
    assert first["metadataKey"] == second["metadataKey"]
    assert first["unitId"] == first_id
    assert second["unitId"] == second_id
    assert PACK_ID not in first_id and "3149" not in first_id


def test_generated_display_name_and_explicit_display_name(units_table: Any) -> None:
    """An omitted display name is generated from metadata; a supplied one is kept."""
    generated = _unit_item(CREW_ID, unit_type="Crew", unit_number=529, city="Denver")
    explicit = _unit_item(PACK_ID, display_name="Aurora Cub Scouts")
    _put(units_table, generated)
    _put(units_table, explicit)

    assert generated["displayName"] == generated_display_name("Crew", 529, "Denver", "CO")
    assert generated["displayName"] == "Crew 529 - Denver, CO"
    stored_explicit = read_unit(PACK_ID)
    assert stored_explicit is not None
    assert stored_explicit["displayName"] == "Aurora Cub Scouts"


def test_equal_unit_numbers_in_different_cities_are_distinct_metadata() -> None:
    """No number-only collision workaround: the city discriminates (UNIT-M-01-03)."""
    aurora = normalized_metadata_key("Pack", 3149, "Aurora", "CO")
    boulder = normalized_metadata_key("Pack", 3149, "Boulder", "CO")
    assert aurora != boulder
    assert aurora == "pack#3149#aurora#co"
    assert normalized_metadata_key("Pack", 3149, "Aurora", "co") == aurora


def test_duplicate_metadata_lookup_finds_the_matching_unit_only(units_table: Any) -> None:
    """The duplicate gate reads the metadataKey index, not the unit number."""
    _put(units_table, _unit_item(PACK_ID))
    _put(units_table, _unit_item(CREW_ID, unit_type="Crew", unit_number=529, city="Denver"))

    matches = find_units_with_metadata(normalized_metadata_key("Pack", 3149, "Aurora", "CO"))
    assert [match["unitId"] for match in matches] == [PACK_ID]
    # An equal number in another city is not a duplicate of Pack 3149.
    assert find_units_with_metadata(normalized_metadata_key("Pack", 3149, "Boulder", "CO")) == []


def test_metadata_key_never_grants_access_shape(units_table: Any) -> None:
    """The metadata index is advisory: it returns Units, never grants."""
    item = _unit_item()
    _put(units_table, item)
    _put(
        units_table,
        build_grant_item(
            unit_id=PACK_ID, account_id=AVERY, created_by_account_id=AVERY, now_iso=CREATED_AT.isoformat()
        ),
    )

    matches = find_units_with_metadata(item["metadataKey"])
    assert [match["sk"] for match in matches] == ["METADATA"]


# --- 1.1.1: invalid settings -----------------------------------------------------


@pytest.mark.parametrize("field", ["unit_type", "city", "state"])
def test_required_geography_fields_reject_blank_values(field: str) -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_required_text(None if field == "unit_type" else "   ", field)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


def test_text_fields_reject_oversize_values() -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_required_text("x" * 101, "unitType")
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT
    assert "100" in excinfo.value.message


def test_optional_text_treats_blank_as_absent() -> None:
    assert normalize_optional_text(None, "displayName") is None
    assert normalize_optional_text("   ", "displayName") is None
    assert normalize_optional_text(" Aurora Pack ", "displayName") == "Aurora Pack"
    with pytest.raises(AppError) as excinfo:
        normalize_optional_text(7, "displayName")
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT
    with pytest.raises(AppError) as oversize:
        normalize_optional_text("x" * 101, "displayName")
    assert oversize.value.error_code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("value", [None, "", 0, -4, "abc", "  "])
def test_unit_number_must_be_a_positive_integer(value: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_unit_number(value)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


def test_unit_number_accepts_a_numeric_string() -> None:
    assert normalize_unit_number("42") == 42


@pytest.mark.parametrize(
    "value", ["Mars/Olympus", "America", "denver", "America/Denver Extra", "a/b/c/d", "1America/Denver"]
)
def test_timezone_must_be_an_iana_name(value: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_timezone(value)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "value", ["America/Denver", "UTC", "Etc/GMT+5", "America/Argentina/Buenos_Aires", "Europe/London"]
)
def test_accepted_iana_timezones(value: Any) -> None:
    assert normalize_timezone(value) == value


@pytest.mark.parametrize("value", ["SPLIT", "equal", 5, ""])
def test_invalid_split_default_is_rejected(value: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_enum(value, "splitDefault", SPLIT_METHODS, DEFAULT_SPLIT_METHOD)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


def test_enum_defaults_apply_when_absent() -> None:
    assert normalize_enum(None, "splitDefault", SPLIT_METHODS, DEFAULT_SPLIT_METHOD) == "EQUAL"
    assert normalize_enum("TIME_WORKED", "splitDefault", SPLIT_METHODS, DEFAULT_SPLIT_METHOD) == "TIME_WORKED"
    assert normalize_enum(None, "councilNeedBasis", COUNCIL_NEED_BASES, DEFAULT_COUNCIL_NEED_BASIS) == "PHYSICAL_STOCK"
    assert (
        normalize_enum("AFTER_ASSIGNMENTS", "councilNeedBasis", COUNCIL_NEED_BASES, DEFAULT_COUNCIL_NEED_BASIS)
        == "AFTER_ASSIGNMENTS"
    )


def test_read_unit_absent_and_load_unit_errors(units_table: Any) -> None:
    assert read_unit("unit-does-not-exist") is None
    with pytest.raises(AppError) as excinfo:
        load_unit_or_not_found("unit-does-not-exist")
    assert excinfo.value.error_code == ErrorCode.NOT_FOUND
    _put(units_table, _unit_item())
    assert load_unit_or_not_found(PACK_ID)["unitId"] == PACK_ID


# --- 1.1.1: the builder is the validation seam -----------------------------------


def test_unit_builder_normalizes_text_and_number() -> None:
    """Whitespace is trimmed and a numeric-string unit number is coerced on write."""
    item = _unit_item(city="  Aurora  ", state=" co ", unit_number="3149", display_name="  Aurora Pack  ")
    assert item["city"] == "Aurora"
    assert item["state"] == "co"
    assert item["unitNumber"] == 3149
    assert item["displayName"] == "Aurora Pack"
    assert item["metadataKey"] == "pack#3149#aurora#co"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unit_id", ""),
        ("unit_type", "   "),
        ("city", None),
        ("state", ""),
        ("timezone_name", "Mars/Olympus"),
        ("created_by_account_id", ""),
        ("now_iso", ""),
    ],
)
def test_unit_builder_rejects_invalid_metadata(field: str, value: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        _unit_item(**{field: value})
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("field", ["unit_number", "split_default", "council_need_basis"])
def test_unit_builder_rejects_invalid_settings(field: str) -> None:
    invalid = {"unit_number": 0, "split_default": "SPLIT", "council_need_basis": "COUNCIL"}[field]
    with pytest.raises(AppError) as excinfo:
        _unit_item(**{field: invalid})
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(("field", "value"), [("admin_count", 0), ("version", 0), ("admin_count", True)])
def test_unit_builder_rejects_counts_below_one(field: str, value: Any) -> None:
    """adminCount >= 1 for the Unit's whole life (§5.1); version starts at 1."""
    with pytest.raises(AppError) as excinfo:
        _unit_item(**{field: value})
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


def test_grant_builder_rejects_a_missing_identity() -> None:
    with pytest.raises(AppError) as excinfo:
        build_grant_item(unit_id=PACK_ID, account_id="", created_by_account_id=AVERY, now_iso=CREATED_AT.isoformat())
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT
    with pytest.raises(AppError) as missing_creator:
        build_grant_item(unit_id=PACK_ID, account_id=AVERY, created_by_account_id=None, now_iso=CREATED_AT.isoformat())
    assert missing_creator.value.error_code == ErrorCode.INVALID_INPUT


def test_invite_builder_rejects_a_missing_identity() -> None:
    with pytest.raises(AppError) as excinfo:
        build_invite_item(invite_code=CODE_ACTIVE, unit_id="", created_by_account_id=AVERY, created_at=CREATED_AT)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


# --- 1.1.3: UnitInvite -----------------------------------------------------------


def test_invite_code_shape_and_alphabet() -> None:
    """16 characters from an unambiguous alphabet; codes do not repeat."""
    codes = {new_invite_code() for _ in range(25)}
    assert len(codes) == 25
    for code in codes:
        assert len(code) == INVITE_CODE_LENGTH
        assert all(character in INVITE_CODE_ALPHABET for character in code)
    for ambiguous in "IO01":
        assert ambiguous not in INVITE_CODE_ALPHABET


@pytest.mark.parametrize("value", ["SHORT", CODE_TOO_LONG, CODE_ACTIVE.lower(), CODE_WITH_DIGITS, None, 16])
def test_invite_code_shape_predicate(value: Any) -> None:
    assert is_valid_invite_code(value) is False
    assert read_invite(value) is None


def test_invite_is_active_at_or_after_expiry() -> None:
    """14-day window, enforced application-side, boundary reads as expired."""
    item = build_invite_item(
        invite_code=CODE_ACTIVE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    assert item["expiresAt"] == (CREATED_AT + timedelta(days=INVITE_TTL_DAYS)).isoformat()
    assert invite_is_active(item, now=CREATED_AT) is True
    assert invite_is_active(item, now=CREATED_AT + timedelta(days=INVITE_TTL_DAYS, seconds=1)) is False
    assert invite_is_active(item, now=CREATED_AT + timedelta(days=INVITE_TTL_DAYS)) is False


def test_invite_ttl_attribute_maps_to_the_expiry_instant() -> None:
    """``expiresAtEpoch`` is the same instant as ``expiresAt``, in epoch seconds."""
    item = build_invite_item(
        invite_code=CODE_ACTIVE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    assert item["expiresAtEpoch"] == int(datetime.fromisoformat(item["expiresAt"]).timestamp())
    assert item["expiresAtEpoch"] == int((CREATED_AT + timedelta(days=14)).timestamp())
    # The units table TTL attribute is the one DynamoDB is configured to collect.
    assert item["pk"].startswith("INVITE#") and item["sk"] == unit_pk(PACK_ID)


def test_build_invite_item_rejects_a_malformed_code() -> None:
    with pytest.raises(AppError) as excinfo:
        build_invite_item(invite_code="nope", unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT)
    assert excinfo.value.error_code == ErrorCode.INVALID_INPUT


def test_invite_reads_by_code_alone(units_table: Any) -> None:
    """Redemption knows only the credential: the invite is addressed by pk."""
    _put(
        units_table,
        build_invite_item(invite_code=CODE_ACTIVE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT),
    )
    found = read_invite(CODE_ACTIVE)
    assert found is not None
    assert found["unitId"] == PACK_ID
    assert found["inviteCode"] == CODE_ACTIVE
    assert read_invite(CODE_UNKNOWN) is None


def test_revoked_and_consumed_invites_read_identically(units_table: Any) -> None:
    """Deleting the row is how revocation and redemption both take an invite out."""
    item = build_invite_item(
        invite_code=CODE_ACTIVE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    _put(units_table, item)
    assert read_invite(CODE_ACTIVE) is not None

    units_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    revoked = read_invite(CODE_ACTIVE)
    consumed = read_invite(CODE_UNKNOWN)
    assert revoked is None and consumed is None


def test_expired_invite_is_unreadable_before_the_ttl_collects_it(units_table: Any) -> None:
    """A physically present but expired row is deniable; the TTL is only eventual."""
    stale = build_invite_item(
        invite_code=CODE_STALE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    _put(units_table, stale)
    raw = units_table.get_item(Key={"pk": stale["pk"], "sk": stale["sk"]})["Item"]
    assert raw["inviteCode"] == CODE_STALE
    assert invite_is_active(raw, now=CREATED_AT + timedelta(days=15)) is False


def test_malformed_expiry_reads_as_expired(units_table: Any) -> None:
    """A corrupt expiry must deny, never crash."""
    assert invite_is_active({"expiresAt": "not-a-time"}, now=CREATED_AT) is False
    assert invite_is_active({}, now=CREATED_AT) is False
    assert parse_timestamp("nope") is None
    assert parse_timestamp(None) is None
    # A naive stored timestamp is still comparable (assumed UTC).
    assert parse_timestamp("2026-11-01T12:00:00") == datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def test_active_invites_exclude_expired_units_and_other_row_types(units_table: Any) -> None:
    """The Unit's invite listing skips metadata/grant rows and expired invites."""
    _put(units_table, _unit_item())
    _put(
        units_table,
        build_grant_item(
            unit_id=PACK_ID, account_id=AVERY, created_by_account_id=AVERY, now_iso=CREATED_AT.isoformat()
        ),
    )
    fresh = build_invite_item(
        invite_code=CODE_FRESH, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    stale = build_invite_item(
        invite_code=CODE_STALE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT - timedelta(days=30)
    )
    other_unit = build_invite_item(
        invite_code=CODE_OTHER_UNIT, unit_id=CREW_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    for item in (fresh, stale, other_unit):
        _put(units_table, item)

    active = list_active_invites(PACK_ID, now=CREATED_AT + timedelta(days=1))
    assert [invite["inviteCode"] for invite in active] == [CODE_FRESH]
    # Newest first, so the listing is stable for the per-Unit active cap.
    newer = build_invite_item(
        invite_code=CODE_NEWEST,
        unit_id=PACK_ID,
        created_by_account_id=AVERY,
        created_at=CREATED_AT + timedelta(hours=2),
    )
    _put(units_table, newer)
    ordered = list_active_invites(PACK_ID, now=CREATED_AT + timedelta(days=1))
    assert [invite["inviteCode"] for invite in ordered] == [CODE_NEWEST, CODE_FRESH]


def test_invite_key_is_unique_per_code(units_table: Any) -> None:
    """A second invite may never overwrite an existing code's row."""
    item = build_invite_item(
        invite_code=CODE_ACTIVE, unit_id=PACK_ID, created_by_account_id=AVERY, created_at=CREATED_AT
    )
    _put(units_table, item)
    with pytest.raises(ClientError) as excinfo:
        units_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#pk)",
            ExpressionAttributeNames={"#pk": "pk"},
        )
    assert excinfo.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
