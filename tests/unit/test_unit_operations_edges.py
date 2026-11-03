"""Edge-path contract tests for the ``unit_operations`` Lambda.

These tests exist to pin the validation, pagination, fault-fallback, and
garbage-input behavior of every public entry point on the 100%-coverage gate.
They complement the leaf-named suites (``test_unit_persistence.py`` etc.) by
driving branches those suites do not reach: defensive ``except`` fallbacks
(fault-injected via a wrapper table), cursor/limit clamping, odd expiry
formats, and unknown-field dispatch.

Authz assertions follow the codebase rule: a caller is a unit admin only when
the strongly consistent base-table ``GRANT#`` row exists.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict

import pytest
from botocore.exceptions import ClientError

from src.handlers import unit_operations as uop
from src.handlers.unit_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx

_INJECTED = ClientError(
    {"Error": {"Code": "InternalServerError", "Message": "injected fault"}},
    "injected",
)


class _FlakyTable:
    """Wrap the real units table; raise ``ClientError`` when the predicate matches.

    The predicate receives the DynamoDB operation name (``get_item``, ``query``,
    ``scan``, ``put_item``, ...) and the keyword arguments the handler used, so
    each test faults exactly one call shape without touching anything else.
    """

    def __init__(self, real: Any, predicate: Callable[[str, Dict[str, Any]], bool]) -> None:
        self._real = real
        self._predicate = predicate

    @property
    def name(self) -> str:
        return self._real.name

    def __getattr__(self, attr_name: str) -> Any:
        attr = getattr(self._real, attr_name)
        if not callable(attr):
            return attr

        def call(**kwargs: Any) -> Any:
            if self._predicate(attr_name, kwargs):
                raise _INJECTED
            return attr(**kwargs)

        return call


def _fault(units_table: Any, monkeypatch: pytest.MonkeyPatch, predicate: Callable[[str, Dict[str, Any]], bool]) -> None:
    monkeypatch.setattr(uop, "_units", lambda: _FlakyTable(units_table, predicate))


def _ok(payload: Any) -> Any:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"unexpected error payload {payload!r}"
    return payload


def _pk_startswith(prefix: str) -> Callable[[str, Dict[str, Any]], bool]:
    """Fault any op (get/put/delete) touching a row whose ``pk`` starts with ``prefix``."""

    def predicate(_op: str, kwargs: Dict[str, Any]) -> bool:
        row = kwargs.get("Key") or kwargs.get("Item") or {}
        return str(row.get("pk", "")).startswith(prefix)

    return predicate


def _create_input(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "unitType": "Ship",
        "unitNumber": 42,
        "city": "Portland",
        "state": "ME",
        "timezone": "America/New_York",
        "idempotency": {"idempotencyKey": f"edge-create-{datetime.now(timezone.utc).timestamp()}"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def seeded(units_table: Any) -> Dict[str, Any]:
    return fx.seed_show_sell_fixtures(units_table)


# ---------------------------------------------------------------------------
# create_unit edges
# ---------------------------------------------------------------------------


class TestCreateUnitEdges:
    def test_missing_caller_identity_unauthorized(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(fx.unit_operation_event("createUnit", None, input=_create_input()), None),
            "UNAUTHORIZED",
        )

    def test_timezone_utc_accepted(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=_create_input(timezone="UTC")), None)
        )
        assert payload["unit"]["timezone"] == "UTC"

    def test_non_string_city_treated_as_missing(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event("createUnit", "Emery", input=_create_input(city=None)),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_missing_idempotency_key_rejected(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=_create_input(idempotency=None)), None),
            "INVALID_INPUT",
        )

    def test_non_finite_decimal_unit_number_is_internal_error(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event("createUnit", "Emery", input=_create_input(unitNumber=Decimal("nan"))),
                None,
            ),
            "INTERNAL_ERROR",
        )

    def test_marker_race_falls_through_to_fresh_write(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Marker exists at load but disappears before replay: the False branch runs.

        The arc under test (``if handled:`` falling through) is only reachable
        when ``load_marker`` and ``replay_or_reject`` disagree, i.e. a marker
        was committed and removed between the two reads. Emulated by letting
        the first ``replay_or_reject`` call (create_unit's own check) answer
        "not handled" while every later call (inside ``execute``) uses the real
        implementation, which replays the committed marker.
        """
        inp = _create_input(duplicateConfirmed=True)
        first = _ok(lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=inp), None))
        real_replay = uop.IdempotentMutationRunner.replay_or_reject
        calls = {"n": 0}

        def flaky_replay(self: Any, *args: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                return (False, None)
            return real_replay(self, *args, **kwargs)

        monkeypatch.setattr(uop.IdempotentMutationRunner, "replay_or_reject", flaky_replay)
        again = _ok(lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=inp), None))
        # execute()'s real replay path answers with the committed result.
        assert again["unit"]["unitId"] == first["unit"]["unitId"]

    def test_duplicate_lookup_failure_allows_create(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A faulting metadataKey GSI read degrades to "no duplicate seen".

        Availability fallback: the handler cannot prove a duplicate when the
        lookup itself faults, so it proceeds. Recorded behavior, not a
        uniqueness guarantee.
        """

        def predicate(op: str, kwargs: Dict[str, Any]) -> bool:
            return op == "query" and kwargs.get("IndexName") == "metadataKey-createdAt-index"

        _fault(units_table, monkeypatch, predicate)
        dup = _create_input(
            unitType="Pack",
            unitNumber=3149,
            city="Aurora",
            state="CO",
            timezone="America/Denver",
            duplicateConfirmed=True,
            idempotency={"idempotencyKey": "edge-dup-fault"},
        )
        payload = _ok(lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=dup), None))
        assert payload["unit"]["metadataKey"] == "pack#3149#aurora#co"


# ---------------------------------------------------------------------------
# update_unit edges
# ---------------------------------------------------------------------------


class TestUpdateUnitEdges:
    def test_missing_unit_id_rejected(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={"idempotency": {"idempotencyKey": "edge-nouid"}},
                ),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_missing_idempotency_key_rejected(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event("updateUnit", "Avery", input={"unitId": fx.PACK_3149}),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_not_found_when_metadata_row_removed(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.delete_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"})
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "displayName": "Gone",
                        "idempotency": {"idempotencyKey": "edge-notfound"},
                    },
                ),
                None,
            ),
            "NOT_FOUND",
        )

    def test_top_level_expected_version_accepted(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "expectedVersion": 1,
                        "displayName": "Pack 3149 - Aurora",
                        "idempotency": {"idempotencyKey": "edge-toplevel-version"},
                    },
                ),
                None,
            )
        )
        assert payload["version"] == 2
        assert payload["displayName"] == "Pack 3149 - Aurora"

    @pytest.mark.parametrize(
        "field,value",
        [("timezone", "Not/AZone"), ("splitDefault", "MAJORITY"), ("councilNeedBasis", "WHENEVER")],
    )
    def test_invalid_settings_rejected(self, seeded: Dict[str, Any], field: str, value: str) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        field: value,
                        "idempotency": {"idempotencyKey": f"edge-bad-{field}"},
                    },
                ),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_null_city_leaves_metadata_unchanged(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        """Explicit ``null`` is "no change" (GraphQL input semantics)."""
        before = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "city": None,
                        "displayName": "Pack 3149 - Aurora, CO",
                        "idempotency": {"idempotencyKey": "edge-null-city"},
                    },
                ),
                None,
            )
        )
        assert payload["city"] == before["city"]
        assert payload["metadataKey"] == before["metadataKey"]

    def test_non_finite_decimal_unit_number_is_internal_error(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "unitNumber": Decimal("nan"),
                        "idempotency": {"idempotencyKey": "edge-nan-update"},
                    },
                ),
                None,
            ),
            # normalized_fingerprint rejects non-finite numbers up front.
            "INVALID_INPUT",
        )

    def test_duplicate_lookup_failure_allows_update(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:

        def predicate(op: str, kwargs: Dict[str, Any]) -> bool:
            return op == "query" and kwargs.get("IndexName") == "metadataKey-createdAt-index"

        _fault(units_table, monkeypatch, predicate)
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "city": "Denver",
                        "idempotency": {"idempotencyKey": "edge-dup-fault-update"},
                    },
                ),
                None,
            )
        )
        assert payload["city"] == "Denver"

    def test_write_failure_falls_back_to_direct_put(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """transact_write_items fault -> handler re-applies the item directly."""
        import src.utils.mutations as mutations

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _INJECTED

        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "displayName": "Fallback Applied",
                        "idempotency": {"idempotencyKey": "edge-fallback-update"},
                    },
                ),
                None,
            )
        )
        assert payload["displayName"] == "Fallback Applied"
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["displayName"] == "Fallback Applied"


# ---------------------------------------------------------------------------
# revoke_unit_access_grant edges
# ---------------------------------------------------------------------------


class TestRevokeEdges:
    def test_non_admin_forbidden(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitAccessGrant",
                    "Taylor",
                    input={
                        "unitId": fx.PACK_3149,
                        "accountId": fx.account_id("Avery"),
                        "idempotency": {"idempotencyKey": "edge-revoke-forbid"},
                    },
                ),
                None,
            ),
            "FORBIDDEN",
        )

    def test_missing_idempotency_key_rejected(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitAccessGrant",
                    "Avery",
                    input={"unitId": fx.PACK_3149, "accountId": fx.account_id("Blake")},
                ),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_not_found_when_metadata_row_removed(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.delete_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"})
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitAccessGrant",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "accountId": fx.account_id("Blake"),
                        "idempotency": {"idempotencyKey": "edge-revoke-notfound"},
                    },
                ),
                None,
            ),
            "NOT_FOUND",
        )

    def test_write_failure_falls_back_to_direct_put(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.utils.mutations as mutations

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _INJECTED

        meta = units_table.get_item(Key={"pk": f"UNIT#{fx.CREW_529}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        meta["adminCount"] = 2
        units_table.put_item(Item=meta)
        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitAccessGrant",
                    "Avery",
                    input={
                        "unitId": fx.CREW_529,
                        "accountId": fx.account_id("Avery"),
                        "idempotency": {"idempotencyKey": "edge-fallback-revoke"},
                    },
                ),
                None,
            )
        )
        assert payload["adminCount"] == 1


# ---------------------------------------------------------------------------
# create_unit_invite edges
# ---------------------------------------------------------------------------


class TestCreateInviteEdges:
    def test_missing_idempotency_key_rejected(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event("createUnitInvite", "Riley", input={"unitId": fx.TROOP_7150}),
                None,
            ),
            "INVALID_INPUT",
        )

    def test_non_admin_forbidden(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Devon",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-inv-forbid"}},
                ),
                None,
            ),
            "FORBIDDEN",
        )

    def test_cap_scan_tolerates_odd_expiry_formats(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        naive = fx.invite_item("NAIVE00000000001", fx.TROOP_7150, "Riley")
        naive["expiresAt"] = "2030-01-01T00:00:00"  # naive ISO: tzinfo None branch
        units_table.put_item(Item=naive)
        garbage = fx.invite_item("GARBAGE000000001", fx.TROOP_7150, "Riley")
        garbage["expiresAt"] = "not-a-date"  # unparseable: except branch
        units_table.put_item(Item=garbage)
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Riley",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-odd-expiry"}},
                ),
                None,
            )
        )
        assert payload["inviteCode"] not in {"NAIVE00000000001", "GARBAGE000000001"}

    def test_scan_failure_still_creates(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, lambda op, _kwargs: op == "scan")
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Riley",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-scan-fault"}},
                ),
                None,
            )
        )
        assert payload["inviteCode"]

    def test_marker_read_failure_still_creates(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("IDEM#createUnitInvite"))
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Riley",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-marker-read-fault"}},
                ),
                None,
            )
        )
        assert payload["inviteCode"]

    def test_marker_replay_without_invite_mints_new_code(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": f"IDEM#createUnitInvite#{fx.TROOP_7150}",
                "sk": "IDEM#stale-replay-key",
                "inviteCode": "ZZZZZZZZZZZZZZZZ",
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Riley",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "stale-replay-key"}},
                ),
                None,
            )
        )
        assert payload["inviteCode"] != "ZZZZZZZZZZZZZZZZ"
        assert (
            units_table.get_item(
                Key={"pk": f"INVITE#{payload['inviteCode']}", "sk": f"UNIT#{fx.TROOP_7150}"}, ConsistentRead=True
            ).get("Item")
            is not None
        )

    def test_marker_write_failure_swallowed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("IDEM#createUnitInvite"))
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "createUnitInvite",
                    "Riley",
                    input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-marker-write-fault"}},
                ),
                None,
            )
        )
        assert payload["inviteCode"]


# ---------------------------------------------------------------------------
# revoke_unit_invite edges
# ---------------------------------------------------------------------------


class TestRevokeInviteEdges:
    def test_non_admin_forbidden(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitInvite",
                    "Taylor",
                    input={"unitId": fx.PACK_3149, "inviteCode": "PKT3149ACTIVE001"},
                ),
                None,
            ),
            "FORBIDDEN",
        )


# ---------------------------------------------------------------------------
# redeem_unit_invite edges
# ---------------------------------------------------------------------------


class TestRedeemEdges:
    def test_missing_caller_identity_unauthorized(self, seeded: Dict[str, Any]) -> None:
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    None,
                    input={"inviteCode": "PKT3149ACTIVE001", "idempotency": {"idempotencyKey": "edge-anon"}},
                ),
                None,
            ),
            "UNAUTHORIZED",
        )

    def test_marker_read_failure_proceeds(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("IDEM#redeemUnitInvite"))
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={
                        "inviteCode": "TRP7150ACTIVE001",
                        "idempotency": {"idempotencyKey": "edge-redeem-read-fault"},
                    },
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Devon')}"

    def test_marker_without_unit_id_proceeds(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": "IDEM#redeemUnitInvite#TRP7150ACTIVE001",
                "sk": "IDEM#rk-no-unit-id",
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={"inviteCode": "TRP7150ACTIVE001", "idempotency": {"idempotencyKey": "rk-no-unit-id"}},
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Devon')}"

    def test_marker_with_missing_grant_proceeds(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": "IDEM#redeemUnitInvite#TRP7150ACTIVE001",
                "sk": "IDEM#rk-stale-grant",
                "unitId": fx.TROOP_7150,
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={"inviteCode": "TRP7150ACTIVE001", "idempotency": {"idempotencyKey": "rk-stale-grant"}},
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Devon')}"

    def test_throttle_counter_write_failure_swallowed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("THROTTLE#"))
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={"inviteCode": "NOPE000000000000", "idempotency": {"idempotencyKey": "edge-throttle-write"}},
                ),
                None,
            ),
            "NOT_FOUND",
        )

    def test_throttle_read_failure_ignored(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("THROTTLE#"))
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={"inviteCode": "TRP7150ACTIVE001", "idempotency": {"idempotencyKey": "edge-throttle-read"}},
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Devon')}"

    def test_consistent_query_failure_falls_back(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:

        def predicate(op: str, kwargs: Dict[str, Any]) -> bool:
            return op == "query" and kwargs.get("ConsistentRead") is True

        _fault(units_table, monkeypatch, predicate)
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Devon",
                    input={"inviteCode": "NOPE000000000001", "idempotency": {"idempotencyKey": "edge-query-fallback"}},
                ),
                None,
            ),
            "NOT_FOUND",
        )

    def test_existing_grant_read_failure_proceeds(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(
            units_table,
            monkeypatch,
            lambda op, kwargs: op == "get_item" and str(kwargs.get("Key", {}).get("sk", "")).startswith("GRANT#"),
        )
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Emery",
                    input={
                        "inviteCode": "PKT3149ACTIVE001",
                        "idempotency": {"idempotencyKey": "edge-grant-read-fault"},
                    },
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Emery')}"

    def test_naive_expiry_accepted(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": "INVITE#NAIVEREDEEM00001",
                "sk": f"UNIT#{fx.CREW_529}",
                "inviteCode": "NAIVEREDEEM00001",
                "unitId": fx.CREW_529,
                "createdByAccountId": fx.account_id("Avery"),
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": (datetime.now(timezone.utc) + timedelta(days=7)).replace(tzinfo=None).isoformat(),
                "expiresAtEpoch": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
            }
        )
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Emery",
                    input={"inviteCode": "NAIVEREDEEM00001", "idempotency": {"idempotencyKey": "edge-naive-redeem"}},
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Emery')}"

    def test_unparseable_expiry_is_not_found(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": "INVITE#GARBAGEREDEEM001",
                "sk": f"UNIT#{fx.CREW_529}",
                "inviteCode": "GARBAGEREDEEM001",
                "unitId": fx.CREW_529,
                "createdByAccountId": fx.account_id("Avery"),
                "createdAt": "2026-01-01T00:00:00+00:00",
                "expiresAt": "not-a-date",
                "expiresAtEpoch": 1,
            }
        )
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Emery",
                    input={"inviteCode": "GARBAGEREDEEM001", "idempotency": {"idempotencyKey": "edge-garbage-redeem"}},
                ),
                None,
            ),
            "NOT_FOUND",
        )

    def test_missing_unit_metadata_still_grants(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        units_table.put_item(
            Item={
                "pk": "INVITE#ORPHANED0000001",
                "sk": f"UNIT#{fx.CREW_529}",
                "inviteCode": "ORPHANED0000001",
                "unitId": fx.CREW_529,
                "createdByAccountId": fx.account_id("Avery"),
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "expiresAtEpoch": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
            }
        )
        units_table.delete_item(Key={"pk": f"UNIT#{fx.CREW_529}", "sk": "METADATA"})
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Emery",
                    input={"inviteCode": "ORPHANED0000001", "idempotency": {"idempotencyKey": "edge-orphan-redeem"}},
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Emery')}"

    def test_marker_write_failure_swallowed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, _pk_startswith("IDEM#redeemUnitInvite"))
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "redeemUnitInvite",
                    "Emery",
                    input={
                        "inviteCode": "PKT3149ACTIVE001",
                        "idempotency": {"idempotencyKey": "edge-redeem-write-fault"},
                    },
                ),
                None,
            )
        )
        assert payload["sk"] == f"GRANT#{fx.account_id('Emery')}"


# ---------------------------------------------------------------------------
# Query edges: my_units / unit / unit_admins / unit_invites / dispatch
# ---------------------------------------------------------------------------


class TestQueryEdges:
    def test_admin_lookup_fault_treated_as_not_admin(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(
            units_table,
            monkeypatch,
            lambda op, kwargs: op == "get_item" and str(kwargs.get("Key", {}).get("sk", "")).startswith("GRANT#"),
        )
        assert (
            lambda_handler(fx.unit_operation_event("unit", "Avery", arguments={"unitId": fx.PACK_3149}), None) is None
        )

    def test_my_units_scan_failure_returns_empty(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, lambda op, _kwargs: op == "scan")
        payload = _ok(lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None))
        assert payload["items"] == []
        assert payload["pageInfo"]["hasNextPage"] is False

    def test_my_units_bad_cursor_starts_at_zero(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"cursor": "not-a-number"}}),
                None,
            )
        )
        assert len(payload["items"]) == 2  # Pack + Crew from page start

    def test_my_units_skips_malformed_and_dangling_grants(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        avery = fx.account_id("Avery")
        units_table.put_item(Item={"pk": "UNIT#unit-ghost-no-uid", "sk": f"GRANT#{avery}", "accountId": avery})
        units_table.put_item(
            Item={
                "pk": "UNIT#unit-ghost-deleted",
                "sk": f"GRANT#{avery}",
                "unitId": "unit-ghost-deleted",
                "accountId": avery,
                "role": "UNIT_ADMIN",
                "createdAt": "2026-01-01T00:00:00+00:00",
            }
        )
        payload = _ok(lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None))
        assert sorted(u["unitId"] for u in payload["items"]) == sorted([fx.PACK_3149, fx.CREW_529])

    def test_unit_admins_scan_failure_returns_empty(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, lambda op, _kwargs: op == "scan")
        payload = _ok(
            lambda_handler(fx.unit_operation_event("unitAdmins", "Riley", arguments={"unitId": fx.TROOP_7150}), None)
        )
        assert payload["items"] == []

    def test_unit_admins_bad_cursor_starts_at_zero(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "unitAdmins",
                    "Riley",
                    arguments={"unitId": fx.TROOP_7150, "page": {"cursor": "junk"}},
                ),
                None,
            )
        )
        assert [g["accountId"] for g in payload["items"]] == [fx.account_id("Riley")]

    def test_unit_invites_query_failure_returns_empty(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(
            units_table,
            monkeypatch,
            lambda op, kwargs: op == "query" and kwargs.get("IndexName") == "unitId-createdAt-index",
        )
        payload = _ok(
            lambda_handler(fx.unit_operation_event("unitInvites", "Avery", arguments={"unitId": fx.PACK_3149}), None)
        )
        assert payload["items"] == []

    def test_unit_invites_bad_cursor_starts_at_zero(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "unitInvites",
                    "Avery",
                    arguments={"unitId": fx.PACK_3149, "page": {"cursor": "junk"}},
                ),
                None,
            )
        )
        assert [i["inviteCode"] for i in payload["items"]] == ["PKT3149ACTIVE001"]

    def test_unit_invites_lists_odd_expiry_formats(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        naive = fx.invite_item("NAIVELIST0000001", fx.TROOP_7150, "Riley")
        naive["expiresAt"] = "2030-01-01T00:00:00"  # naive ISO: tz attach branch
        units_table.put_item(Item=naive)
        garbage = fx.invite_item("GARBAGELIST00001", fx.TROOP_7150, "Riley")
        garbage["expiresAt"] = "not-a-date"  # unparseable: kept (defensive)
        units_table.put_item(Item=garbage)
        payload = _ok(
            lambda_handler(fx.unit_operation_event("unitInvites", "Riley", arguments={"unitId": fx.TROOP_7150}), None)
        )
        codes = {i["inviteCode"] for i in payload["items"]}
        assert {"TRP7150ACTIVE001", "NAIVELIST0000001", "GARBAGELIST00001"} <= codes

    def test_unknown_field_rejected(self, seeded: Dict[str, Any]) -> None:
        event = fx.unit_operation_event("unit", "Avery", arguments={"unitId": fx.PACK_3149})
        event["info"]["fieldName"] = "definitelyNotAUnitField"
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")


# ---------------------------------------------------------------------------
# Pagination clamp (_parse_page)
# ---------------------------------------------------------------------------


class TestPaginationClamps:
    def test_non_numeric_limit_falls_back_to_default(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"limit": "many"}}),
                None,
            )
        )
        assert len(payload["items"]) == 2

    def test_limit_clamped_to_minimum(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"limit": 0}}), None)
        )
        assert len(payload["items"]) == 1
        assert payload["pageInfo"]["hasNextPage"] is True

    def test_limit_clamped_to_maximum(self, seeded: Dict[str, Any]) -> None:
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"limit": 500}}),
                None,
            )
        )
        assert len(payload["items"]) == 2
        assert payload["pageInfo"]["hasNextPage"] is False
