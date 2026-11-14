"""Leaf 1.3 — Unit invite and administration resolvers.

Driven through the ``unit_operations`` entrypoint with the Stage 1 fixture event
builder. Covers the API contract (§3.4) and the e2e descriptions this leaf
answers to:

- ``createUnitInvite`` — 16-character single-use code, 14-day expiry, the
  20/21 active-invite boundary, admin-only, idempotent replay, and no marker
  behind a rejected attempt.
- ``redeemUnitInvite`` — ``UNIT-M-05-01`` … ``UNIT-M-05-04`` plus the §6.6
  per-Account UTC-hour counter on the existing throttle table.
- ``unitInvites`` / ``revokeUnitInvite`` — active-unused listing with codes,
  revoke-only-unused, ``NOT_FOUND`` for consumed codes except an identical retry.
- ``myUnits`` / ``unit`` / ``unitAdmins`` — tenant-bound reads, roster join, and
  the shared opaque cursor bound to the issuing scope (impact map §3.4).

The §6.6 counter lives on ``kernelworx-public-order-throttles-ue1-dev``, which is
deliberately outside the 10-table fixture set, so this module creates it for
every test: any failed redemption attempt writes the counter.

Error assertions target ``errorCode`` and, where the client must branch, the
message text — ``utils.handlers`` forwards only ``errorCode``/``message`` across
the Lambda boundary today, so the ``AppError.details`` subcodes this module sets
(``INVITE_LIMIT_REACHED``, ``INVITE_REDEMPTION_THROTTLE``) are asserted at the
AppSync layer, with the JS resolver that forwards them.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
import pytest

from src.handlers.unit_operations import (
    CREATE_INVITE_FIELD,
    INVITE_FAILURES_PER_HOUR,
    MAX_ACTIVE_UNIT_INVITES,
    MY_UNITS_FIELD,
    REDEEM_INVITE_FIELD,
    REVOKE_GRANT_FIELD,
    REVOKE_INVITE_FIELD,
    UNIT_ADMINS_FIELD,
    UNIT_FIELD,
    UNIT_INVITES_FIELD,
    handle_unit_operation,
)
from src.utils import unit_models
from src.utils.errors import ErrorCode
from tests.unit.show_sell_fixtures import (
    account_id,
    assert_is_error,
    grant_item,
    invite_item,
    unit_item,
    unit_operation_event,
)
from tests.unit.table_schemas import create_public_order_throttles_table_schema

AVERY = account_id("Avery")
BLAKE = account_id("Blake")
CASEY = "0a1b2c3d-0001-4a2b-8d10-000000000001"
MORGAN = "0a1b2c3d-0002-4a2b-8d10-000000000002"
STRANGER = "0a1b2c3d-0003-4a2b-8d10-000000000003"

PACK_ID = "unit-pack-3149-aurora"
CREW_ID = "unit-crew-529-denver"

# Invite codes are cut from the real alphabet so the fixtures cannot drift into
# an unusable shape (ambiguous characters are excluded by design, §5.3).
_ALPHABET = unit_models.INVITE_CODE_ALPHABET
CODE_A = _ALPHABET[0:16]
CODE_B = _ALPHABET[5:21]
CODE_C = _ALPHABET[9:25]
CODE_D = _ALPHABET[13:29]
CODE_NOT_ISSUED = _ALPHABET[-1] * 16


@pytest.fixture(autouse=True)
def throttles_table(dynamodb_table: Any) -> Any:
    """The existing throttle table (§6.6), created for every test in this module.

    Every failed redemption attempt writes the counter, so the table has to exist
    even in tests that only assert ``NOT_FOUND``. TTL is configured by a separate
    call, exactly as the shared fixture set does it.
    """
    client = boto3.client("dynamodb", region_name="us-east-1")
    schema = create_public_order_throttles_table_schema()
    ttl = schema.pop("TimeToLiveSpecification")
    client.create_table(**schema)
    client.update_time_to_live(TableName=schema["TableName"], TimeToLiveSpecification=ttl)
    return boto3.resource("dynamodb", region_name="us-east-1").Table(schema["TableName"])


@pytest.fixture
def accounts_table(dynamodb_table: Any) -> Any:
    """The accounts table, for the roster's email/name join."""
    return boto3.resource("dynamodb", region_name="us-east-1").Table("kernelworx-accounts-ue1-dev")


def _seed_unit(units_table: Any, unit_id: str, *, admins: List[str], city: str = "Aurora") -> None:
    units_table.put_item(Item=unit_item(unit_id, "Pack", 3149, city, "CO", created_by="Avery", admin_count=len(admins)))
    for admin in admins:
        units_table.put_item(Item=grant_item(unit_id, admin, created_by="Avery"))


def _seed_invite(
    units_table: Any,
    code: str,
    unit_id: str,
    *,
    created_by: str = "Avery",
    expired: bool = False,
    order: int = 0,
) -> str:
    """Write an invite relative to the real clock, ordered by ``order``.

    Expiry is judged against ``datetime.now`` in the resolver, so the fixture
    stays honest without freezing time: active invites expire in the future,
    expired ones in the past. The ``unitId-createdAt-index`` sort key decides
    listing order, hence the per-invite ``order`` offset.
    """
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=1 if not expired else 15, minutes=order)
    expires = now + timedelta(days=13) if not expired else now - timedelta(days=1)
    item = invite_item(code, unit_id, created_by, created_at=created, expires_at=expires)
    units_table.put_item(Item=item)
    return str(item["pk"])


def _call(field: str, caller: Optional[str], **kwargs: Any) -> Any:
    return handle_unit_operation(unit_operation_event(field, caller, **kwargs), None)


def _mutation_input(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"idempotency": {"idempotencyKey": overrides.pop("key", "invite-1")}}
    payload.update(overrides)
    return payload


def _invite_call(field: str, caller: Optional[str], *, unit_id: str = PACK_ID, **overrides: Any) -> Any:
    return _call(field, caller, input=_mutation_input(unitId=unit_id, **overrides))


def _redeem(caller: Optional[str], code: Any, key: str) -> Any:
    return _call(REDEEM_INVITE_FIELD, caller, input={"inviteCode": code, "idempotency": {"idempotencyKey": key}})


def _rows(units_table: Any) -> List[Dict[str, Any]]:
    return list(units_table.scan()["Items"])


def _invite_pks(units_table: Any) -> List[str]:
    return sorted(str(row["pk"]) for row in _rows(units_table) if str(row["pk"]).startswith("INVITE#"))


def _marker_rows(units_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(units_table) if str(row["pk"]).startswith("IDEM#")]


def _grant_accounts(units_table: Any, unit_id: str) -> List[str]:
    return [
        str(row["accountId"])
        for row in _rows(units_table)
        if row["pk"] == f"UNIT#{unit_id}" and str(row["sk"]).startswith("GRANT#")
    ]


def _unit_row(units_table: Any, unit_id: str) -> Dict[str, Any]:
    return dict(units_table.get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"})["Item"])


# --- createUnitInvite (§1.3.1) ---------------------------------------------------


def test_created_invite_is_single_use_shaped_and_expires_in_fourteen_days(units_table: Any) -> None:
    """An admin-issued invite: 16 usable characters, 14-day expiry, creator recorded."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    invite = _invite_call(CREATE_INVITE_FIELD, AVERY)

    code = str(invite["inviteCode"])
    assert len(code) == 16
    assert not set(code) & set("IO01")
    assert invite["unitId"] == PACK_ID
    assert invite["createdByAccountId"] == AVERY
    created = datetime.fromisoformat(invite["createdAt"])
    assert datetime.fromisoformat(invite["expiresAt"]) - created == timedelta(days=14)
    assert "expiresAtEpoch" not in invite

    stored = [row for row in _rows(units_table) if str(row["pk"]).startswith("INVITE#")]
    assert len(stored) == 1
    assert stored[0]["pk"] == f"INVITE#{code}"
    assert int(stored[0]["expiresAtEpoch"]) == int(datetime.fromisoformat(invite["expiresAt"]).timestamp())


def test_only_current_admins_may_create_invites(units_table: Any) -> None:
    """AUTH-U: a stranger, a revoked admin, and an anonymous caller get nothing."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, BLAKE])
    units_table.delete_item(Key={"pk": f"UNIT#{PACK_ID}", "sk": f"GRANT#{BLAKE}"})

    assert_is_error(_invite_call(CREATE_INVITE_FIELD, BLAKE), ErrorCode.NOT_FOUND)
    assert_is_error(_invite_call(CREATE_INVITE_FIELD, STRANGER), ErrorCode.NOT_FOUND)
    assert_is_error(_invite_call(CREATE_INVITE_FIELD, None), ErrorCode.UNAUTHORIZED)
    assert _invite_pks(units_table) == []
    assert _marker_rows(units_table) == []


def test_twentieth_invite_is_accepted_and_the_twenty_first_conflicts(units_table: Any) -> None:
    """The ceiling counts active invites, and a rejection writes nothing."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    for index in range(MAX_ACTIVE_UNIT_INVITES):
        _invite_call(CREATE_INVITE_FIELD, AVERY, key=f"invite-{index}")
    assert len(_invite_pks(units_table)) == MAX_ACTIVE_UNIT_INVITES

    markers_before = len(_marker_rows(units_table))
    error = assert_is_error(_invite_call(CREATE_INVITE_FIELD, AVERY, key="invite-overflow"), ErrorCode.CONFLICT)
    assert str(MAX_ACTIVE_UNIT_INVITES) in error["message"]
    assert len(_invite_pks(units_table)) == MAX_ACTIVE_UNIT_INVITES
    # A rejected attempt stages no marker, so the caller's next call is a real attempt.
    assert len(_marker_rows(units_table)) == markers_before


def test_expired_and_deleted_invites_do_not_consume_a_slot(units_table: Any) -> None:
    """Only redeemable invites count against the ceiling."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID, expired=True)
    for index in range(MAX_ACTIVE_UNIT_INVITES - 1):
        _invite_call(CREATE_INVITE_FIELD, AVERY, key=f"slot-{index}")
    assert len(_invite_pks(units_table)) == MAX_ACTIVE_UNIT_INVITES

    created = _invite_call(CREATE_INVITE_FIELD, AVERY, key="slot-final")
    assert created["inviteCode"]
    assert len(_invite_pks(units_table)) == MAX_ACTIVE_UNIT_INVITES + 1


def test_identical_invite_retry_replays_the_first_code(units_table: Any) -> None:
    """IDEM: the retry returns the same code and writes exactly one invite."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    first = _invite_call(CREATE_INVITE_FIELD, AVERY, key="retry-me")
    second = _invite_call(CREATE_INVITE_FIELD, AVERY, key="retry-me")

    assert second == first
    assert len(_invite_pks(units_table)) == 1


def test_reused_idempotency_key_with_different_content_is_rejected(units_table: Any) -> None:
    """One key cannot describe two requests: the second is refused, nothing writes.

    The marker key carries the resource scope, so a different Unit is a different
    request entirely; the reuse the guard catches is the same scope with different
    content.
    """
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    _seed_invite(units_table, CODE_B, PACK_ID)
    assert _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_A, key="shared-key") is True
    error = assert_is_error(
        _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_B, key="shared-key"), ErrorCode.INVALID_INPUT
    )
    assert "idempotencyKey" in error["message"]
    assert _invite_pks(units_table) == [f"INVITE#{CODE_B}"]


def test_invite_on_an_unknown_unit_is_not_found(units_table: Any) -> None:
    """A deleted Unit's address is indistinguishable from a mistyped one."""
    assert_is_error(_invite_call(CREATE_INVITE_FIELD, AVERY), ErrorCode.NOT_FOUND)
    assert _invite_pks(units_table) == []


# --- redeemUnitInvite (§1.3.2) ---------------------------------------------------


def test_redeem_grants_access_consumes_the_code_and_counts_the_admin(units_table: Any) -> None:
    """UNIT-M-05-01: Casey becomes a Unit Admin, once."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)

    grant = _redeem(CASEY, CODE_A, "r-1")

    assert grant["unitId"] == PACK_ID
    assert grant["accountId"] == CASEY
    assert grant["createdByAccountId"] == AVERY
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2
    assert _invite_pks(units_table) == []
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, CASEY])

    # Single use: the spent code is now indistinguishable from a wrong one.
    assert_is_error(_redeem(CASEY, CODE_A, "r-2"), ErrorCode.NOT_FOUND)
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, CASEY])


def test_unknown_expired_and_consumed_codes_answer_identically(units_table: Any) -> None:
    """UNIT-M-05-02: no oracle for which case the caller hit."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    expired_pk = _seed_invite(units_table, CODE_A, PACK_ID, expired=True)
    _seed_invite(units_table, CODE_B, PACK_ID)

    attempts = [_redeem(CASEY, CODE_NOT_ISSUED, "u-1"), _redeem(CASEY, CODE_A, "u-2")]
    assert _redeem(MORGAN, CODE_B, "u-3")["accountId"] == MORGAN
    attempts.append(_redeem(CASEY, CODE_B, "u-4"))

    for payload in attempts:
        error = assert_is_error(payload, ErrorCode.NOT_FOUND)
        assert error["message"] == attempts[0]["message"]
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2
    assert _invite_pks(units_table) == [expired_pk]
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, MORGAN])


def test_orphan_invite_is_not_found_and_grants_nothing(units_table: Any) -> None:
    """An invite whose Unit row is gone cannot mint a grant."""
    _seed_invite(units_table, CODE_A, PACK_ID)
    assert_is_error(_redeem(CASEY, CODE_A, "o-1"), ErrorCode.NOT_FOUND)
    assert _grant_accounts(units_table, PACK_ID) == []


def test_second_valid_invite_for_an_existing_admin_does_not_double_count(units_table: Any) -> None:
    """UNIT-M-05-03: the existing grant comes back and adminCount stays."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])
    _seed_invite(units_table, CODE_A, PACK_ID)

    grant = _redeem(CASEY, CODE_A, "dup-1")

    assert grant["accountId"] == CASEY
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2
    assert _invite_pks(units_table) == []
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, CASEY])


def test_two_redeemers_of_one_code_leave_one_coherent_result(units_table: Any) -> None:
    """The invite's delete condition is the single-use guard under a race."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)

    first = _redeem(CASEY, CODE_A, "race-1")
    second = _redeem(MORGAN, CODE_A, "race-2")

    assert first["accountId"] == CASEY
    assert_is_error(second, ErrorCode.NOT_FOUND)
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, CASEY])


def test_ten_failures_then_the_original_retry_still_returns_the_grant(units_table: Any) -> None:
    """UNIT-M-05-04: the window punishes guessing, never a completed retry."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    redeem = _redeem(CASEY, CODE_A, "keep-1")

    for index in range(INVITE_FAILURES_PER_HOUR):
        assert_is_error(_redeem(CASEY, CODE_B, f"f-{index}"), ErrorCode.NOT_FOUND)
    assert_is_error(_redeem(CASEY, CODE_C, "f-11"), ErrorCode.RATE_LIMIT_EXCEEDED)

    assert _redeem(CASEY, CODE_A, "keep-1") == redeem
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 2


def test_throttle_window_is_per_account_and_stamped_hourly(throttles_table: Any, units_table: Any) -> None:
    """One Account's guessing never locks another out; buckets are UTC hours."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)

    for index in range(INVITE_FAILURES_PER_HOUR + 1):
        expected = ErrorCode.NOT_FOUND if index < INVITE_FAILURES_PER_HOUR else ErrorCode.RATE_LIMIT_EXCEEDED
        assert_is_error(_redeem(CASEY, CODE_B, f"c-{index}"), expected)

    assert _redeem(MORGAN, CODE_A, "m-1")["accountId"] == MORGAN

    counters = throttles_table.scan()["Items"]
    assert len(counters) == 1
    key = str(counters[0]["key"])
    assert key.startswith(f"UNIT_INVITE_REDEMPTION#{CASEY}#WINDOW#")
    window_start = datetime.strptime(key.split("#WINDOW#")[1], "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    assert int(counters[0]["attempts"]) == INVITE_FAILURES_PER_HOUR + 1
    assert counters[0]["accountId"] == CASEY
    # The TTL outlives the window it counts, so the hour cannot be forgotten early.
    assert int(counters[0]["expiresAt"]) > int(window_start.timestamp()) + 3600


def test_a_new_attempt_in_a_later_window_is_unaffected(units_table: Any, monkeypatch: Any) -> None:
    """The counter is a rolling window, not a per-Account ban."""
    from src.handlers import unit_operations

    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    for index in range(INVITE_FAILURES_PER_HOUR + 1):
        expected = ErrorCode.NOT_FOUND if index < INVITE_FAILURES_PER_HOUR else ErrorCode.RATE_LIMIT_EXCEEDED
        assert_is_error(_redeem(CASEY, CODE_B, f"w-{index}"), expected)

    monkeypatch.setattr(unit_operations, "_current_redemption_window", lambda: ("2026-10-31T09", 1_793_379_600))
    assert _redeem(CASEY, CODE_A, "next-hour")["accountId"] == CASEY


def test_malformed_codes_answer_as_absent_and_are_counted(units_table: Any) -> None:
    """Length and alphabet mistakes disclose nothing, and they spend the window."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    for index, code in enumerate(("", "short", "ABCDEFGHIJ234567", "Abcd23456789EFGH", 42)):
        assert_is_error(_redeem(CASEY, code, f"m-{index}"), ErrorCode.NOT_FOUND)
    assert _grant_accounts(units_table, PACK_ID) == [AVERY]


def test_redeem_needs_a_signed_in_account_but_no_admin_role(units_table: Any) -> None:
    """Redemption is how a non-admin becomes an admin."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    assert_is_error(
        _call(REDEEM_INVITE_FIELD, None, input={"inviteCode": CODE_A, "idempotency": {"idempotencyKey": "a-1"}}),
        ErrorCode.UNAUTHORIZED,
    )
    assert _redeem(STRANGER, CODE_A, "a-2")["accountId"] == STRANGER


def test_missing_idempotency_key_is_rejected_before_any_write(units_table: Any) -> None:
    """Every Stage 1 mutation carries IdempotencyInput (SDL contract)."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    assert_is_error(_call(REDEEM_INVITE_FIELD, CASEY, input={"inviteCode": CODE_A}), ErrorCode.INVALID_INPUT)
    assert _invite_pks(units_table) == [f"INVITE#{CODE_A}"]
    assert _grant_accounts(units_table, PACK_ID) == [AVERY]


def test_a_throttled_attempt_counter_stays_retryable(units_table: Any, monkeypatch: Any) -> None:
    """A busy counter is never reported as a bad invite code."""
    from botocore.exceptions import ClientError

    from src.handlers import unit_operations

    class Busy:
        def update_item(self, **kwargs: Any) -> Dict[str, Any]:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem")

    class Broken:
        def update_item(self, **kwargs: Any) -> Dict[str, Any]:
            raise ClientError({"Error": {"Code": "ValidationException"}}, "UpdateItem")

    monkeypatch.setattr(unit_operations, "get_dynamodb_client", lambda: Busy())
    assert_is_error(_redeem(CASEY, CODE_B, "b-1"), ErrorCode.RESOURCE_BUSY)
    monkeypatch.setattr(unit_operations, "get_dynamodb_client", lambda: Broken())
    assert_is_error(_redeem(CASEY, CODE_C, "b-2"), ErrorCode.DATABASE_ERROR)
    assert _grant_accounts(units_table, PACK_ID) == []


def test_a_broken_replay_never_writes_a_second_result(units_table: Any, monkeypatch: Any) -> None:
    """A committed marker whose rows vanished is an internal fault, not a re-attempt."""
    from src.utils import unit_auth, unit_models

    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    created = _invite_call(CREATE_INVITE_FIELD, AVERY, key="replay-invite")
    redeemed = _redeem(CASEY, CODE_A, "replay-redeem")

    monkeypatch.setattr(unit_models, "read_invite", lambda invite_code: None)
    assert_is_error(_invite_call(CREATE_INVITE_FIELD, AVERY, key="replay-invite"), ErrorCode.INTERNAL_ERROR)
    monkeypatch.setattr(unit_auth, "read_grant", lambda unit_id, account_id: None)
    assert_is_error(_redeem(CASEY, CODE_A, "replay-redeem"), ErrorCode.INTERNAL_ERROR)

    # Neither broken replay minted a second invite or a second grant.
    assert created["inviteCode"] and redeemed["accountId"] == CASEY
    assert len(_marker_rows(units_table)) == 2
    assert _invite_pks(units_table) == [f"INVITE#{created['inviteCode']}"]
    assert sorted(_grant_accounts(units_table, PACK_ID)) == sorted([AVERY, CASEY])


def test_a_counter_that_cannot_be_read_fails_closed(monkeypatch: Any, units_table: Any) -> None:
    """An unreadable attempt count is never treated as zero attempts."""
    from src.handlers import unit_operations

    class Unreadable:
        def update_item(self, **kwargs: Any) -> Dict[str, Any]:
            return {"Attributes": {"attempts": {"N": "not-a-count"}}}

    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    monkeypatch.setattr(unit_operations, "get_dynamodb_client", lambda: Unreadable())
    assert_is_error(_redeem(CASEY, CODE_NOT_ISSUED, "unreadable"), ErrorCode.DATABASE_ERROR)
    assert _grant_accounts(units_table, PACK_ID) == [AVERY]


# --- unitInvites / revokeUnitInvite (§1.3.3) -------------------------------------


def test_listing_shows_active_unused_invites_with_their_codes(units_table: Any) -> None:
    """Admins can read and hand out their invites; expired rows stay hidden."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID, order=0)
    _seed_invite(units_table, CODE_B, PACK_ID, expired=True, order=1)

    connection = _call(UNIT_INVITES_FIELD, AVERY, arguments={"unitId": PACK_ID})

    assert [item["inviteCode"] for item in connection["items"]] == [CODE_A]
    assert connection["pageInfo"] == {"endCursor": None, "hasNextPage": False}
    assert connection["items"][0]["unitId"] == PACK_ID
    assert connection["items"][0]["createdByAccountId"] == AVERY
    assert "expiresAtEpoch" not in connection["items"][0]


def test_listing_and_revoking_are_admin_only_and_unit_scoped(units_table: Any) -> None:
    """Another Unit's admin sees neither the invite nor that one exists."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_unit(units_table, CREW_ID, admins=[BLAKE], city="Denver")
    _seed_invite(units_table, CODE_A, PACK_ID)

    assert_is_error(_call(UNIT_INVITES_FIELD, BLAKE, arguments={"unitId": PACK_ID}), ErrorCode.NOT_FOUND)
    assert_is_error(_call(UNIT_INVITES_FIELD, STRANGER, arguments={"unitId": PACK_ID}), ErrorCode.NOT_FOUND)
    assert_is_error(
        _invite_call(REVOKE_INVITE_FIELD, BLAKE, unit_id=CREW_ID, inviteCode=CODE_A, key="cross"), ErrorCode.NOT_FOUND
    )
    assert_is_error(_call(UNIT_INVITES_FIELD, AVERY, arguments={}), ErrorCode.INVALID_INPUT)
    assert _invite_pks(units_table) == [f"INVITE#{CODE_A}"]


def test_revoke_removes_the_invite_and_denies_later_redeem(units_table: Any) -> None:
    """A revoked code is indistinguishable from one that never existed."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)

    assert _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_A, key="revoke-1") is True
    assert _invite_pks(units_table) == []
    assert_is_error(_redeem(CASEY, CODE_A, "after-revoke"), ErrorCode.NOT_FOUND)


def test_revoked_invite_retry_is_idempotent_but_a_fresh_attempt_is_not_found(units_table: Any) -> None:
    """The marker answers the caller's own completed revocation, nothing else."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_invite(units_table, CODE_A, PACK_ID)
    assert _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_A, key="idem-revoke") is True

    assert _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_A, key="idem-revoke") is True
    assert_is_error(
        _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_A, key="idem-revoke-2"), ErrorCode.NOT_FOUND
    )
    assert_is_error(
        _invite_call(REVOKE_INVITE_FIELD, AVERY, inviteCode=CODE_NOT_ISSUED, key="never"), ErrorCode.NOT_FOUND
    )
    assert _invite_pks(units_table) == []


def test_invite_listing_pages_forward_and_refuses_foreign_cursors(units_table: Any) -> None:
    """A cursor is a position inside one scope, not a global offset."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    for order, code in enumerate((CODE_A, CODE_B, CODE_C)):
        _seed_invite(units_table, code, PACK_ID, order=order)

    first = _call(UNIT_INVITES_FIELD, AVERY, arguments={"unitId": PACK_ID, "page": {"limit": 2}})
    assert [item["inviteCode"] for item in first["items"]] == [CODE_A, CODE_B]
    assert first["pageInfo"]["hasNextPage"] is True
    second = _call(
        UNIT_INVITES_FIELD,
        AVERY,
        arguments={"unitId": PACK_ID, "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}},
    )
    assert [item["inviteCode"] for item in second["items"]] == [CODE_C]
    assert second["pageInfo"] == {"endCursor": None, "hasNextPage": False}

    # The same token against another Unit is refused, not repositioned inside it.
    _seed_unit(units_table, CREW_ID, admins=[AVERY], city="Denver")
    _seed_invite(units_table, CODE_D, CREW_ID)
    assert_is_error(
        _call(
            UNIT_INVITES_FIELD,
            AVERY,
            arguments={"unitId": CREW_ID, "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}},
        ),
        ErrorCode.INVALID_INPUT,
    )


# --- myUnits / unit / unitAdmins (§1.3.4) ----------------------------------------


def test_my_units_returns_only_granted_units(units_table: Any) -> None:
    """AUTH-U: a Unit the caller was never granted on is invisible."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_unit(units_table, CREW_ID, admins=[BLAKE], city="Denver")

    mine = _call(MY_UNITS_FIELD, AVERY, arguments={"page": {"limit": 10}})
    assert [item["unitId"] for item in mine["items"]] == [PACK_ID]
    assert _call(MY_UNITS_FIELD, STRANGER, arguments={})["items"] == []
    assert_is_error(_call(MY_UNITS_FIELD, None, arguments={}), ErrorCode.UNAUTHORIZED)


def test_my_units_pages_with_an_opaque_cursor(units_table: Any) -> None:
    """Every granted Unit is reachable, with no gap or repeat across pages."""
    seeded = ["unit-a-1", "unit-b-2", "unit-c-3"]
    for unit_id, city in zip(seeded, ("Aurora", "Boulder", "Denver"), strict=True):
        _seed_unit(units_table, unit_id, admins=[AVERY], city=city)

    first = _call(MY_UNITS_FIELD, AVERY, arguments={"page": {"limit": 2}})
    second = _call(MY_UNITS_FIELD, AVERY, arguments={"page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}})
    ids = [item["unitId"] for item in first["items"]] + [item["unitId"] for item in second["items"]]
    assert sorted(ids) == seeded
    assert first["pageInfo"]["hasNextPage"] is True and second["pageInfo"]["hasNextPage"] is False


def test_unit_query_returns_settings_and_authoritative_admin_count(units_table: Any) -> None:
    """The caller's own Unit, and nothing for anyone else."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, BLAKE])
    unit = _call(UNIT_FIELD, AVERY, arguments={"unitId": PACK_ID})
    assert unit["unitId"] == PACK_ID and unit["adminCount"] == 2
    assert unit["unitNumber"] == 3149 and unit["timezone"]

    assert_is_error(_call(UNIT_FIELD, BLAKE, arguments={"unitId": CREW_ID}), ErrorCode.NOT_FOUND)
    assert_is_error(_call(UNIT_FIELD, STRANGER, arguments={"unitId": PACK_ID}), ErrorCode.NOT_FOUND)
    assert_is_error(_call(UNIT_FIELD, AVERY, arguments={}), ErrorCode.INVALID_INPUT)
    assert_is_error(_call(UNIT_FIELD, AVERY, arguments={"unitId": " "}), ErrorCode.INVALID_INPUT)
    # ``unit`` takes no page argument; a stray one is not a reason to fail.
    assert _call(UNIT_FIELD, AVERY, arguments={"unitId": PACK_ID, "page": "nope"})["unitId"] == PACK_ID


def test_roster_joins_contacts_and_drops_a_revoked_admin_immediately(units_table: Any, accounts_table: Any) -> None:
    """A revoked admin is gone from the next read, not only from the count."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, BLAKE])
    accounts_table.put_item(
        Item={"accountId": f"ACCOUNT#{AVERY}", "email": "avery@example.com", "givenName": "Ada", "familyName": "Avery"}
    )
    accounts_table.put_item(Item={"accountId": f"ACCOUNT#{BLAKE}", "email": "blake@example.com"})

    roster = _call(UNIT_ADMINS_FIELD, AVERY, arguments={"unitId": PACK_ID})
    by_account = {item["accountId"]: item for item in roster["items"]}
    assert by_account[AVERY]["email"] == "avery@example.com" and by_account[AVERY]["name"] == "Ada Avery"
    assert by_account[BLAKE]["email"] == "blake@example.com" and by_account[BLAKE]["name"] is None

    _call(
        REVOKE_GRANT_FIELD,
        AVERY,
        input={
            "unitId": PACK_ID,
            "accountId": BLAKE,
            "version": {"expectedVersion": 1},
            "idempotency": {"idempotencyKey": "revoke-blake"},
        },
    )
    after = _call(UNIT_ADMINS_FIELD, AVERY, arguments={"unitId": PACK_ID})
    assert [item["accountId"] for item in after["items"]] == [AVERY]
    assert _unit_row(units_table, PACK_ID)["adminCount"] == 1


def test_roster_keeps_a_grant_whose_account_row_is_missing(units_table: Any, accounts_table: Any) -> None:
    """The grant makes someone an admin; a missing contact row does not."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    roster = _call(UNIT_ADMINS_FIELD, AVERY, arguments={"unitId": PACK_ID})
    assert roster["items"][0]["accountId"] == AVERY
    assert roster["items"][0]["email"] is None and roster["items"][0]["name"] is None
    assert accounts_table.scan()["Items"] == []


def test_unsupported_field_names_the_router_fault(units_table: Any) -> None:
    """A resolver wired to the wrong Lambda is a server fault, not user input."""
    assert_is_error(_call("unitInventory", AVERY, arguments={}), ErrorCode.INTERNAL_ERROR)


# --- shared page contract (impact map §3.4) ---------------------------------------


def _token(payload: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode()


@pytest.mark.parametrize(
    "page,code",
    [
        ({"limit": 0}, ErrorCode.INVALID_INPUT),
        ({"limit": 101}, ErrorCode.INVALID_INPUT),
        ({"limit": "plenty"}, ErrorCode.INVALID_INPUT),
        ({"limit": None}, None),
        ({"limit": "2"}, None),
        ({"cursor": 12}, ErrorCode.INVALID_INPUT),
        ({"cursor": "!" * 600}, ErrorCode.INVALID_INPUT),
        ({"cursor": "not-a-token"}, ErrorCode.INVALID_INPUT),
        ({"cursor": _token([1, 2])}, ErrorCode.INVALID_INPUT),
        ({"cursor": _token({"v": 99, "s": f"{MY_UNITS_FIELD}#{AVERY}", "o": 1})}, ErrorCode.INVALID_INPUT),
        ({"cursor": _token({"v": 1, "s": f"{MY_UNITS_FIELD}#{STRANGER}", "o": 1})}, ErrorCode.INVALID_INPUT),
        ({"cursor": _token({"v": 1, "s": f"{MY_UNITS_FIELD}#{AVERY}", "o": -1})}, ErrorCode.INVALID_INPUT),
        ({"cursor": _token({"v": 1, "s": f"{MY_UNITS_FIELD}#{AVERY}", "o": "1"})}, ErrorCode.INVALID_INPUT),
        ({"cursor": base64.urlsafe_b64encode(b"\xff\xfe").decode()}, ErrorCode.INVALID_INPUT),
        ("not-an-object", ErrorCode.INVALID_INPUT),
    ],
)
def test_page_input_is_validated_before_any_read(units_table: Any, page: Any, code: Optional[str]) -> None:
    """Limits, cursors, and token integrity fail as input errors, never as data."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    payload = _call(MY_UNITS_FIELD, AVERY, arguments={"page": page})
    if code is None:
        assert payload["items"]
    else:
        assert_is_error(payload, code)


def test_default_page_limit_is_fifty(units_table: Any) -> None:
    """A caller who asks for nothing gets the documented default, not everything."""
    seeded = [f"unit-many-{index}" for index in range(51)]
    for index, unit_id in enumerate(seeded):
        _seed_unit(units_table, unit_id, admins=[AVERY], city=f"City {index}")

    page = _call(MY_UNITS_FIELD, AVERY, arguments={})
    assert len(page["items"]) == 50
    assert page["pageInfo"]["hasNextPage"] is True
    rest = _call(MY_UNITS_FIELD, AVERY, arguments={"page": {"cursor": page["pageInfo"]["endCursor"]}})
    seen = [item["unitId"] for item in page["items"]] + [item["unitId"] for item in rest["items"]]
    assert sorted(seen) == sorted(seeded)
    assert rest["pageInfo"]["endCursor"] is None
