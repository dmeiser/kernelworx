"""
Tests for Show & Sell transaction + idempotency helpers in utils.dynamodb.

Covers the wave-1 convention (docs/investigations/show-sell-idempotency-convention.md):
preflight cap, client-side duplicate-key rejection, cancellation
classification, bounded throttling retries, and the marker item shape.
"""

import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.utils.dynamodb import (
    IDEM_TTL_SECONDS,
    MAX_RACE_RETRIES,
    MAX_TRANSACT_ITEMS,
    TransactionCancelledError,
    TransactionDuplicateKeyError,
    TransactionThrottledError,
    execute_transaction,
    idem_expiry_epoch,
    idem_item_key,
    new_marker_item,
    transaction_item_key,
)

TABLE = "kernelworx-units-ue1-dev"
KEY: Dict[str, Any] = {"unitId": "unit-1", "itemKey": "METADATA"}


def _put(table: str = TABLE, item: Dict[str, Any] = KEY) -> Dict[str, Any]:
    return {"Put": {"TableName": table, "Item": dict(item)}}


def _client_error(code: str, *, cancellation_reasons: Any = None) -> ClientError:
    response: Dict[str, Any] = {"Error": {"Code": code, "Message": code}}
    if cancellation_reasons is not None:
        response["CancellationReasons"] = cancellation_reasons
    return ClientError(response, "TransactWriteItems")


class TestTransactionItemKey:
    def test_put_uses_item(self) -> None:
        assert transaction_item_key(_put()) == (TABLE, tuple(sorted(KEY.items())))

    def test_update_uses_key(self) -> None:
        entry = {"Update": {"TableName": TABLE, "Key": dict(KEY)}}
        assert transaction_item_key(entry) == (TABLE, tuple(sorted(KEY.items())))

    def test_condition_check_uses_key(self) -> None:
        entry = {"ConditionCheck": {"TableName": TABLE, "Key": dict(KEY)}}
        assert transaction_item_key(entry) == (TABLE, tuple(sorted(KEY.items())))


class TestExecuteTransaction:
    def test_success_passes_plan(self) -> None:
        client = MagicMock()
        plan = [_put()]
        execute_transaction(plan, client=client)
        client.transact_write_items.assert_called_once_with(TransactItems=plan)

    def test_plan_over_cap_rejected_before_call(self) -> None:
        client = MagicMock()
        items = [_put(item={"unitId": f"unit-{i}", "itemKey": "METADATA"}) for i in range(MAX_TRANSACT_ITEMS + 1)]
        with pytest.raises(ValueError, match="cap"):
            execute_transaction(items, client=client)
        client.transact_write_items.assert_not_called()

    def test_plan_at_cap_accepted(self) -> None:
        client = MagicMock()
        items = [_put(item={"unitId": f"unit-{i}", "itemKey": "METADATA"}) for i in range(MAX_TRANSACT_ITEMS)]
        execute_transaction(items, client=client)
        client.transact_write_items.assert_called_once()

    def test_duplicate_key_rejected_before_call(self) -> None:
        client = MagicMock()
        with pytest.raises(TransactionDuplicateKeyError):
            execute_transaction([_put(), _put()], client=client)
        client.transact_write_items.assert_not_called()

    def test_same_key_different_tables_allowed(self) -> None:
        client = MagicMock()
        execute_transaction([_put(), _put(table="kernelworx-inventory-ue1-dev")], client=client)
        client.transact_write_items.assert_called_once()

    def test_cancellation_classifies_failed_indexes(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = _client_error(
            "TransactionCanceledException",
            cancellation_reasons=[{"Code": "None"}, {"Code": "ConditionalCheckFailed"}],
        )
        with pytest.raises(TransactionCancelledError) as exc_info:
            execute_transaction([_put(), _put(table="kernelworx-inventory-ue1-dev")], client=client)
        assert exc_info.value.failed_indexes == [1]

    def test_cancellation_without_reasons_marks_all(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = _client_error("TransactionCanceledException")
        with pytest.raises(TransactionCancelledError) as exc_info:
            execute_transaction([_put()], client=client)
        assert exc_info.value.failed_indexes == [0]

    def test_throttle_retries_then_succeeds(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = [
            _client_error("ProvisionedThroughputExceededException"),
            None,
        ]
        with patch.object(time, "sleep") as sleep_mock:
            execute_transaction([_put()], client=client)
        assert client.transact_write_items.call_count == 2
        sleep_mock.assert_called_once_with(0.05)

    def test_throttle_exhaustion_raises_throttled(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = _client_error("ThrottlingException")
        with patch.object(time, "sleep"):
            with pytest.raises(TransactionThrottledError) as exc_info:
                execute_transaction([_put()], client=client, max_retries=2)
        assert client.transact_write_items.call_count == 3  # initial + 2 retries
        assert "2 retries" in str(exc_info.value)

    def test_non_transient_client_error_propagates(self) -> None:
        client = MagicMock()
        client.transact_write_items.side_effect = _client_error("AccessDeniedException")
        with pytest.raises(ClientError):
            execute_transaction([_put()], client=client)


class TestIdempotencyHelpers:
    def test_marker_item_key_layout(self) -> None:
        assert idem_item_key("createUnit", "key-1") == "IDEM#createUnit#key-1"

    def test_expiry_is_seven_days(self) -> None:
        assert idem_expiry_epoch(1_000_000) == 1_000_000 + IDEM_TTL_SECONDS
        assert IDEM_TTL_SECONDS == 7 * 24 * 3600

    def test_marker_item_shape(self) -> None:
        marker = new_marker_item(scope="createUnit", marker_key="key-1", fingerprint="fp-9", now_epoch=5_000_000)
        assert marker["itemKey"] == "IDEM#createUnit#key-1"
        assert marker["idemFingerprint"] == "fp-9"
        assert marker["idemCommittedAtEpoch"] == 5_000_000
        assert marker["expiresAtEpoch"] == 5_000_000 + IDEM_TTL_SECONDS
        assert "idemResult" not in marker

    def test_marker_item_carries_result_when_given(self) -> None:
        result: Dict[str, Any] = {"unit": {"unitId": "unit-1"}}
        marker = new_marker_item(
            scope="createUnit", marker_key="key-1", fingerprint="fp-9", now_epoch=5_000_000, result=result
        )
        assert marker["idemResult"] == result

    def test_default_retry_ceiling_matches_convention(self) -> None:
        assert MAX_RACE_RETRIES == 3
