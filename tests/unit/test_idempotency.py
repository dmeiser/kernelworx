"""Leaf 1.7.2: the shared mutation helper's contract.

Every Show & Sell / inventory mutation in Stages 1-5 writes through
``src/utils/mutations.py``, so these tests are the gate on the program's single
write path: fingerprint normalization, marker survival, original-result replay,
same-key/different-fingerprint rejection, zero partial writes on a failed
condition, the CONFLICT/RESOURCE_BUSY split, and the 90/91-action boundary
(data model §8.9-8.10, API contract §3.1/§3.4).

Live DynamoDB semantics are exercised against moto (it enforces transaction
conditions and reports ``CancellationReasons`` with ``ALL_OLD`` items, which is
what the marker-race discriminator reads); transport faults are injected with a
stub client because moto cannot throttle on demand.
"""

from __future__ import annotations

import time
from typing import Any, cast
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from moto import mock_aws

from src.utils.dynamodb import reset_dynamodb_resource
from src.utils.errors import AppError, ErrorCode
from src.utils.mutations import (
    BOOTSTRAP_SCOPE,
    MARKER_STATUS_COMPLETED,
    MARKER_STATUS_IN_FLIGHT,
    MARKER_TTL_ATTRIBUTE,
    MARKER_TTL_SECONDS,
    MAX_TRANSACTION_ACTIONS,
    IdempotentMutationRunner,
    WritePlan,
    build_marker_item,
    classify_transaction_error,
    marker_keys,
    marker_partition_key,
    marker_sort_key,
    marker_ttl_epoch,
    normalized_fingerprint,
)

UNITS_TABLE = "kernelworx-units-ue1-dev"


def _client() -> Any:
    """A moto DynamoDB client with the units table shape from table_schemas."""
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=UNITS_TABLE,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.update_time_to_live(
        TableName=UNITS_TABLE,
        TimeToLiveSpecification={"AttributeName": MARKER_TTL_ATTRIBUTE, "Enabled": True},
    )
    return dynamodb


def _keys(
    actor: str = "ACCOUNT#alex", operation: str = "createUnit", scope: str = BOOTSTRAP_SCOPE, key: str = "k-1"
) -> Any:
    return marker_keys(
        table_key="units",
        table_name=UNITS_TABLE,
        actor_id=actor,
        operation=operation,
        scope=scope,
        idempotency_key=key,
    )


def _payload() -> dict[str, Any]:
    return {
        "unitType": "Pack",
        "unitNumber": 12,
        "city": "Austin",
        "state": "TX",
        "displayName": None,
        "timezone": "America/Chicago",
        "splitDefault": "EQUAL",
    }


def _unit_put(unit_id: str, *, version: int = 1) -> dict[str, Any]:
    return {
        "TableName": UNITS_TABLE,
        "Item": {
            "pk": {"S": f"UNIT#{unit_id}"},
            "sk": {"S": "METADATA"},
            "unitId": {"S": unit_id},
            "adminCount": {"N": "1"},
            "version": {"N": str(version)},
        },
        "ConditionExpression": "attribute_not_exists(#pk)",
        "ExpressionAttributeNames": {"#pk": "pk"},
    }


def _staged_plan(client: Any, keys: Any, fingerprint: str, *, extra: list[dict[str, Any]] | None = None) -> WritePlan:
    plan = WritePlan()
    IdempotentMutationRunner(client).stage_marker(plan, keys, fingerprint=fingerprint, result_id="UNIT#u-1")
    for action in extra or []:
        plan.add("Put", action)
    return plan


def _get(client: Any, keys: Any) -> dict[str, Any] | None:
    item = client.get_item(TableName=keys.table_name, Key={"pk": {"S": keys.pk}, "sk": {"S": keys.sk}}).get("Item")
    return item if isinstance(item, dict) else None


# ---------------------------------------------------------------------------
# Fingerprint normalization
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_field_order_never_changes_the_fingerprint(self) -> None:
        a = normalized_fingerprint({"x": 1, "y": "two"})
        b = normalized_fingerprint({"y": "two", "x": 1})
        assert a == b

    def test_padding_is_normalized_but_internal_whitespace_is_content(self) -> None:
        """Trimmed text is one request regardless of client padding, but two
        different strings never alias: "Ann  Marie" and "Ann Marie" are
        different display names and must fingerprint differently."""
        assert normalized_fingerprint({"city": "  Austin  "}) == normalized_fingerprint({"city": "Austin"})
        assert normalized_fingerprint({"name": "Ann  Marie"}) != normalized_fingerprint({"name": "Ann Marie"})

    def test_explicit_null_is_distinct_from_omitted_unless_the_caller_drops_nulls(self) -> None:
        """Default: an explicit null is a different request from an omitted key
        (for updates, omitted = leave unchanged while null = clear the field).
        Create-shaped payloads opt in with drop_none=True, because GraphQL
        equates an omitted optional argument with an explicit null on a create,
        and a retry that drops an unset optional argument must still replay."""
        assert normalized_fingerprint({"a": 1, "b": None}) != normalized_fingerprint({"a": 1})
        assert normalized_fingerprint({"a": 1, "b": None}, drop_none=True) == normalized_fingerprint(
            {"a": 1}, drop_none=True
        )

    def test_null_valued_mapping_stays_distinguishable_from_an_empty_one(self) -> None:
        assert normalized_fingerprint({"b": None}) != normalized_fingerprint({})

    def test_integral_floats_match_ints_and_meaningful_changes_differ(self) -> None:
        assert normalized_fingerprint({"q": 2}) == normalized_fingerprint({"q": 2.0})
        assert normalized_fingerprint({"q": 2}) != normalized_fingerprint({"q": 3})
        assert normalized_fingerprint({"v": True}) != normalized_fingerprint({"v": "True"})

    def test_nested_structures_are_canonicalized(self) -> None:
        assert normalized_fingerprint({"lines": [{"b": 1, "a": 2}]}) == normalized_fingerprint(
            {"lines": [{"a": 2, "b": 1}]}
        )
        assert normalized_fingerprint({"lines": [{"a": 1}, {"a": 2}]}) != normalized_fingerprint(
            {"lines": [{"a": 2}, {"a": 1}]}
        )

    def test_algorithm_prefix_is_carried(self) -> None:
        """A later normalization change must be a visible migration, not a silent
        marker invalidation mid-flight."""
        assert normalized_fingerprint(_payload()).startswith("sha256:")

    def test_a_null_inside_a_list_is_still_a_value(self) -> None:
        """Nulls are only droppable as mapping values (GraphQL argument shape);
        inside a list they are elements, so a list of one null must not collapse
        to an empty list."""
        assert normalized_fingerprint({"a": [None]}) != normalized_fingerprint({"a": []})

    def test_non_finite_floats_and_exotic_types_are_rejected_not_coerced(self) -> None:
        with pytest.raises(AppError) as exc:
            normalized_fingerprint({"v": {"x"}})
        assert exc.value.error_code == ErrorCode.INVALID_INPUT
        with pytest.raises(AppError) as exc:
            normalized_fingerprint({"v": float("nan")})
        assert exc.value.error_code == ErrorCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# Marker key contract (data model §8.9)
# ---------------------------------------------------------------------------


class TestMarkerKeys:
    def test_key_carries_actor_operation_and_scope(self) -> None:
        keys = _keys()
        # '#' inside a segment is escaped ('%23'), so the actor segment
        # ACCOUNT#alex renders as ACCOUNT%23alex and cannot blur into the
        # operation/scope boundaries.
        assert keys.pk == f"IDEM#ACCOUNT%23alex#createUnit#{BOOTSTRAP_SCOPE}"
        assert keys.sk == "IDEM#k-1"

    @pytest.mark.parametrize(
        ("scope", "operation"),
        [
            (BOOTSTRAP_SCOPE, "createUnit"),
            ("UNIT#u-1", "updateUnit"),
            ("INVITE#abcdefghABCDEFGH", "redeemUnitInvite"),
            ("JC2K7Q", "joinUnitCampaign"),
        ],
    )
    def test_resource_scope_contract(self, scope: str, operation: str) -> None:
        """unitId when one exists, inviteCode for redemption (durable after the
        invite row is deleted), joinCode for a Campaign join, and the fixed
        bootstrap scope for Unit creation."""
        keys = _keys(operation=operation, scope=scope)
        # '#' is escaped inside segments, so a scope that itself carries the
        # delimiter cannot blur the segment boundaries.
        assert keys.pk.endswith(f"{operation}#{scope.replace('#', '%23')}")

    def test_hash_delimiter_is_escaped_inside_partition_key_segments(self) -> None:
        """actor/operation/scope tuples that differ only in where the '#' falls
        must not assemble to the same partition key."""
        joined = marker_partition_key("A#B", "op", "scope")
        assert joined == "IDEM#A%23B#op#scope"
        assert marker_partition_key("A", "B#op", "scope") != joined
        assert marker_partition_key("A", "op", "B#scope") != joined

    def test_assembled_partition_key_is_capped_at_the_dynamodb_limit(self) -> None:
        with pytest.raises(AppError) as exc:
            marker_partition_key("x" * 512, "op", "y" * 512)
        assert exc.value.error_code == ErrorCode.INVALID_INPUT
        # The largest key that fits is still accepted.
        assert marker_partition_key("x" * 500, "op", "y" * 500).startswith("IDEM#")

    def test_another_account_with_the_same_key_gets_its_own_marker(self) -> None:
        """The tenant-authorization guard's marker half: a caller cannot consume
        or replay another caller's idempotency key."""
        mine = _keys(actor="ACCOUNT#alex")
        theirs = _keys(actor="ACCOUNT#morgan")
        assert mine.pk != theirs.pk

    def test_the_same_key_on_two_operations_is_two_markers(self) -> None:
        assert _keys(operation="createUnit").pk != _keys(operation="updateUnit").pk

    @pytest.mark.parametrize("bad", ["", "   ", "x" * 129, "has space", "with\ttab", "sem;colon"])
    def test_idempotency_key_shape_is_validated(self, bad: str) -> None:
        with pytest.raises(AppError) as exc:
            marker_sort_key(bad)
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    @pytest.mark.parametrize("bad", ["", "   ", "x" * 513, "bad scope"])
    def test_scope_shape_is_validated(self, bad: str) -> None:
        with pytest.raises(AppError) as exc:
            marker_partition_key("ACCOUNT#a", "createUnit", bad)
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_non_string_key_and_scope_are_invalid_input(self) -> None:
        """Defensive: a resolver that forwards a GraphQL Int or a list as the key
        or scope fails at the contract boundary instead of producing a marker
        keyed by a repr."""
        with pytest.raises(AppError) as exc:
            marker_sort_key(cast(str, 12))
        assert exc.value.error_code == ErrorCode.INVALID_INPUT
        with pytest.raises(AppError) as exc:
            marker_partition_key("ACCOUNT#a", "createUnit", cast(str, ["UNIT#u-1"]))
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    @pytest.mark.parametrize(
        "shape",
        [
            "019aa3bb-73c2-7b10-9a1e-3c4d5e6f7a8b",  # Cognito sub
            "PROFILE#abc-def-123",
            "INVITE#abcdefghABCDEFGH",
            "kernelworx-units",
        ],
    )
    def test_key_safe_accepts_the_id_forms_the_codebase_produces(self, shape: str) -> None:
        assert marker_sort_key(shape) == f"IDEM#{shape}"


# ---------------------------------------------------------------------------
# Marker survival (seven-day numeric epoch TTL)
# ---------------------------------------------------------------------------


class TestMarkerTtl:
    def test_seven_day_numeric_epoch(self) -> None:
        now = 1_800_000_000
        assert marker_ttl_epoch(now) == now + MARKER_TTL_SECONDS
        assert MARKER_TTL_SECONDS == 7 * 24 * 60 * 60

    def test_ttl_attribute_is_numeric_epoch_seconds_not_an_iso_timestamp(self) -> None:
        """DynamoDB TTL requires a NUMBER; the legacy `invites` table's `expiresAt`
        is a string ISO timestamp, so the distinct attribute name is load-bearing."""
        item = build_marker_item(_keys(), fingerprint="sha256:x", now_epoch=1_800_000_000)
        assert item[MARKER_TTL_ATTRIBUTE] == {"N": str(1_800_000_000 + MARKER_TTL_SECONDS)}
        assert MARKER_TTL_ATTRIBUTE == "expiresAtEpoch"

    def test_live_marker_carries_a_future_ttl(self) -> None:
        with mock_aws():
            client = _client()
            keys = _keys()
            item = build_marker_item(keys, fingerprint="sha256:x")
            client.put_item(TableName=keys.table_name, Item=item)
            stored = _get(client, keys)
            assert stored is not None
            assert int(stored[MARKER_TTL_ATTRIBUTE]["N"]) > int(time.time())

    def test_marker_status_starts_in_flight_and_result_id_is_required(self) -> None:
        item = build_marker_item(_keys(), fingerprint="sha256:x", result_id="UNIT#u-1")
        assert item["status"] == {"S": MARKER_STATUS_IN_FLIGHT}
        assert item["resultId"] == {"S": "UNIT#u-1"}
        assert "resultId" not in build_marker_item(_keys(), fingerprint="sha256:x")


# ---------------------------------------------------------------------------
# Write plan counting (90/91 boundary, §8.10)
# ---------------------------------------------------------------------------


class TestWritePlan:
    def test_budget_is_ninety_actions(self) -> None:
        assert MAX_TRANSACTION_ACTIONS == 90
        assert WritePlan().max_actions == MAX_TRANSACTION_ACTIONS

    def test_exactly_ninety_actions_is_accepted(self) -> None:
        plan = WritePlan()
        for i in range(MAX_TRANSACTION_ACTIONS):
            plan.add("Put", {"TableName": UNITS_TABLE, "Item": {"pk": {"S": "x"}, "sk": {"S": f"k{i}"}}})
        assert plan.action_count == MAX_TRANSACTION_ACTIONS
        assert len(plan.transact_items()) == MAX_TRANSACTION_ACTIONS

    def test_the_ninety_first_action_fails_before_any_write(self) -> None:
        """CONFLICT carrying OPERATION_TOO_LARGE, and the rejection happens while
        staging, so no DynamoDB call is ever made for an oversized plan."""
        plan = WritePlan()
        for i in range(MAX_TRANSACTION_ACTIONS):
            plan.add("Put", {"TableName": UNITS_TABLE, "Item": {"pk": {"S": "x"}, "sk": {"S": f"k{i}"}}})
        with pytest.raises(AppError) as exc:
            plan.add("Put", {"TableName": UNITS_TABLE, "Item": {"pk": {"S": "x"}, "sk": {"S": "overflow"}}})
        assert exc.value.error_code == ErrorCode.CONFLICT
        assert exc.value.details["subcode"] == ErrorCode.OPERATION_TOO_LARGE
        assert exc.value.details["plannedActions"] == MAX_TRANSACTION_ACTIONS + 1
        assert plan.action_count == MAX_TRANSACTION_ACTIONS

    def test_plan_counts_every_action_type_including_conditions_and_marker(self) -> None:
        client = _client_under_mock()
        keys = _keys()
        fingerprint = normalized_fingerprint(_payload())
        runner = IdempotentMutationRunner(client)
        plan = WritePlan()
        runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id="UNIT#u-1")
        plan.add("Put", _unit_put("u-1"))
        plan.add(
            "ConditionCheck",
            {
                "TableName": UNITS_TABLE,
                "Key": {"pk": {"S": "UNIT#u-1"}, "sk": {"S": "METADATA"}},
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": {"#version": "version"},
                "ExpressionAttributeValues": {":expected": {"N": "3"}},
            },
        )
        plan.add("Delete", {"TableName": UNITS_TABLE, "Key": {"pk": {"S": "x"}, "sk": {"S": "y"}}})
        plan.add("Update", {"TableName": UNITS_TABLE, "Key": {"pk": {"S": "x"}, "sk": {"S": "z"}}})
        assert plan.action_count == 5

    def test_unknown_action_and_missing_table_are_invalid_input(self) -> None:
        plan = WritePlan()
        with pytest.raises(AppError) as exc:
            plan.add("Upsert", {"TableName": UNITS_TABLE})
        assert exc.value.error_code == ErrorCode.INVALID_INPUT
        with pytest.raises(AppError) as exc:
            plan.add("Put", {"Item": {}})
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_condition_check_without_a_condition_expression_is_invalid_input(self) -> None:
        """A condition check that cannot fail is not a guard; staging one would
        let a mutation look version-checked while racing freely."""
        plan = WritePlan()
        with pytest.raises(AppError) as exc:
            plan.add("ConditionCheck", {"TableName": UNITS_TABLE, "Key": {"pk": {"S": "x"}, "sk": {"S": "y"}}})
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_plan_reports_the_tables_it_touches_for_iam_scope_review(self) -> None:
        plan = WritePlan()
        plan.add("Put", {"TableName": "other-table", "Item": {"pk": {"S": "x"}}})
        assert plan.tables == frozenset({"other-table"})

    def test_budget_cannot_be_raised_past_the_contract_cap(self) -> None:
        """The 90-action budget is a product contract (data model §8.10), not a
        per-call tuning knob: 91-100 was never an acceptable plan, even though
        DynamoDB's own cap is 100."""
        with pytest.raises(ValueError):
            WritePlan(max_actions=101)
        with pytest.raises(ValueError):
            WritePlan(max_actions=MAX_TRANSACTION_ACTIONS + 1)
        assert WritePlan(max_actions=MAX_TRANSACTION_ACTIONS).max_actions == MAX_TRANSACTION_ACTIONS


def _client_under_mock() -> Any:
    """Staging never calls DynamoDB, so a bare mock proves that."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Marker + transaction execution
# ---------------------------------------------------------------------------


class TestExecute:
    def test_identical_retry_replays_the_original_result_without_new_writes(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            plan = _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")])
            first = runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
            assert first == "UNIT#u-1"
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 2  # marker + unit

            replay_calls: list[str] = []

            def load(result_id: str) -> str:
                replay_calls.append(result_id)
                return f"replayed:{result_id}"

            retry_plan = _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")])
            second = runner.execute(
                keys,
                retry_plan,
                operation="createUnit",
                fingerprint=fingerprint,
                result_id="UNIT#u-1",
                load_result=load,
            )
            assert second == "replayed:UNIT#u-1"
            assert replay_calls == ["UNIT#u-1"]
            # Zero new effect: the duplicate Unit Put never ran (it would have
            # failed its own condition anyway, which is the belt to the marker's
            # braces - both are required so a bug in one cannot double-write).
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 2

    def test_completed_marker_is_flipped_with_the_result_reference(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            plan = _staged_plan(client, keys, fingerprint)
            runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-9")
            stored = _get(client, keys)
            assert stored is not None
            assert stored["status"] == {"S": MARKER_STATUS_COMPLETED}
            assert stored["resultId"] == {"S": "UNIT#u-9"}
            assert stored["fingerprint"] == {"S": fingerprint}

    def test_same_key_different_fingerprint_is_invalid_input_and_writes_nothing(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            first = normalized_fingerprint(_payload())
            runner.execute(
                keys,
                _staged_plan(client, keys, first, extra=[_unit_put("u-1")]),
                operation="createUnit",
                fingerprint=first,
                result_id="UNIT#u-1",
            )
            changed = normalized_fingerprint({**_payload(), "city": "Houston"})
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, changed, operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INVALID_INPUT
            assert exc.value.details["subcode"] == "IDEMPOTENCY_FINGERPRINT_MISMATCH"
            assert _get(client, keys)["fingerprint"] == {"S": first}
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 2

    def test_execute_also_rejects_a_changed_fingerprint_before_staging_anything(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            first = normalized_fingerprint(_payload())
            runner.execute(
                keys,
                _staged_plan(client, keys, first),
                operation="createUnit",
                fingerprint=first,
                result_id="UNIT#u-1",
            )
            changed = normalized_fingerprint({**_payload(), "unitNumber": 99})
            with pytest.raises(AppError) as exc:
                runner.execute(
                    keys,
                    _staged_plan(client, keys, changed),
                    operation="createUnit",
                    fingerprint=changed,
                    result_id="UNIT#u-1",
                    load_result=lambda r: r,
                )
            assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_failed_condition_writes_nothing_at_all(self) -> None:
        """Zero partial write: a business condition that does not hold cancels the
        whole transaction, marker included, and surfaces as CONFLICT."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            # Pre-create the Unit so the create-condition fails.
            client.put_item(TableName=UNITS_TABLE, Item=_unit_put("u-1")["Item"])
            plan = _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")])
            with pytest.raises(AppError) as exc:
                runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
            assert exc.value.error_code == ErrorCode.CONFLICT
            assert _get(client, keys) is None, "the marker must not survive a cancelled transaction"
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 1

    def test_stale_version_condition_check_maps_to_conflict(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys(operation="updateUnit", scope="UNIT#u-1")
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(TableName=UNITS_TABLE, Item=_unit_put("u-1", version=4)["Item"])
            plan = WritePlan()
            runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id="UNIT#u-1")
            plan.add(
                "ConditionCheck",
                {
                    "TableName": UNITS_TABLE,
                    "Key": {"pk": {"S": "UNIT#u-1"}, "sk": {"S": "METADATA"}},
                    "ConditionExpression": "#version = :expected",
                    "ExpressionAttributeNames": {"#version": "version"},
                    "ExpressionAttributeValues": {":expected": {"N": "3"}},
                },
            )
            with pytest.raises(AppError) as exc:
                runner.execute(keys, plan, operation="updateUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
            assert exc.value.error_code == ErrorCode.CONFLICT
            assert _get(client, keys) is None
            assert client.get_item(TableName=UNITS_TABLE, Key={"pk": {"S": "UNIT#u-1"}, "sk": {"S": "METADATA"}})[
                "Item"
            ]["version"] == {"N": "4"}

    def test_concurrent_identical_request_races_and_double_write_is_impossible(self) -> None:
        """The interleaving the pre-check cannot cover: two attempts both read "no
        marker", and the loser's transaction then loses the marker condition. The
        loser surfaces the retryable race code, its business Put never lands, and
        its next attempt replays the winner."""

        class StaleReadClient:
            """Forwards writes to moto but answers the marker read from the moment
            before the winner committed - exactly what a real concurrent reader sees."""

            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def get_item(self, **kwargs: Any) -> dict[str, Any]:
                return {}

            def transact_write_items(self, **kwargs: Any) -> dict[str, Any]:
                return self._inner.transact_write_items(**kwargs)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        with mock_aws():
            client = _client()
            winner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            winner.execute(
                keys,
                _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")]),
                operation="createUnit",
                fingerprint=fingerprint,
                result_id="UNIT#u-1",
            )

            loser = IdempotentMutationRunner(StaleReadClient(client))
            with pytest.raises(AppError) as exc:
                loser.execute(
                    keys,
                    _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")]),
                    operation="createUnit",
                    fingerprint=fingerprint,
                    result_id="UNIT#u-1",
                    backfill_marker=False,
                )
            assert exc.value.error_code == ErrorCode.RESOURCE_BUSY
            assert exc.value.details["subcode"] == "IDEMPOTENCY_KEY_RACE"
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 2, "the loser wrote nothing"

            retry = winner.execute(
                keys,
                _staged_plan(client, keys, fingerprint, extra=[_unit_put("u-1")]),
                operation="createUnit",
                fingerprint=fingerprint,
                result_id="UNIT#u-1",
                load_result=lambda r: f"replayed:{r}",
            )
            assert retry == "replayed:UNIT#u-1"
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 2

    def test_in_flight_marker_with_a_result_reference_still_replays(self) -> None:
        """The marker insert rides inside the transaction, so an in-flight marker
        means the business writes committed and only the status back-fill is
        pending; a retry must not re-run them."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(
                TableName=keys.table_name,
                Item=build_marker_item(keys, fingerprint=fingerprint, result_id="UNIT#u-1"),
            )
            handled, result = runner.replay_or_reject(
                keys, fingerprint, operation="createUnit", load_result=lambda r: f"replayed:{r}"
            )
            assert (handled, result) == (True, "replayed:UNIT#u-1")

    def test_marker_without_a_result_reference_cannot_be_replayed(self) -> None:
        """Caller misuse fails loudly rather than silently re-running a mutation
        whose writes already committed."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(TableName=keys.table_name, Item=build_marker_item(keys, fingerprint=fingerprint))
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, fingerprint, operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_a_result_reference_of_the_wrong_shape_is_not_treated_as_absent(self) -> None:
        """A marker attribute written by a different code path (a number where the
        contract stores a string) must not be silently read as "no result": that
        would take the caller down the re-run path and double-apply the mutation."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(
                TableName=keys.table_name,
                Item={
                    "pk": {"S": keys.pk},
                    "sk": {"S": keys.sk},
                    "fingerprint": {"S": fingerprint},
                    "status": {"S": MARKER_STATUS_COMPLETED},
                    "resultId": {"N": "1"},
                },
            )
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, fingerprint, operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_corrupt_marker_fails_closed(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            client.put_item(
                TableName=keys.table_name,
                Item={"pk": {"S": keys.pk}, "sk": {"S": keys.sk}, "status": {"S": MARKER_STATUS_COMPLETED}},
            )
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, "sha256:x", operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INTERNAL_ERROR
            client.update_item(
                TableName=keys.table_name,
                Key={"pk": {"S": keys.pk}, "sk": {"S": keys.sk}},
                UpdateExpression="SET #f = :f",
                ExpressionAttributeNames={"#f": "fingerprint"},
                ExpressionAttributeValues={":f": {"S": "sha256:x"}},
            )
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, "sha256:x", operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INTERNAL_ERROR

    @pytest.mark.parametrize(
        "item",
        [
            {"status": {"S": MARKER_STATUS_COMPLETED}},  # no fingerprint
            {"fingerprint": "sha256:x", "status": {"S": MARKER_STATUS_COMPLETED}},
            {"fingerprint": {"S": "sha256:x"}, "status": "COMPLETED"},
            {"fingerprint": {"N": "1"}, "status": {"S": MARKER_STATUS_COMPLETED}},
        ],
    )
    def test_a_marker_attribute_of_the_wrong_shape_fails_closed(self, item: dict[str, Any]) -> None:
        """The reader is tested directly because a non-wire attribute value cannot
        even be sent through boto3; a marker carrying one must never be read as
        "no marker", which would re-run a committed mutation."""
        from src.utils.mutations import _marker_from_item

        with pytest.raises(AppError) as exc:
            _marker_from_item({"pk": {"S": "IDEM#a"}, "sk": {"S": "IDEM#k"}, **item})
        assert exc.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_a_well_formed_marker_reads_back_with_its_result_reference(self) -> None:
        from src.utils.mutations import _marker_from_item

        assert _marker_from_item(
            {
                "fingerprint": {"S": "sha256:x"},
                "status": {"S": MARKER_STATUS_COMPLETED},
                "resultId": {"S": "UNIT#u-1"},
            }
        ) == ("sha256:x", MARKER_STATUS_COMPLETED, "UNIT#u-1")

    def test_unknown_marker_status_fails_closed(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(
                TableName=keys.table_name,
                Item={
                    "pk": {"S": keys.pk},
                    "sk": {"S": keys.sk},
                    "fingerprint": {"S": fingerprint},
                    "status": {"S": "WAT"},
                    "resultId": {"S": "UNIT#u-1"},
                },
            )
            with pytest.raises(AppError) as exc:
                runner.replay_or_reject(keys, fingerprint, operation="createUnit", load_result=lambda r: r)
            assert exc.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_empty_plan_is_rejected_before_any_call(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            with pytest.raises(AppError) as exc:
                runner.execute(keys, WritePlan(), operation="createUnit", fingerprint="sha256:x")
            assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_execute_refuses_a_marker_less_plan_and_driving_it_twice_writes_nothing(self) -> None:
        """execute() owns the marker. A plan whose first action is not the
        conditional marker Put must never commit: the old behavior committed the
        business write, then classified the post-commit marker flip's
        ConditionalCheckFailed as CONFLICT - the caller was told the write
        failed, retried, and applied it twice. Driving the refused plan twice
        proves nothing partial landed in between."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            marker_less = WritePlan()
            marker_less.add("Put", _unit_put("u-1"))
            for _ in range(2):
                with pytest.raises(AppError) as exc:
                    runner.execute(
                        keys, marker_less, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1"
                    )
                assert exc.value.error_code == ErrorCode.INVALID_INPUT
                assert client.scan(TableName=UNITS_TABLE)["Count"] == 0, (
                    "a marker-less plan must not commit anything, on any attempt"
                )

    @pytest.mark.parametrize(
        "first_action",
        [
            # Not a Put at all.
            {"Delete": {"TableName": UNITS_TABLE, "Key": {"pk": {"S": "x"}, "sk": {"S": "y"}}}},
            # A Put on a different table - even with the marker's exact key pair.
            {
                "Put": {
                    "TableName": "other-table",
                    "Item": {"pk": {"S": "IDEM#x"}, "sk": {"S": "IDEM#k-1"}},
                    "ConditionExpression": "attribute_not_exists(#pk)",
                }
            },
            # A Put with no item body at all.
            {"Put": {"TableName": UNITS_TABLE, "ConditionExpression": "attribute_not_exists(#pk)"}},
        ],
    )
    def test_the_first_action_must_be_a_put_with_the_marker_key_on_the_marker_table(
        self, first_action: dict[str, Any]
    ) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            plan = WritePlan()
            plan.add(next(iter(first_action)), first_action[next(iter(first_action))])
            # The marker rides second: the parametrized action opens the plan.
            runner.stage_marker(plan, keys, fingerprint=fingerprint, result_id="UNIT#u-1")
            with pytest.raises(AppError) as exc:
                runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
            assert exc.value.error_code == ErrorCode.INVALID_INPUT
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 0

    def test_the_first_action_must_be_the_conditional_marker_put(self) -> None:
        """A marker-shaped Put without its condition, or with a different sort
        key, is not the uniqueness guard either - the plan is refused pre-write.
        A plan whose marker was staged after a business action is likewise
        refused: the marker must open the transaction."""
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            marker_item = build_marker_item(keys, fingerprint=fingerprint, result_id="UNIT#u-1")

            unconditional = WritePlan()
            # The marker's exact key pair, but with NO condition: an
            # unconditional marker Put is not a uniqueness guard.
            unconditional.add("Put", {"TableName": UNITS_TABLE, "Item": marker_item})

            wrong_sort = WritePlan()
            wrong_sort.add(
                "Put",
                {
                    "TableName": UNITS_TABLE,
                    "Item": {**marker_item, "sk": {"S": "IDEM#someone-else"}},
                    "ConditionExpression": "attribute_not_exists(#pk)",
                },
            )

            defeated_guard = WritePlan()
            # The marker's exact key pair, and an attribute_not_exists that is
            # aliased to an attribute no marker item carries: the condition is
            # always true, so it is not an idempotency guard at all.
            defeated_guard.add(
                "Put",
                {
                    "TableName": UNITS_TABLE,
                    "Item": dict(marker_item),
                    "ConditionExpression": "attribute_not_exists(#pk)",
                    "ExpressionAttributeNames": {"#pk": "someNonexistentAttribute"},
                },
            )

            or_defeated_guard = WritePlan()
            # The same class smuggled inside an OR: a real-looking
            # attribute_not_exists token, but the other disjunct is always true,
            # so the whole condition never blocks any insert.
            or_defeated_guard.add(
                "Put",
                {
                    "TableName": UNITS_TABLE,
                    "Item": dict(marker_item),
                    "ConditionExpression": "attribute_not_exists(#real) OR attribute_not_exists(#pk)",
                    "ExpressionAttributeNames": {
                        "#real": "someNonexistentAttribute",
                        "#pk": "pk",
                    },
                },
            )

            inverted_guard = WritePlan()
            # The NOT-inverted shape would block every insert instead of guarding
            # the uniqueness race - also not the guard the contract stages.
            inverted_guard.add(
                "Put",
                {
                    "TableName": UNITS_TABLE,
                    "Item": dict(marker_item),
                    "ConditionExpression": "NOT attribute_not_exists(#pk)",
                    "ExpressionAttributeNames": {"#pk": "pk"},
                },
            )

            business_first = WritePlan()
            business_first.add("Put", _unit_put("u-1"))
            runner.stage_marker(business_first, keys, fingerprint=fingerprint, result_id="UNIT#u-1")

            for plan in (unconditional, wrong_sort, defeated_guard, or_defeated_guard, inverted_guard, business_first):
                with pytest.raises(AppError) as exc:
                    runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
                assert exc.value.error_code == ErrorCode.INVALID_INPUT
            assert client.scan(TableName=UNITS_TABLE)["Count"] == 0

    def test_execute_rechecks_the_final_action_count(self) -> None:
        """The budget cap is re-asserted against the plan that actually reaches
        execute(), so a plan object that did not come out of WritePlan cannot
        bypass the 90-action ceiling (data model §8.10)."""

        class OversizeStub:
            action_count = MAX_TRANSACTION_ACTIONS + 1

            def transact_items(self) -> list[dict[str, Any]]:
                return [{"Put": {"TableName": UNITS_TABLE}}] * (MAX_TRANSACTION_ACTIONS + 1)

        client = MagicMock()
        runner = IdempotentMutationRunner(client)
        with pytest.raises(AppError) as exc:
            runner.execute(
                _keys(),
                cast(WritePlan, OversizeStub()),
                operation="createUnit",
                fingerprint="sha256:x",
                result_id="UNIT#u-1",
            )
        assert exc.value.error_code == ErrorCode.CONFLICT
        assert exc.value.details["subcode"] == ErrorCode.OPERATION_TOO_LARGE
        client.transact_write_items.assert_not_called()

    def test_marker_staging_requires_a_result_id(self) -> None:
        runner = IdempotentMutationRunner(MagicMock())
        with pytest.raises(AppError) as exc:
            runner.stage_marker(WritePlan(), _keys(), fingerprint="sha256:x", result_id="  ")
        assert exc.value.error_code == ErrorCode.INVALID_INPUT

    def test_back_fill_can_be_deferred_by_the_caller(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            runner.execute(
                keys,
                _staged_plan(client, keys, fingerprint),
                operation="createUnit",
                fingerprint=fingerprint,
                result_id="UNIT#u-1",
                backfill_marker=False,
            )
            assert _get(client, keys)["status"] == {"S": MARKER_STATUS_IN_FLIGHT}
            runner.complete_marker(keys, fingerprint=fingerprint, result_id="UNIT#u-1")
            assert _get(client, keys)["status"] == {"S": MARKER_STATUS_COMPLETED}

    def test_back_fill_refuses_to_overwrite_a_different_marker(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            client.put_item(
                TableName=keys.table_name,
                Item=build_marker_item(keys, fingerprint="sha256:other", result_id="UNIT#u-1"),
            )
            with pytest.raises(AppError) as exc:
                runner.complete_marker(keys, fingerprint=fingerprint, result_id="UNIT#u-1")
            assert exc.value.error_code == ErrorCode.CONFLICT

    def test_load_marker_read_is_consistent_and_missing_marker_is_none(self) -> None:
        with mock_aws():
            client = _client()
            runner = IdempotentMutationRunner(client)
            assert runner.load_marker(_keys()) is None
            call = client.get_item

            seen: list[bool] = []

            def spy(**kwargs: Any) -> Any:
                seen.append(bool(kwargs.get("ConsistentRead")))
                return call(**kwargs)

            client.get_item = spy  # type: ignore[method-assign]
            runner.load_marker(_keys())
            assert seen == [True]

    def test_default_runner_uses_a_plain_client_and_writes_wire_form_items(self) -> None:
        """No explicit client means the shared plain-client path (so the
        DYNAMODB_ENDPOINT override is honored).

        The wire-form assertion is the sharp edge: boto3's DynamoDB *service
        resource* attaches its type serializer to ``meta.client``, so a client
        taken from a resource re-encodes the helper's ``{"S": ...}`` values and
        the marker lands as a map. Reading the stored item back in wire form is
        what proves the helper never went through that client.
        """
        with mock_aws():
            client = _client()
            reset_dynamodb_resource()
            runner = IdempotentMutationRunner()
            keys = _keys()
            fingerprint = normalized_fingerprint(_payload())
            plan = _staged_plan(client, keys, fingerprint)
            runner.execute(keys, plan, operation="createUnit", fingerprint=fingerprint, result_id="UNIT#u-1")
            stored = _get(client, keys)
            assert stored is not None
            assert stored["status"] == {"S": MARKER_STATUS_COMPLETED}
            assert stored[MARKER_TTL_ATTRIBUTE]["N"]

    def test_a_resource_derived_client_would_corrupt_the_marker_and_is_not_used(self) -> None:
        """Direct proof of the trap the default path avoids."""
        with mock_aws():
            client = _client()
            resource_client = boto3.resource("dynamodb", region_name="us-east-1").meta.client
            keys = _keys()
            with pytest.raises(ClientError) as exc:
                resource_client.put_item(TableName=UNITS_TABLE, Item=build_marker_item(keys, fingerprint="sha256:x"))
            assert "Type mismatch" in str(exc.value)
            assert _get(client, keys) is None


# ---------------------------------------------------------------------------
# Error classification (CONFLICT vs RESOURCE_BUSY)
# ---------------------------------------------------------------------------


def _client_error(code: str, message: str = "nope", reasons: list[dict[str, Any]] | None = None) -> ClientError:
    response: dict[str, Any] = {"Error": {"Code": code, "Message": message}}
    if reasons is not None:
        response["CancellationReasons"] = reasons
    return ClientError(response, "TransactWriteItems")


class TestErrorClassification:
    def test_cancelled_transaction_is_a_retry_by_re_read_conflict(self) -> None:
        exc = classify_transaction_error(
            _client_error(
                "TransactionCanceledException",
                reasons=[{"Code": "ConditionalCheckFailed", "Message": "The conditional request failed"}],
            ),
            operation="createUnit",
        )
        assert exc.error_code == ErrorCode.CONFLICT

    def test_transaction_without_reasons_still_classifies(self) -> None:
        exc = classify_transaction_error(_client_error("TransactionCanceledException"), operation="createUnit")
        assert exc.error_code == ErrorCode.CONFLICT

    def test_non_list_cancellation_reasons_are_ignored(self) -> None:
        error = ClientError({"Error": {"Code": "TransactionCanceledException"}, "CancellationReasons": "junk"}, "x")
        assert classify_transaction_error(error, operation="createUnit").error_code == ErrorCode.CONFLICT

    @pytest.mark.parametrize(
        "code",
        ["ProvisionedThroughputExceededException", "ThrottlingException", "TooManyRequestsException"],
    )
    def test_throttling_is_the_retryable_resource_busy(self, code: str) -> None:
        assert classify_transaction_error(_client_error(code), operation="createUnit").error_code == (
            ErrorCode.RESOURCE_BUSY
        )

    @pytest.mark.parametrize("code", ["ThrottlingError", "ProvisionedThroughputExceeded"])
    def test_throttling_reported_as_a_per_item_cancellation_reason_is_resource_busy(self, code: str) -> None:
        exc = classify_transaction_error(
            _client_error(
                "TransactionCanceledException",
                reasons=[
                    {"Code": "ConditionalCheckFailed", "Message": "m"},
                    {"Code": code, "Message": "m"},
                ],
            ),
            operation="createUnit",
        )
        assert exc.error_code == ErrorCode.RESOURCE_BUSY

    def test_a_non_retryable_per_item_cancellation_stays_a_conflict(self) -> None:
        """A failed condition (not throttling, not contention) is the non-retryable
        re-read-and-recompute verdict."""
        assert (
            classify_transaction_error(
                _client_error(
                    "TransactionCanceledException",
                    reasons=[{"Code": "ConditionalCheckFailed", "Message": "m"}],
                ),
                operation="createUnit",
            ).error_code
            == ErrorCode.CONFLICT
        )

    def test_per_item_transaction_conflict_is_retryable_contention(self) -> None:
        """Per-item TransactionConflict is the same retryable contention family as
        throttling (spec 3.3): resend after a backoff, not re-read/recompute."""
        exc = classify_transaction_error(
            _client_error(
                "TransactionCanceledException",
                reasons=[{"Code": "TransactionConflict", "Message": "m"}],
            ),
            operation="createUnit",
        )
        assert exc.error_code == ErrorCode.RESOURCE_BUSY

    def test_top_level_transaction_conflict_is_retryable_contention(self) -> None:
        assert classify_transaction_error(
            _client_error("TransactionConflictException"), operation="createUnit"
        ).error_code == (ErrorCode.RESOURCE_BUSY)

    @pytest.mark.parametrize(
        "message",
        [
            "Transaction request cannot include more than 100 items",
            "Transaction request cannot include multiple operations on one item",
        ],
    )
    def test_oversize_or_duplicate_transaction_maps_to_operation_too_large(self, message: str) -> None:
        exc = classify_transaction_error(_client_error("ValidationException", message=message), operation="createUnit")
        assert exc.error_code == ErrorCode.CONFLICT
        assert exc.details["subcode"] == ErrorCode.OPERATION_TOO_LARGE

    def test_an_unrelated_validation_exception_stays_internal(self) -> None:
        """Only the size/duplicate shape is remapped; an unexpected
        ValidationException is still an internal failure, not a client conflict."""
        assert classify_transaction_error(
            _client_error("ValidationException", message="One or more parameter values were invalid"),
            operation="createUnit",
        ).error_code == (ErrorCode.INTERNAL_ERROR)

    def test_transaction_in_progress_is_the_retryable_resource_busy(self) -> None:
        assert classify_transaction_error(
            _client_error("TransactionInProgressException"), operation="createUnit"
        ).error_code == (ErrorCode.RESOURCE_BUSY)

    def test_a_transport_fault_is_retryable_not_a_service_verdict(self) -> None:
        exc = EndpointConnectionError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com")
        assert classify_transaction_error(exc, operation="createUnit").error_code == ErrorCode.RESOURCE_BUSY

    def test_permission_and_internal_faults_are_not_retryable(self) -> None:
        assert classify_transaction_error(
            _client_error("AccessDeniedException"), operation="createUnit"
        ).error_code == (ErrorCode.INTERNAL_ERROR)
        assert classify_transaction_error(RuntimeError("boom"), operation="createUnit").error_code == (
            ErrorCode.INTERNAL_ERROR
        )

    def test_marker_condition_rejection_is_detected_from_the_old_marker_item(self) -> None:
        """DynamoDB never says which condition failed; the marker's ALL_OLD return
        is the only discriminator, and it must not misfire on a business-row
        cancellation."""
        marker_reason = {
            "Code": "ConditionalCheckFailed",
            "Message": "The conditional request failed",
            "Item": {
                "pk": {"S": "IDEM#ACCOUNT#alex#createUnit#BOOTSTRAP"},
                "sk": {"S": "IDEM#k-1"},
                "fingerprint": {"S": "sha256:x"},
                "status": {"S": MARKER_STATUS_IN_FLIGHT},
            },
        }
        error = _client_error("TransactionCanceledException", reasons=[marker_reason])
        from src.utils.mutations import _is_marker_condition_rejection

        assert _is_marker_condition_rejection(error) is True
        business_reason = {
            "Code": "ConditionalCheckFailed",
            "Message": "The conditional request failed",
            "Item": {"pk": {"S": "UNIT#u-1"}, "sk": {"S": "METADATA"}, "version": {"N": "4"}},
        }
        assert (
            _is_marker_condition_rejection(_client_error("TransactionCanceledException", reasons=[business_reason]))
            is False
        )
        assert _is_marker_condition_rejection(RuntimeError("boom")) is False
        assert _is_marker_condition_rejection(_client_error("AccessDeniedException")) is False

    def test_a_throttle_inside_the_transaction_surfaces_as_resource_busy(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = _client_error("ThrottlingException")
        runner = IdempotentMutationRunner(client)
        keys = _keys()
        plan = _staged_plan(client, keys, "sha256:x")
        with pytest.raises(AppError) as exc:
            runner.execute(keys, plan, operation="createUnit", fingerprint="sha256:x", result_id="UNIT#u-1")
        assert exc.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_a_marker_load_fault_is_classified_too(self) -> None:
        client = MagicMock()
        client.get_item.side_effect = _client_error("ThrottlingException")
        runner = IdempotentMutationRunner(client)
        with pytest.raises(AppError) as exc:
            runner.load_marker(_keys())
        assert exc.value.error_code == ErrorCode.RESOURCE_BUSY
