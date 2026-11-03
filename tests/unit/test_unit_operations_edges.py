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
from botocore.exceptions import ClientError, EndpointConnectionError

from src.handlers import unit_operations as uop
from src.handlers.unit_operations import lambda_handler
from src.utils.mutations import (
    MARKER_STATUS_COMPLETED,
    marker_partition_key,
    marker_sort_key,
    normalized_fingerprint,
)
from tests.unit import show_sell_fixtures as fx

_INJECTED = ClientError(
    {"Error": {"Code": "InternalServerError", "Message": "injected fault"}},
    "injected",
)
# A genuine transport fault: the one exception class the DEF-11 fallback is
# authorized to contain (mutations.py classifies service verdicts). EndpointConnectionError is a BotoCoreError subclass.
_TRANSPORT_FAULT = EndpointConnectionError(endpoint_url="https://dynamodb-fault.invalid")


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


def _wire_pk(kwargs: Dict[str, Any]) -> str:
    """Read one row's pk from a Key/Item body in plain or wire (typed) form."""
    body = kwargs.get("Key") or kwargs.get("Item") or {}
    pk = body.get("pk", "")
    if isinstance(pk, dict):
        return str(pk.get("S", ""))
    return str(pk)


def _marker_operations(segment: str) -> Callable[[str, Dict[str, Any]], bool]:
    """Fault writes touching an idempotency marker whose pk carries ``segment``.

    Marker keys follow the data model §8.9 actor-scoped layout
    (``IDEM#<actor>#<operation>#<scope>``); the handler helper names the
    physical table, so predicates match on the operation segment.
    """

    def predicate(op: str, kwargs: Dict[str, Any]) -> bool:
        pk = _wire_pk(kwargs)
        return pk.startswith("IDEM#") and segment in pk

    return predicate


class _FaultingClient:
    """Plain-client stand-in for ``src.utils.mutations._get_client`` faults.

    Marker reads and transactions go through the wire-form client, not the
    resource table, so fault injection for those operations happens here.
    """

    def __init__(self, transact_exc: Exception = None, get_item_exc: Exception = None) -> None:
        self._transact_exc = transact_exc
        self._get_item_exc = get_item_exc

    def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
        if self._get_item_exc is not None:
            raise self._get_item_exc
        return {}

    def transact_write_items(self, **_kwargs: Any) -> None:
        if self._transact_exc is not None:
            raise self._transact_exc


def _create_public_order_throttles_table() -> Any:
    """Create the §6.6 throttles table (excluded from create_all_tables on
    purpose so the seeded fixture-count contract stays exact)."""
    import boto3

    from tests.unit import table_schemas as schemas

    schema = schemas.create_public_order_throttles_table_schema()
    ttl = schema.pop("TimeToLiveSpecification", None)
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.create_table(**schema)
    if ttl is not None:
        dynamodb.meta.client.update_time_to_live(TableName=table.table_name, TimeToLiveSpecification=ttl)
    return table


def _fault_throttles(monkeypatch: pytest.MonkeyPatch, predicate: Callable[[str, Dict[str, Any]], bool]) -> None:
    monkeypatch.setattr(uop, "_throttles", lambda: _FlakyTable(_create_public_order_throttles_table(), predicate))


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

    def test_marker_race_verdict_reaches_the_caller(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An idempotency-key race surfaces as RESOURCE_BUSY and must never be
        overridden by the DEF-11 fallback, which would write a second Unit under
        a key the winner already committed (F4 adjudication)."""
        import src.utils.mutations as mutations

        class _RacingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise ClientError(
                    {
                        "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                        "CancellationReasons": [
                            {
                                "Code": "ConditionalCheckFailed",
                                "Message": "lost the marker race",
                                "Item": {
                                    "pk": {"S": "IDEM#someone#createUnit#BOOTSTRAP"},
                                    "sk": {"S": "IDEM#race-key"},
                                    "fingerprint": {"S": "sha256:opaque"},
                                    "status": {"S": "COMPLETED"},
                                },
                            }
                        ],
                    },
                    "TransactWriteItems",
                )

        monkeypatch.setattr(mutations, "_get_client", lambda: _RacingClient())
        before = sum(1 for i in units_table.scan()["Items"] if i["sk"] == "METADATA")
        payload = lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=_create_input()), None)
        fx.assert_is_error(payload, "RESOURCE_BUSY")
        after = sum(1 for i in units_table.scan()["Items"] if i["sk"] == "METADATA")
        assert after == before  # no fresh write was applied over the winner

    def test_write_failure_falls_back_to_direct_put(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """transact_write_items *transport* fault -> unit AND its creator grant must both persist.

        The transaction stages three writes (marker, unit, grant); a fallback
        that writes only the unit leaves adminCount=1 with no GRANT# row, so
        the unit is unadministrable and invisible to myUnits. Both rows are
        the contract.
        """
        import src.utils.mutations as mutations

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _TRANSPORT_FAULT

        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        payload = _ok(lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=_create_input()), None))
        unit_id = payload["unit"]["unitId"]
        assert (
            units_table.get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"}, ConsistentRead=True).get("Item")
            is not None
        )
        assert (
            units_table.get_item(
                Key={"pk": f"UNIT#{unit_id}", "sk": f"GRANT#{fx.account_id('Emery')}"}, ConsistentRead=True
            ).get("Item")
            is not None
        )

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

    def test_non_string_city_takes_no_strip_path(self, seeded: Dict[str, Any]) -> None:
        """Defensive arc: a non-string city reaches the branch but skips strip().

        Unreachable through AppSync (the GraphQL schema types ``city`` as
        String), so this only pins that the handler does not 500 on the guard.
        """
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "city": 123,
                        "idempotency": {"idempotencyKey": "edge-city-garbage"},
                    },
                ),
                None,
            )
        )
        assert payload["unitId"] == fx.PACK_3149

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
                raise _TRANSPORT_FAULT

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

    def test_stale_condition_surface_verdict_not_silent_overwrite(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The version condition inside the transaction is the concurrency backstop:
        a write whose snapshot was superseded between the pre-check and the
        transaction surfaces CONFLICT verdict verbatim, never falling back over
        the concurrent commit."""
        import src.utils.mutations as mutations

        class _ConflictingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise ClientError(
                    {
                        "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                        "CancellationReasons": [{"Code": "ConditionalCheckFailedException"}],
                    },
                    "TransactWriteItems",
                )

        monkeypatch.setattr(mutations, "_get_client", lambda: _ConflictingClient())
        payload = lambda_handler(
            fx.unit_operation_event(
                "updateUnit",
                "Avery",
                input={
                    "unitId": fx.PACK_3149,
                    "displayName": "Raced Away",
                    "idempotency": {"idempotencyKey": "edge-condition-update"},
                },
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["displayName"] != "Raced Away"
        assert stored["version"] == 1

    def test_retry_hash_ignores_key_padding_and_version_envelope(
        self, units_table: Any, seeded: Dict[str, Any]
    ) -> None:
        """F7: the updateUnit fingerprint carries request content only - the
        idempotencyKey and the version envelope are not part of it, so a replay
        sent with a padded key and without the version object still replays."""
        first = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "version": {"expectedVersion": 1},
                        "displayName": "Normalized Replay",
                        "idempotency": {"idempotencyKey": "edge-normalized-1"},
                    },
                ),
                None,
            )
        )
        assert first["version"] == 2
        retry = lambda_handler(
            fx.unit_operation_event(
                "updateUnit",
                "Avery",
                input={
                    "unitId": fx.PACK_3149,
                    "displayName": "Normalized Replay",
                    "idempotency": {"idempotencyKey": "  edge-normalized-1  "},
                },
            ),
            None,
        )
        assert not retry.get("__isError"), retry
        assert retry["unitId"] == fx.PACK_3149
        assert retry["version"] == 2  # replay, not a second write
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["version"] == 2

    def test_fallback_put_condition_failure_returns_committed_state(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R3: the fallback Put carries the same version ConditionExpression as
        the staged one. When the fallback Put itself loses the race (its
        condition fails), the handler must read the committed state and return
        it - never overwrite the concurrent commit, never silently undo it."""
        import src.utils.mutations as mutations

        condition_failed = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "the conditional request failed",
                }
            },
            "PutItem",
        )

        class _RacingTable:
            """Faults only the fallback Put; reads delegate to the real table."""

            def __init__(self, real: Any) -> None:
                self._real = real

            @property
            def name(self) -> str:
                return self._real.name

            def put_item(self, **_kwargs: Any) -> Dict[str, Any]:
                raise condition_failed

            def __getattr__(self, attr_name: str) -> Any:
                return getattr(self._real, attr_name)

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _TRANSPORT_FAULT

        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        monkeypatch.setattr(uop, "_units", lambda: _RacingTable(units_table))
        stored_before = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)[
            "Item"
        ]
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "displayName": "Raced Away By Fallback Put",
                        "idempotency": {"idempotencyKey": "edge-fallback-race"},
                    },
                ),
                None,
            )
        )
        # The committed (concurrent) state is returned, not the stale snapshot.
        assert payload["unitId"] == fx.PACK_3149
        assert payload.get("displayName") != "Raced Away By Fallback Put"
        assert payload["version"] == stored_before["version"]
        stored_after = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)[
            "Item"
        ]
        assert stored_after == stored_before

    def test_fallback_put_condition_failure_with_missing_unit_raises(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If even the committed read comes back empty after a failed fallback
        Put, the handler has nothing true to report and must re-raise."""
        import src.utils.mutations as mutations

        condition_failed = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "the conditional request failed",
                }
            },
            "PutItem",
        )

        class _RacingTable:
            def __init__(self, real: Any) -> None:
                self._real = real

            @property
            def name(self) -> str:
                return self._real.name

            def put_item(self, **_kwargs: Any) -> Dict[str, Any]:
                raise condition_failed

            def __getattr__(self, attr_name: str) -> Any:
                return getattr(self._real, attr_name)

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _TRANSPORT_FAULT

        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        monkeypatch.setattr(uop, "_units", lambda: _RacingTable(units_table))
        monkeypatch.setattr(uop, "_get_unit", lambda rid: None)
        fx.assert_is_error(
            lambda_handler(
                fx.unit_operation_event(
                    "updateUnit",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "displayName": "Vanished Mid-flight",
                        "idempotency": {"idempotencyKey": "edge-fallback-vanish"},
                    },
                ),
                None,
            ),
            "INTERNAL_ERROR",
        )

    def test_fallback_put_unexpected_error_not_swallowed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A generic service fault from the fallback Put is neither contained
        nor swallowed: the handler surfaces the error verdict."""
        import src.utils.mutations as mutations

        class _FailingTable:
            def __init__(self, real: Any) -> None:
                self._real = real

            @property
            def name(self) -> str:
                return self._real.name

            def put_item(self, **_kwargs: Any) -> Dict[str, Any]:
                raise _INJECTED

            def __getattr__(self, attr_name: str) -> Any:
                return getattr(self._real, attr_name)

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _TRANSPORT_FAULT

        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        monkeypatch.setattr(uop, "_units", lambda: _FailingTable(units_table))
        payload = lambda_handler(
            fx.unit_operation_event(
                "updateUnit",
                "Avery",
                input={
                    "unitId": fx.PACK_3149,
                    "displayName": "Double Fault",
                    "idempotency": {"idempotencyKey": "edge-fallback-other-fault"},
                },
            ),
            None,
        )
        assert isinstance(payload, dict) and payload.get("__isError") is True, payload
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["displayName"] != "Double Fault"


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

    def test_transaction_fault_verdict_is_reported_not_faked(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The revoke transaction stages the grant delete, count decrement and
        version bump atomically; a fault surfaces as RESOURCE_BUSY with zero
        partial effects, and the retry re-rules from a clean read."""
        import src.utils.mutations as mutations

        class _FailingClient:
            def get_item(self, **_kwargs: Any) -> Dict[str, Any]:
                return {}

            def transact_write_items(self, **_kwargs: Any) -> None:
                raise _TRANSPORT_FAULT

        meta = units_table.get_item(Key={"pk": f"UNIT#{fx.CREW_529}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        meta["adminCount"] = 2
        units_table.put_item(Item=meta)
        monkeypatch.setattr(mutations, "_get_client", lambda: _FailingClient())
        payload = lambda_handler(
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
        fx.assert_is_error(payload, "RESOURCE_BUSY")
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.CREW_529}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["adminCount"] == 2
        assert stored["version"] == 1
        assert (
            units_table.get_item(
                Key={"pk": f"UNIT#{fx.CREW_529}", "sk": f"GRANT#{fx.account_id('Avery')}"}, ConsistentRead=True
            ).get("Item")
            is not None
        )

    def test_missing_grant_is_an_idempotent_noop(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        """Revoking a grant that does not exist (wrong accountId, or a concurrent
        admin already revoked it) must not decrement adminCount or bump version."""
        meta = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        meta["adminCount"] = 2
        units_table.put_item(Item=meta)
        payload = _ok(
            lambda_handler(
                fx.unit_operation_event(
                    "revokeUnitAccessGrant",
                    "Avery",
                    input={
                        "unitId": fx.PACK_3149,
                        "accountId": fx.account_id("Emery"),
                        "version": {"expectedVersion": 1},
                        "idempotency": {"idempotencyKey": "edge-revoke-noop"},
                    },
                ),
                None,
            )
        )
        assert payload["unitId"] == fx.PACK_3149
        assert payload["adminCount"] == 2
        stored = units_table.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert stored["adminCount"] == 2
        assert stored["version"] == 1


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

    def test_cap_count_fault_fails_closed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fault inside the 20-active-cap count fails the request closed: writing
        blind would silently waive the cap (F3/F5 adjudication)."""

        def predicate(op: str, kwargs: Dict[str, Any]) -> bool:
            return op == "query" and kwargs.get("IndexName") == "unitId-createdAt-index"

        _fault(units_table, monkeypatch, predicate)
        before = len([i for i in units_table.scan()["Items"] if str(i["pk"]).startswith("INVITE#")])
        payload = lambda_handler(
            fx.unit_operation_event(
                "createUnitInvite",
                "Riley",
                input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-cap-fault-closed"}},
            ),
            None,
        )
        fx.assert_is_error(payload, "RESOURCE_BUSY")
        after = len([i for i in units_table.scan()["Items"] if str(i["pk"]).startswith("INVITE#")])
        assert after == before

    def test_marker_read_fault_refuses_to_run(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A marker read the handler cannot resolve means it cannot prove no
        identical request succeeded: refusal without a fresh write."""
        import src.utils.mutations as mutations

        monkeypatch.setattr(mutations, "_get_client", lambda: _FaultingClient(get_item_exc=_INJECTED))
        payload = lambda_handler(
            fx.unit_operation_event(
                "createUnitInvite",
                "Riley",
                input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-marker-read-fault"}},
            ),
            None,
        )
        fx.assert_is_error(payload, "INTERNAL_ERROR")

    def test_completed_marker_replays_verdict_without_reminting(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        """A COMPLETED marker is always the answer, even when its result row is
        gone: the replay verdict is returned verbatim - no marker deletion, no
        re-run, and no second active invite is minted."""
        mk_pk = marker_partition_key(fx.account_id("Riley"), "createUnitInvite", fx.TROOP_7150)
        mk_sk = marker_sort_key("stale-replay-key")
        units_table.put_item(
            Item={
                "pk": mk_pk,
                "sk": mk_sk,
                "fingerprint": normalized_fingerprint({"unitId": fx.TROOP_7150}),
                "status": MARKER_STATUS_COMPLETED,
                "resultId": "ZZZZZZZZZZZZZZZZ",
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        before = [i for i in units_table.scan()["Items"] if str(i.get("pk", "")).startswith("INVITE#")]
        payload = lambda_handler(
            fx.unit_operation_event(
                "createUnitInvite",
                "Riley",
                input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "stale-replay-key"}},
            ),
            None,
        )
        assert payload is None
        after = [i for i in units_table.scan()["Items"] if str(i.get("pk", "")).startswith("INVITE#")]
        assert len(after) == len(before)
        marker = units_table.get_item(Key={"pk": mk_pk, "sk": mk_sk}, ConsistentRead=True).get("Item")
        assert marker is not None
        assert marker["status"] == MARKER_STATUS_COMPLETED

    def test_marker_write_fault_refuses_to_mint(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The invite and its marker commit atomically: a transaction fault writes
        nothing (no un-marked active invite a retry would double)."""
        import src.utils.mutations as mutations

        monkeypatch.setattr(mutations, "_get_client", lambda: _FaultingClient(transact_exc=_INJECTED))
        before = len([i for i in units_table.scan()["Items"] if str(i["pk"]).startswith("INVITE#")])
        payload = lambda_handler(
            fx.unit_operation_event(
                "createUnitInvite",
                "Riley",
                input={"unitId": fx.TROOP_7150, "idempotency": {"idempotencyKey": "edge-marker-write-fault"}},
            ),
            None,
        )
        fx.assert_is_error(payload, "INTERNAL_ERROR")
        after = len([i for i in units_table.scan()["Items"] if str(i["pk"]).startswith("INVITE#")])
        assert after == before


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

    def test_marker_read_fault_refuses_to_run(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A marker read the handler cannot resolve keeps the runner's verdict:
        refusing beats minting a second grant under one key."""
        import src.utils.mutations as mutations

        monkeypatch.setattr(mutations, "_get_client", lambda: _FaultingClient(get_item_exc=_INJECTED))
        payload = lambda_handler(
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
        fx.assert_is_error(payload, "INTERNAL_ERROR")

    def test_marker_without_result_ref_refuses_to_run(self, units_table: Any, seeded: Dict[str, Any]) -> None:
        """A completed §8.9 marker with no result reference cannot be replayed:
        the runner's refusal verdict reaches the caller instead of a re-run."""
        units_table.put_item(
            Item={
                "pk": marker_partition_key(fx.account_id("Devon"), "redeemUnitInvite", "TRP7150ACTIVE001"),
                "sk": marker_sort_key("rk-no-result-ref"),
                "fingerprint": normalized_fingerprint({"inviteCode": "TRP7150ACTIVE001"}),
                "status": MARKER_STATUS_COMPLETED,
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        payload = lambda_handler(
            fx.unit_operation_event(
                "redeemUnitInvite",
                "Devon",
                input={"inviteCode": "TRP7150ACTIVE001", "idempotency": {"idempotencyKey": "rk-no-result-ref"}},
            ),
            None,
        )
        fx.assert_is_error(payload, "INTERNAL_ERROR")
        # Nothing was written below the refused replay.
        grant = units_table.get_item(
            Key={"pk": f"UNIT#{fx.TROOP_7150}", "sk": f"GRANT#{fx.account_id('Devon')}"}, ConsistentRead=True
        )
        assert "Item" not in grant

    def test_completed_marker_replays_verdict_without_regranting(
        self, units_table: Any, seeded: Dict[str, Any]
    ) -> None:
        """A COMPLETED redeem marker is always the answer, even when its grant
        row is gone: the replay verdict is returned verbatim - no marker
        deletion, no re-run, and no second grant under the same key."""
        mk_pk = marker_partition_key(fx.account_id("Devon"), "redeemUnitInvite", "TRP7150ACTIVE001")
        mk_sk = marker_sort_key("rk-stale-grant")
        units_table.put_item(
            Item={
                "pk": mk_pk,
                "sk": mk_sk,
                "fingerprint": normalized_fingerprint({"inviteCode": "TRP7150ACTIVE001"}),
                "status": MARKER_STATUS_COMPLETED,
                "resultId": fx.TROOP_7150,
                "expiresAtEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
            }
        )
        payload = lambda_handler(
            fx.unit_operation_event(
                "redeemUnitInvite",
                "Devon",
                input={"inviteCode": "TRP7150ACTIVE001", "idempotency": {"idempotencyKey": "rk-stale-grant"}},
            ),
            None,
        )
        assert payload is None
        grant = units_table.get_item(
            Key={"pk": f"UNIT#{fx.TROOP_7150}", "sk": f"GRANT#{fx.account_id('Devon')}"}, ConsistentRead=True
        )
        assert "Item" not in grant
        marker = units_table.get_item(Key={"pk": mk_pk, "sk": mk_sk}, ConsistentRead=True).get("Item")
        assert marker is not None
        assert marker["status"] == MARKER_STATUS_COMPLETED

    def test_throttle_counter_write_failure_swallowed(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuinely unavailable failure counter stays best-effort: the
        NOT_FOUND verdict for the attempt itself still reaches the caller."""
        _fault_throttles(monkeypatch, lambda op, _kwargs: op == "update_item")
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

    def test_marker_write_fault_refuses_to_grant(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Grant, invite burn and adminCount sync commit atomically with the
        marker: a transaction fault writes nothing and surfaces verbatim."""
        import src.utils.mutations as mutations

        monkeypatch.setattr(mutations, "_get_client", lambda: _FaultingClient(transact_exc=_INJECTED))
        payload = lambda_handler(
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
        fx.assert_is_error(payload, "INTERNAL_ERROR")
        # the invite was not burned by the aborted transaction
        assert (
            units_table.get_item(
                Key={"pk": "INVITE#PKT3149ACTIVE001", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
            ).get("Item")
            is not None
        )


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

    def test_my_units_index_query_failure_returns_empty(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(
            units_table, monkeypatch, lambda op, _kw: op == "query" and _kw.get("IndexName") == "accountId-unitId-index"
        )
        payload = _ok(lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None))
        assert payload["items"] == []
        assert payload["pageInfo"]["hasNextPage"] is False

    def test_my_units_skips_grant_row_missing_unit_id(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A projected grant row without a unitId cannot name a unit, so the
        page skips it (`continue`) rather than crashing on a malformed GetItem
        key - the real GSI cannot project such a row, so the projection is
        injected at the query boundary."""
        avery = fx.account_id("Avery")

        class _GraftedGrantTable:
            def __init__(self, real: Any) -> None:
                self._real = real

            @property
            def name(self) -> str:
                return self._real.name

            def query(self, **kwargs: Any) -> Dict[str, Any]:
                resp = getattr(self._real, "query")(**kwargs)
                if kwargs.get("IndexName") == "accountId-unitId-index":
                    resp = {k: v for k, v in resp.items()}
                    resp["Items"] = list(resp.get("Items", [])) + [
                        {"pk": "UNIT#unit-ghost-unnamed", "sk": f"GRANT#{avery}", "accountId": avery}
                    ]
                return resp

            def __getattr__(self, attr_name: str) -> Any:
                return getattr(self._real, attr_name)

        monkeypatch.setattr(uop, "_units", lambda: _GraftedGrantTable(units_table))
        payload = _ok(lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None))
        assert sorted(u["unitId"] for u in payload["items"]) == sorted([fx.PACK_3149, fx.CREW_529])

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

    def test_unit_admins_base_query_failure_returns_empty(
        self, units_table: Any, seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fault(units_table, monkeypatch, lambda op, kw: op == "query" and "IndexName" not in kw)
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
