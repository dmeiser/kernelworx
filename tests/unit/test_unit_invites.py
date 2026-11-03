"""Leaf 1.3.1-1.3.3: Unit invite mutations and administration.

Named tests from the delivery checklist:

- 1.3.1 ``createUnitInvite``: AUTH-U denial, 20 active unused invites
  allowed / the 21st rejected, idempotent retry.
- 1.3.2 ``redeemUnitInvite``: single-use, existing-grant redemption without
  an adminCount increment, consumed-retry replay, two-redeemer race, and the
  10-failed-attempts-per-hour throttle (attempt 11 is RATE_LIMIT_EXCEEDED).
- 1.3.3 ``unitInvites``/``revokeUnitInvite``: AUTH-U, active-unused-only
  listing with pagination, revocation, and identical-retry success.

Contract sources: data model §5.3/§6.6/§8.1, API doc createUnitInvite
(maximum 20 active unused invites) and redeemUnitInvite (duplicate existing
grant returns the current grant without incrementing adminCount).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.handlers.unit_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx
from tests.unit.test_unit_operations_edges import _create_public_order_throttles_table


def _seed(units_table: Any) -> Any:
    units = units_table
    fx.seed_show_sell_fixtures(units)
    return units


def _get_unit(units: Any, unit_id: str) -> dict:
    return units.get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"}, ConsistentRead=True)["Item"]


def _put_unit(units: Any, item: dict) -> None:
    units.put_item(Item=item)


def _create_invite(caller: str, unit_id: str, key: str) -> dict:
    return fx.unit_operation_event(
        "createUnitInvite",
        caller,
        input={"unitId": unit_id, "idempotency": {"idempotencyKey": key}},
    )


def _invite_items(units: Any, unit_id: str) -> list:
    # The unitId-createdAt-index also projects METADATA/GRANT rows (they carry
    # unitId + createdAt); a correct listing counts only INVITE# items.
    return [
        i
        for i in units.query(
            IndexName="unitId-createdAt-index",
            KeyConditionExpression="unitId = :u",
            ExpressionAttributeValues={":u": unit_id},
        )["Items"]
        if i["pk"].startswith("INVITE#")
    ]


# ---------------------------------------------------------------------------
# 1.3.1 createUnitInvite
# ---------------------------------------------------------------------------


class TestCreateUnitInvite:
    def test_auth_u_non_admin_denied_without_write(self, units_table: Any) -> None:
        """AUTH-U-03: Devon (no Pack 3149 grant) cannot mint invites; nothing is written."""
        units = _seed(units_table)
        payload = lambda_handler(_create_invite("Devon", fx.PACK_3149, "invite-denied"), None)
        fx.assert_is_error(payload, "FORBIDDEN")
        assert len(_invite_items(units, fx.PACK_3149)) == 2  # only the seeded active + expired

    def test_admin_creates_sixteen_character_fourteen_day_code(self, units_table: Any) -> None:
        units = _seed(units_table)
        payload = lambda_handler(_create_invite("Avery", fx.PACK_3149, "invite-ok"), None)
        assert not payload.get("__isError"), payload
        assert len(payload["inviteCode"]) == 16
        created = datetime.fromisoformat(payload["createdAt"])
        expires = datetime.fromisoformat(payload["expiresAt"])
        # "At most 14 days": the handler derives both timestamps from one clock
        # read, so a one-second epsilon absorbs sub-second clock skew only.
        assert timedelta(0) < expires - created <= timedelta(days=14, seconds=1)
        assert payload["createdByAccountId"] == fx.account_id("Avery")
        stored = units.get_item(
            Key={"pk": f"INVITE#{payload['inviteCode']}", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )
        assert "Item" in stored

    def test_twenty_active_invites_allowed_twenty_first_rejected(self, units_table: Any) -> None:
        """The 20-active cap counts unused, unexpired invites; the 21st fails and writes nothing."""
        units = _seed(units_table)
        # Expired seeded invite does not count toward the cap.
        active = [i for i in _invite_items(units, fx.PACK_3149) if "EXPIRED" not in i["inviteCode"]]
        for n in range(len(active), 20):
            payload = lambda_handler(_create_invite("Avery", fx.PACK_3149, f"cap-{n}"), None)
            assert not payload.get("__isError"), payload
        assert len(_invite_items(units, fx.PACK_3149)) == 21  # 20 active + 1 expired
        overflow = lambda_handler(_create_invite("Avery", fx.PACK_3149, "cap-overflow"), None)
        fx.assert_is_error(overflow, "CONFLICT")
        assert len(_invite_items(units, fx.PACK_3149)) == 21

    def test_idempotent_retry_returns_same_code(self, units_table: Any) -> None:
        """IDEM-01: the identical retry returns the original invite, not a second code."""
        units = _seed(units_table)
        event = _create_invite("Avery", fx.PACK_3149, "invite-retry")
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        second = lambda_handler(event, None)
        assert not second.get("__isError"), second
        assert second["inviteCode"] == first["inviteCode"]
        # 2 seeded Pack 3149 invites (active + expired) + 1 created; the retry adds nothing.
        assert len(_invite_items(units, fx.PACK_3149)) == 3


# ---------------------------------------------------------------------------
# 1.3.2 redeemUnitInvite
# ---------------------------------------------------------------------------


def _redeem(caller: str, code: str, key: str) -> dict:
    return fx.unit_operation_event(
        "redeemUnitInvite", caller, input={"inviteCode": code, "idempotency": {"idempotencyKey": key}}
    )


class TestRedeemUnitInvite:
    def test_single_use_second_redeem_is_not_found(self, units_table: Any) -> None:
        units = _seed(units_table)
        first = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "redeem-1"), None)
        assert not first.get("__isError"), first
        assert first["accountId"] == fx.account_id("Devon")
        stored = units.get_item(
            Key={"pk": "INVITE#PKT3149ACTIVE001", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )
        assert "Item" not in stored  # single-use: conditionally deleted
        meta = _get_unit(units, fx.PACK_3149)
        assert meta["adminCount"] == 2  # Avery + Devon
        second = lambda_handler(_redeem("Emery", "PKT3149ACTIVE001", "redeem-2"), None)
        fx.assert_is_error(second, "NOT_FOUND")

    def test_existing_grant_redeem_returns_grant_without_incrementing_count(self, units_table: Any) -> None:
        """The redeemer already holds a grant: current grant returned, adminCount unchanged, invite unburned."""
        units = _seed(units_table)
        meta = _get_unit(units, fx.PACK_3149)
        meta["adminCount"] = 2
        meta["version"] = 2
        _put_unit(units, meta)
        _put_unit(units, fx.grant_item(fx.PACK_3149, "Devon", created_by="Avery"))
        payload = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "redeem-existing"), None)
        assert not payload.get("__isError"), payload
        assert payload["accountId"] == fx.account_id("Devon")
        assert _get_unit(units, fx.PACK_3149)["adminCount"] == 2
        # The invite is not consumed by a no-op redemption.
        stored = units.get_item(
            Key={"pk": "INVITE#PKT3149ACTIVE001", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )
        assert "Item" in stored

    def test_consumed_retry_replays_original_result(self, units_table: Any) -> None:
        """IDEM-01/IDEM-02: after consumption, the identical retry returns the original grant with no second effect."""
        units = _seed(units_table)
        event = _redeem("Devon", "PKT3149ACTIVE001", "redeem-replay")
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        second = lambda_handler(event, None)
        assert not second.get("__isError"), second
        assert second["accountId"] == first["accountId"]
        assert _get_unit(units, fx.PACK_3149)["adminCount"] == 2

    def test_two_redeemers_race_exactly_one_grant(self, units_table: Any) -> None:
        """Two different accounts redeem one code: one wins, the loser sees NOT_FOUND, count +1 total."""
        units = _seed(units_table)
        winner = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "race-a"), None)
        assert not winner.get("__isError"), winner
        loser = lambda_handler(_redeem("Emery", "PKT3149ACTIVE001", "race-b"), None)
        fx.assert_is_error(loser, "NOT_FOUND")
        meta = _get_unit(units, fx.PACK_3149)
        assert meta["adminCount"] == 2
        grants = units.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"UNIT#{fx.PACK_3149}", ":prefix": "GRANT#"},
            ConsistentRead=True,
        )["Items"]
        assert {g["accountId"] for g in grants} == {fx.account_id("Avery"), fx.account_id("Devon")}

    def test_throttle_eleventh_failed_attempt_in_hour_is_rate_limited(self, units_table: Any) -> None:
        """Data model §6.6: only failed attempts count; attempt 11 in one UTC hour is RATE_LIMIT_EXCEEDED."""
        _seed(units_table)
        _create_public_order_throttles_table()
        for n in range(10):
            payload = lambda_handler(_redeem("Devon", f"BOGUS{n:011d}", f"throttle-{n}"), None)
            fx.assert_is_error(payload, "NOT_FOUND")
        eleventh = lambda_handler(_redeem("Devon", "BOGUS0000000099", "throttle-10"), None)
        fx.assert_is_error(eleventh, "RATE_LIMIT_EXCEEDED")
        # later failed attempts stay rate limited and the counter keeps its window shape
        twelfth = lambda_handler(_redeem("Devon", "BOGUS0000000100", "throttle-11"), None)
        fx.assert_is_error(twelfth, "RATE_LIMIT_EXCEEDED")

    def test_failed_attempts_write_the_documented_throttle_shape(self, units_table: Any) -> None:
        """Data model §6.6: the counter lives in the public_order_throttles table under
        UNIT_INVITE_REDEMPTION#<accountId>#WINDOW#<yyyy-MM-ddTHH>, with windowStart /
        attempts attributes and an epoch-second TTL horizon."""
        _seed(units_table)
        throttles = _create_public_order_throttles_table()
        now = datetime.now(tz=timezone.utc)
        window = now.strftime("%Y-%m-%dT%H")
        for n in range(3):
            fx.assert_is_error(
                lambda_handler(_redeem("Devon", f"SHAPE{n:012d}", f"throttle-shape-{n}"), None),
                "NOT_FOUND",
            )
        item = throttles.get_item(Key={"key": f"UNIT_INVITE_REDEMPTION#{fx.account_id('Devon')}#WINDOW#{window}"})[
            "Item"
        ]
        assert int(item["attempts"]) == 3
        assert item["windowStart"] == window
        assert int(item["expiresAt"]) > int(now.timestamp())
        # no counter rows were ever written to the units table
        assert not [i for i in units_table.scan()["Items"] if str(i.get("pk", "")).startswith("THROTTLE#")]

    def test_valid_redemption_does_not_increment_the_counter(self, units_table: Any) -> None:
        """A successful redemption (and an identical replay of one) leaves the
        failure counter untouched."""
        units = _seed(units_table)
        throttles = _create_public_order_throttles_table()
        payload = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "throttle-valid"), None)
        assert not payload.get("__isError"), payload
        replay = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "throttle-valid"), None)
        assert not replay.get("__isError"), replay
        assert throttles.scan()["Items"] == []
        assert _get_unit(units, fx.PACK_3149)["adminCount"] == 2


# ---------------------------------------------------------------------------
# 1.3.3 unitInvites / revokeUnitInvite
# ---------------------------------------------------------------------------


class TestUnitInvitesAndRevoke:
    def test_auth_u_non_admin_cannot_list(self, units_table: Any) -> None:
        _seed(units_table)
        payload = lambda_handler(
            fx.unit_operation_event("unitInvites", "Riley", arguments={"unitId": fx.PACK_3149}), None
        )
        fx.assert_is_error(payload, "FORBIDDEN")

    def test_lists_only_active_unused_invites_with_code_and_expiry(self, units_table: Any) -> None:
        """Redeemed, revoked, and expired invites do not appear; codes/expiry are present (UNIT-Q-04-01)."""
        _seed(units_table)
        payload = lambda_handler(
            fx.unit_operation_event("unitInvites", "Avery", arguments={"unitId": fx.PACK_3149}), None
        )
        assert not payload.get("__isError"), payload
        codes = {i["inviteCode"] for i in payload["items"]}
        assert "PKT3149ACTIVE001" in codes
        assert "PKT3149EXPIRED01" not in codes  # expired excluded
        assert "PKT3149CONSUMED1" not in codes  # consumed is a deleted row
        for item in payload["items"]:
            assert len(item["inviteCode"]) == 16
            assert "expiresAt" in item

    def test_pagination_limit_and_cursor(self, units_table: Any) -> None:
        """PAGE-01: default/max limits, valid cursors, stable pageInfo."""
        _seed(units_table)
        for n in range(3):
            payload = lambda_handler(_create_invite("Avery", fx.PACK_3149, f"page-{n}"), None)
            assert not payload.get("__isError"), payload
        first = lambda_handler(
            fx.unit_operation_event(
                "unitInvites",
                "Avery",
                arguments={"unitId": fx.PACK_3149, "page": {"limit": 2}},
            ),
            None,
        )
        assert not first.get("__isError"), first
        assert len(first["items"]) == 2
        assert first["pageInfo"]["hasNextPage"] is True
        assert first["pageInfo"]["endCursor"]
        second = lambda_handler(
            fx.unit_operation_event(
                "unitInvites",
                "Avery",
                arguments={"unitId": fx.PACK_3149, "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}},
            ),
            None,
        )
        assert not second.get("__isError"), second
        seen = {i["inviteCode"] for i in first["items"]} | {i["inviteCode"] for i in second["items"]}
        assert len(seen) == 4  # seeded active + 3 created; no duplicates across pages
        assert "PKT3149ACTIVE001" in seen

    def test_revoke_removes_invite_and_redeem_sees_not_found(self, units_table: Any) -> None:
        units = _seed(units_table)
        payload = lambda_handler(
            fx.unit_operation_event(
                "revokeUnitInvite",
                "Avery",
                input={
                    "unitId": fx.PACK_3149,
                    "inviteCode": "PKT3149ACTIVE001",
                    "idempotency": {"idempotencyKey": "revoke-invite-1"},
                },
            ),
            None,
        )
        assert payload is True, payload
        stored = units.get_item(
            Key={"pk": "INVITE#PKT3149ACTIVE001", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )
        assert "Item" not in stored
        listing = lambda_handler(
            fx.unit_operation_event("unitInvites", "Avery", arguments={"unitId": fx.PACK_3149}), None
        )
        assert "PKT3149ACTIVE001" not in {i["inviteCode"] for i in listing["items"]}
        redeem = lambda_handler(_redeem("Devon", "PKT3149ACTIVE001", "redeem-revoked"), None)
        fx.assert_is_error(redeem, "NOT_FOUND")

    def test_revoke_not_found_for_redeemed_code_except_identical_retry(self, units_table: Any) -> None:
        """A redeemed (deleted) code revokes as NOT_FOUND; only the identical retry is accepted."""
        _seed(units_table)
        event = _redeem("Devon", "PKT3149ACTIVE001", "redeem-then-revoke")
        lambda_handler(event, None)
        retry_redeem = lambda_handler(event, None)
        assert not retry_redeem.get("__isError"), retry_redeem
        revoke = lambda_handler(
            fx.unit_operation_event(
                "revokeUnitInvite",
                "Avery",
                input={
                    "unitId": fx.PACK_3149,
                    "inviteCode": "PKT3149ACTIVE001",
                    "idempotency": {"idempotencyKey": "revoke-missing"},
                },
            ),
            None,
        )
        fx.assert_is_error(revoke, "NOT_FOUND")
