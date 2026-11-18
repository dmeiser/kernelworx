"""Unit tests for delete_campaign_orders Lambda handler and deletion helpers."""

from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, patch

import pytest

from src.handlers.campaign_operations import (
    _fulfillment_version_delete_condition,
    _order_fulfillment_version,
    _query_order_keys_for_campaign,
    _verify_campaign_deleted,
    _verify_order_keys_deleted,
    batch_delete_keys,
    delete_campaign_orders,
    delete_fulfillments_for_orders,
    delete_order_and_fulfillments,
    delete_orders_for_campaign,
    fulfillment_keys_for_orders,
)
from src.utils.errors import AppError, ErrorCode
from src.utils.order_fulfillment_models import fulfillment_version_condition
from tests.unit.fixtures import batch_delete_table, unprocessed_batches


class TestDeleteCampaignOrders:
    """Tests for delete_campaign_orders Lambda handler."""

    _OWNER_SUB = "owner-sub-001"

    @staticmethod
    def _seed_owned_campaign(
        profiles_table: Any,
        campaigns_table: Any,
        profile_id: str,
        campaign_id: str,
        owner_sub: str,
    ) -> None:
        """Seed a profile owned by owner_sub and a campaign on that profile."""
        profiles_table.put_item(
            Item={
                "ownerAccountId": f"ACCOUNT#{owner_sub}",
                "profileId": profile_id,
                "profileName": f"Profile {profile_id}",
            }
        )
        campaigns_table.put_item(
            Item={
                "profileId": profile_id,
                "campaignId": campaign_id,
                "campaignName": "Test Campaign",
                "campaignYear": 2024,
            }
        )

    @staticmethod
    def _event(campaign_id: str, caller_sub: str) -> Dict[str, Any]:
        return {
            "arguments": {"campaignId": campaign_id},
            "identity": {"sub": caller_sub},
        }

    def test_delete_campaign_orders_success(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting all orders for a campaign owned by the caller."""
        campaign_id = "CAMPAIGN#campaign-123"
        profile_id = "PROFILE#profile-123"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        for i in range(5):
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": f"ORDER#{i}",
                    "customerName": f"Customer {i}",
                    "totalAmount": Decimal("10.0"),
                }
            )

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 5}
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 0

    def test_a_fulfillment_landing_mid_delete_leaves_the_order_for_the_retry(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """ARCH-1 (round-3 review): the sweep/delete window cannot orphan, and cannot strand.

        The batch form deleted every Order first and swept their history afterwards. If
        that second sweep failed, the retry read no Orders, returned `deletedCount: 0`,
        and the records that survived the failure were orphaned for good — the cascade had
        no durable record of which partitions still needed cleaning, because it enumerated
        work by reading Orders.

        Each Order is now deleted by a write pinned to the ``fulfillmentVersion`` the
        cascade read. A real fulfillment commits its row and moves that version in one
        transaction, so a fulfillment landing during the sweep fails the pin: the record
        stays attached to an Order that is still present, the cascade stops, and the next
        run finds the same Order and finishes the job.
        """
        campaign_id = "CAMPAIGN#campaign-race"
        profile_id = "PROFILE#profile-race"
        order_key = {"campaignId": campaign_id, "orderId": "ORDER#1"}
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer 1",
                "totalAmount": Decimal("4.0"),
            }
        )

        real_sweep = delete_fulfillments_for_orders
        injections = {"count": 0}

        def sweep_then_fulfill(order_ids: List[str], *, logger: Any = None) -> int:
            """The real sweep, then the fulfillment that commits in the window behind it."""
            deleted = real_sweep(order_ids, logger=logger)
            if injections["count"] == 0:
                injections["count"] = 1
                order_fulfillments_table.put_item(
                    Item={
                        "pk": "ORDER#1",
                        "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#late",
                        "entityType": "OrderFulfillment",
                        "orderId": "ORDER#1",
                        "campaignId": campaign_id,
                        "fulfillmentId": "late",
                        "quantity": 1,
                        "createdAt": "2024-10-02T00:00:00+00:00",
                    }
                )
                # A fulfillment is one transaction: the row above AND the Order's version.
                orders_table.update_item(
                    Key=order_key,
                    UpdateExpression="SET fulfillmentVersion = :v",
                    ExpressionAttributeValues={":v": 1},
                )
            return deleted

        with patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", side_effect=sweep_then_fulfill):
            first = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert first["__isError"] is True, f"the pinned delete must fail: {first!r}"
        assert first["errorCode"] == "CONFLICT"
        # The Order survived, and that row is the durable record of unfinished cleanup —
        # the thing the batch form could not offer once the Orders were gone.
        assert orders_table.get_item(Key=order_key).get("Item") is not None, "the pinned delete removed a changed Order"
        assert len(order_fulfillments_table.scan()["Items"]) == 1, "the arriving record was deleted or orphaned"

        # The retry reads the same Order, sweeps its history, and completes.
        second = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert second == {"deletedCount": 1}
        assert orders_table.scan()["Items"] == [], "the retry left the Order behind"
        assert order_fulfillments_table.scan()["Items"] == [], "the retry left fulfillment history orphaned"

    def test_a_sweep_that_cannot_finish_leaves_the_order_and_its_history_in_place(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """A failed history sweep is not a license to delete the parent.

        `_verify_fulfillment_keys_deleted` refuses while swept records survive the batch,
        and the refusal happens before the Order's delete, so the whole partition is still
        there for the next run — no Order is ever removed on top of records the cascade
        could not reach.
        """
        campaign_id = "CAMPAIGN#campaign-sweep-fails"
        profile_id = "PROFILE#profile-sweep-fails"
        order_key = {"campaignId": campaign_id, "orderId": "ORDER#1"}
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer 1",
                "totalAmount": Decimal("4.0"),
            }
        )
        order_fulfillments_table.put_item(
            Item={
                "pk": "ORDER#1",
                "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#ful-1",
                "entityType": "OrderFulfillment",
                "orderId": "ORDER#1",
                "campaignId": campaign_id,
                "fulfillmentId": "ful-1",
                "quantity": 2,
                "createdAt": "2024-10-02T00:00:00+00:00",
            }
        )

        real_sweep = delete_fulfillments_for_orders
        attempts = {"count": 0}

        def fail_the_first_sweep(order_ids: List[str], *, logger: Any = None) -> int:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to delete data. Please retry.")
            return real_sweep(order_ids, logger=logger)

        with patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", side_effect=fail_the_first_sweep):
            first = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)
            assert first["errorCode"] == "RESOURCE_BUSY"
            assert orders_table.get_item(Key=order_key).get("Item") is not None
            assert len(order_fulfillments_table.scan()["Items"]) == 1

            second = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert second == {"deletedCount": 1}
        assert orders_table.scan()["Items"] == []
        assert order_fulfillments_table.scan()["Items"] == []

    def test_delete_campaign_orders_chunks_batches(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting more than 25 orders chunks deletes into batches."""
        campaign_id = "CAMPAIGN#campaign-many"
        profile_id = "PROFILE#profile-many"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        for i in range(30):
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": f"ORDER#{i}",
                    "customerName": f"Customer {i}",
                    "totalAmount": Decimal("10.0"),
                }
            )

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 30}
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 0

    def test_delete_campaign_orders_empty(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test deleting orders for a campaign with no orders."""
        campaign_id = "CAMPAIGN#campaign-empty"
        profile_id = "PROFILE#profile-empty"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 0}

    def test_delete_campaign_orders_unprefixed_id(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that an unprefixed campaignId is normalized."""
        campaign_id = "CAMPAIGN#campaign-raw"
        profile_id = "PROFILE#profile-raw"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer",
                "totalAmount": Decimal("10.0"),
            }
        )

        result = delete_campaign_orders(self._event("campaign-raw", self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 1}

    def test_delete_campaign_orders_missing_campaign_id(
        self,
        lambda_context: Any,
    ) -> None:
        """Test that missing campaignId returns an error payload."""
        event = {"arguments": {}, "identity": {"sub": self._OWNER_SUB}}
        result = delete_campaign_orders(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_delete_campaign_orders_missing_identity(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that missing caller identity raises UNAUTHORIZED."""
        campaign_id = "CAMPAIGN#no-identity"
        profile_id = "PROFILE#no-identity"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        result = delete_campaign_orders({"arguments": {"campaignId": campaign_id}}, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_delete_campaign_orders_campaign_not_found(
        self,
        campaigns_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that deleting a nonexistent campaign returns NOT_FOUND."""
        result = delete_campaign_orders(self._event("CAMPAIGN#ghost", self._OWNER_SUB), lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_delete_campaign_orders_campaign_missing_profile_id(
        self,
        lambda_context: Any,
    ) -> None:
        """Test that a campaign row with no profileId raises NOT_FOUND."""
        campaign_id = "CAMPAIGN#no-profile"
        with patch(
            "src.handlers.campaign_operations._get_campaign_by_id",
            return_value={"campaignId": campaign_id, "campaignName": "Orphan"},
        ):
            result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_delete_campaign_orders_denied_non_owner(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that a non-owner caller without a WRITE share is denied."""
        campaign_id = "CAMPAIGN#owned-by-other"
        profile_id = "PROFILE#owned-by-other"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer",
                "totalAmount": Decimal("10.0"),
            }
        )

        result = delete_campaign_orders(self._event(campaign_id, "intruder-sub"), lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        remaining = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(remaining.get("Items", [])) == 1

    def test_delete_campaign_orders_only_targets_requested_campaign(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that orders for other campaigns are not deleted."""
        target_campaign = "CAMPAIGN#target"
        other_campaign = "CAMPAIGN#other"
        target_profile = "PROFILE#target"
        other_profile = "PROFILE#other"
        self._seed_owned_campaign(profiles_table, campaigns_table, target_profile, target_campaign, self._OWNER_SUB)
        self._seed_owned_campaign(profiles_table, campaigns_table, other_profile, other_campaign, self._OWNER_SUB)

        orders_table.put_item(
            Item={
                "campaignId": target_campaign,
                "orderId": "ORDER#target",
                "customerName": "Target",
                "totalAmount": Decimal("10.0"),
            }
        )
        orders_table.put_item(
            Item={
                "campaignId": other_campaign,
                "orderId": "ORDER#other",
                "customerName": "Other",
                "totalAmount": Decimal("10.0"),
            }
        )

        result = delete_campaign_orders(self._event(target_campaign, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 1}
        assert (
            orders_table.get_item(Key={"campaignId": other_campaign, "orderId": "ORDER#other"}).get("Item") is not None
        )

    def test_delete_campaign_orders_unexpected_error(
        self,
        campaigns_table: Any,
        profiles_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that unexpected errors are wrapped in an INTERNAL_ERROR AppError."""
        campaign_id = "CAMPAIGN#any"
        profile_id = "PROFILE#any"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)

        with patch("src.handlers.campaign_operations.delete_orders_for_campaign") as mock_delete:
            mock_delete.side_effect = RuntimeError("unexpected failure")

            result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete campaign orders" in result["message"]

    def test_delete_campaign_orders_throttled_raises_resource_busy(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that throttling during delete_campaign_orders returns RESOURCE_BUSY."""
        from botocore.exceptions import ClientError

        campaign_id = "CAMPAIGN#throttled"
        profile_id = "PROFILE#throttled"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": "ORDER#1",
                "customerName": "Customer 1",
                "totalAmount": Decimal("10.0"),
            }
        )

        with patch("src.handlers.campaign_operations.tables.orders.meta.client.delete_item") as mock_delete:
            error_response = {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}}
            mock_delete.side_effect = ClientError(error_response, "DeleteItem")

            result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
            # A throttled parent delete leaves the Order where the next run can find it.
            assert (
                orders_table.get_item(Key={"campaignId": campaign_id, "orderId": "ORDER#1"}).get("Item") is not None
            ), "a failed delete removed the Order it could not clean"

    def test_delete_campaign_orders_verifies_order_id_gsi(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
        order_fulfillments_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that deleted orders are no longer visible in the orderId-index GSI."""
        campaign_id = "CAMPAIGN#gsi-verify"
        profile_id = "PROFILE#gsi-verify"
        self._seed_owned_campaign(profiles_table, campaigns_table, profile_id, campaign_id, self._OWNER_SUB)
        order_ids = [f"ORDER#{i}" for i in range(3)]
        for order_id in order_ids:
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": order_id,
                    "customerName": "Customer",
                    "totalAmount": Decimal("10.0"),
                }
            )

        result = delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert result == {"deletedCount": 3}
        for order_id in order_ids:
            gsi_response = orders_table.query(
                IndexName="orderId-index",
                KeyConditionExpression="orderId = :oid",
                ExpressionAttributeValues={":oid": order_id},
            )
            assert len(gsi_response.get("Items", [])) == 0


class TestVerifyOrderKeysDeleted:
    """Tests for the base-table order deletion verification helper."""

    def test_returns_when_all_order_keys_are_absent(self) -> None:
        """Test that verification succeeds when every deleted order is gone."""
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {"kernelworx-orders-v2-ue1-dev": []}}

        order_keys = [
            {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#2"},
        ]

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource):
            _verify_order_keys_deleted(order_keys)

        mock_resource.batch_get_item.assert_called_once()
        req = mock_resource.batch_get_item.call_args.kwargs["RequestItems"]["kernelworx-orders-v2-ue1-dev"]
        assert req["ConsistentRead"] is True
        assert req["Keys"] == order_keys

    def test_chunks_order_keys_at_100_keys_per_call(self) -> None:
        """Test that keys are split into chunks of at most 100 per BatchGetItem call."""
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {"kernelworx-orders-v2-ue1-dev": []}}

        order_keys = [{"campaignId": "CAMPAIGN#batch", "orderId": f"ORDER#{i}"} for i in range(250)]

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource):
            _verify_order_keys_deleted(order_keys)

        assert mock_resource.batch_get_item.call_count == 3
        sizes = [
            len(call.kwargs["RequestItems"]["kernelworx-orders-v2-ue1-dev"]["Keys"])
            for call in mock_resource.batch_get_item.call_args_list
        ]
        assert sizes == [100, 100, 50]
        for call in mock_resource.batch_get_item.call_args_list:
            assert call.kwargs["RequestItems"]["kernelworx-orders-v2-ue1-dev"]["ConsistentRead"] is True

    def test_retries_unprocessed_keys_with_backoff(self) -> None:
        """Test that unprocessed keys are retried with backoff and succeed."""
        table_name = "kernelworx-orders-v2-ue1-dev"
        mock_resource = MagicMock()
        unprocessed_key = {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#2"}
        mock_resource.batch_get_item.side_effect = [
            {"Responses": {table_name: []}, "UnprocessedKeys": {table_name: {"Keys": [unprocessed_key]}}},
            {"Responses": {table_name: []}, "UnprocessedKeys": {}},
        ]

        order_keys = [
            {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#1"},
            unprocessed_key,
        ]

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            patch("src.utils.dynamodb.time.sleep") as mock_sleep,
        ):
            _verify_order_keys_deleted(order_keys)

        assert mock_resource.batch_get_item.call_count == 2
        assert mock_sleep.call_count == 1

    def test_raises_when_unprocessed_keys_exceed_retry_cap(self) -> None:
        """Test that persistent unprocessed keys raise RESOURCE_BUSY after retry cap."""
        table_name = "kernelworx-orders-v2-ue1-dev"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {table_name: []},
            "UnprocessedKeys": {table_name: {"Keys": [{"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#1"}]}},
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            patch("src.utils.dynamodb.time.sleep"),
            pytest.raises(AppError) as exc_info,
        ):
            _verify_order_keys_deleted([{"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#1"}])

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_raises_when_an_order_key_persists(self) -> None:
        """Test that verification raises INTERNAL_ERROR when an order persists."""
        table_name = "kernelworx-orders-v2-ue1-dev"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {table_name: [{"campaignId": "CAMPAIGN#x", "orderId": "ORDER#2"}]}
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            pytest.raises(AppError) as exc_info,
        ):
            _verify_order_keys_deleted(
                [
                    {"campaignId": "CAMPAIGN#x", "orderId": "ORDER#1"},
                    {"campaignId": "CAMPAIGN#x", "orderId": "ORDER#2"},
                ]
            )

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to delete order" in str(exc_info.value.message)

    def test_empty_keys_makes_no_api_call(self) -> None:
        """Test that empty order keys list performs no API call."""
        mock_resource = MagicMock()
        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource):
            _verify_order_keys_deleted([])

        mock_resource.batch_get_item.assert_not_called()

    def test_uses_custom_table_name_from_table_attribute(self) -> None:
        """Test that custom table name is read from tables.orders.name when set."""
        mock_table = MagicMock()
        mock_table.name = "custom-orders-table"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {"custom-orders-table": []}}

        with (
            patch("src.handlers.campaign_operations.tables") as mock_tables,
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
        ):
            mock_tables.orders = mock_table
            _verify_order_keys_deleted([{"campaignId": "C", "orderId": "O1"}])

        assert "custom-orders-table" in mock_resource.batch_get_item.call_args.kwargs["RequestItems"]

    def test_falls_back_to_env_var_when_table_has_no_name(self, monkeypatch: Any) -> None:
        """Test fallback to environment variable when table object lacks name."""
        monkeypatch.setenv("ORDERS_TABLE_NAME", "env-orders-table")
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {"env-orders-table": []}}

        with (
            patch("src.handlers.campaign_operations.tables") as mock_tables,
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
        ):
            mock_tables.orders = object()
            _verify_order_keys_deleted([{"campaignId": "C", "orderId": "O1"}])

        assert "env-orders-table" in mock_resource.batch_get_item.call_args.kwargs["RequestItems"]


class TestVerifyCampaignDeleted:
    """Tests for the base-table campaign deletion verification helper."""

    def test_returns_when_campaign_is_absent(self) -> None:
        """Test that verification succeeds when the deleted campaign is gone."""
        table_name = "kernelworx-campaigns-v2-ue1-dev"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {table_name: []}}

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource):
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#gone")

        mock_resource.batch_get_item.assert_called_once()
        req = mock_resource.batch_get_item.call_args.kwargs["RequestItems"][table_name]
        assert req["ConsistentRead"] is True
        assert req["Keys"] == [{"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#gone"}]

    def test_retries_unprocessed_keys_with_backoff(self) -> None:
        """Test that unprocessed keys are retried with backoff and succeed."""
        table_name = "kernelworx-campaigns-v2-ue1-dev"
        mock_resource = MagicMock()
        unprocessed_key = {"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#retry"}
        mock_resource.batch_get_item.side_effect = [
            {"Responses": {table_name: []}, "UnprocessedKeys": {table_name: {"Keys": [unprocessed_key]}}},
            {"Responses": {table_name: []}, "UnprocessedKeys": {}},
        ]

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            patch("src.utils.dynamodb.time.sleep") as mock_sleep,
        ):
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#retry")

        assert mock_resource.batch_get_item.call_count == 2
        assert mock_sleep.call_count == 1

    def test_raises_when_unprocessed_keys_exceed_retry_cap(self) -> None:
        """Test that persistent unprocessed keys raise RESOURCE_BUSY after retry cap."""
        table_name = "kernelworx-campaigns-v2-ue1-dev"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {table_name: []},
            "UnprocessedKeys": {table_name: {"Keys": [{"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#busy"}]}},
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            patch("src.utils.dynamodb.time.sleep"),
            pytest.raises(AppError) as exc_info,
        ):
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#busy")

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_raises_when_campaign_persists(self) -> None:
        """Test that verification raises INTERNAL_ERROR when the campaign persists."""
        table_name = "kernelworx-campaigns-v2-ue1-dev"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {
            "Responses": {table_name: [{"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#stuck"}]}
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
            pytest.raises(AppError) as exc_info,
        ):
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#stuck")

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to delete campaign" in str(exc_info.value.message)

    def test_uses_custom_table_name_from_table_attribute(self) -> None:
        """Test that custom table name is read from tables.campaigns.name when set."""
        mock_table = MagicMock()
        mock_table.name = "custom-campaigns-table"
        mock_resource = MagicMock()
        mock_resource.batch_get_item.return_value = {"Responses": {"custom-campaigns-table": []}}

        with (
            patch("src.handlers.campaign_operations.tables") as mock_tables,
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=mock_resource),
        ):
            mock_tables.campaigns = mock_table
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#gone")

        assert "custom-campaigns-table" in mock_resource.batch_get_item.call_args.kwargs["RequestItems"]


class TestQueryOrderKeysForCampaign:
    """Tests for the order key query helper."""

    @patch("src.handlers.campaign_operations.query_all_items")
    def test_queries_orders_by_campaign_id(self, mock_query: MagicMock) -> None:
        """Test that _query_order_keys_for_campaign queries the orders table."""
        mock_query.return_value = [
            {"campaignId": "CAMPAIGN#q", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#q", "orderId": "ORDER#2"},
        ]

        result = _query_order_keys_for_campaign("CAMPAIGN#q")

        assert len(result) == 2
        mock_query.assert_called_once()
        call_args = mock_query.call_args.args
        assert call_args[1]["KeyConditionExpression"] == "campaignId = :cid"
        assert call_args[1]["ExpressionAttributeValues"] == {":cid": "CAMPAIGN#q"}


class TestDeleteOrderAndFulfillments:
    """The per-Order lifecycle: strong read, history sweep, version-pinned parent delete."""

    @staticmethod
    def _tables(order_item: Dict[str, Any] | None) -> MagicMock:
        mock_tables = MagicMock()
        mock_tables.orders.get_item.return_value = {"Item": order_item} if order_item is not None else {}
        mock_tables.orders.name = "kernelworx-orders-v2-ue1-dev"
        return mock_tables

    def test_reads_the_order_strongly_and_pins_the_delete_to_the_version_it_read(self) -> None:
        order_item = {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1", "fulfillmentVersion": Decimal("3")}
        mock_tables = self._tables(order_item)
        with (
            patch("src.handlers.campaign_operations.tables", mock_tables),
            patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", return_value=2) as mock_sweep,
        ):
            deleted, records = delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1")

        assert (deleted, records) == (True, 2)
        # The version read must precede the sweep: a version read afterwards would already
        # count a fulfillment the sweep never saw, and the delete would orphan its row.
        mock_tables.orders.get_item.assert_called_once_with(
            Key={"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"}, ConsistentRead=True
        )
        mock_sweep.assert_called_once_with(["ORDER#1"], logger=ANY)
        kwargs = mock_tables.orders.delete_item.call_args.kwargs
        assert kwargs["Key"] == {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"}
        assert (
            kwargs["ConditionExpression"]
            == "#fulfillmentVersion = :expectedFulfillmentVersion AND attribute_exists(#orderId)"
        )
        assert kwargs["ExpressionAttributeValues"] == {":expectedFulfillmentVersion": 3}

    def test_a_pre_wave_3_order_that_carries_no_version_is_pinned_at_zero(self) -> None:
        order_item = {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"}
        mock_tables = self._tables(order_item)
        with (
            patch("src.handlers.campaign_operations.tables", mock_tables),
            patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", return_value=0),
        ):
            assert delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1") == (True, 0)

        condition = mock_tables.orders.delete_item.call_args.kwargs["ConditionExpression"]
        assert condition == (
            "(attribute_not_exists(#fulfillmentVersion) OR #fulfillmentVersion = :expectedFulfillmentVersion) "
            "AND attribute_exists(#orderId)"
        )

    def test_an_order_that_is_already_gone_issues_no_sweep_and_no_write(self) -> None:
        # Whoever removed it was pinned too, so its history went with it: a second sweep
        # would be a read of an empty partition for nothing.
        mock_tables = self._tables(None)
        with patch("src.handlers.campaign_operations.tables", mock_tables) as mock_tables_arg:
            with patch("src.handlers.campaign_operations.delete_fulfillments_for_orders") as mock_sweep:
                assert delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1") == (False, 0)

        assert mock_tables_arg is mock_tables
        mock_sweep.assert_not_called()
        mock_tables.orders.delete_item.assert_not_called()

    def test_a_sweep_that_refuses_stops_before_the_parent_delete(self) -> None:
        order_item = {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1", "fulfillmentVersion": Decimal("1")}
        mock_tables = self._tables(order_item)
        with (
            patch("src.handlers.campaign_operations.tables", mock_tables),
            patch(
                "src.handlers.campaign_operations.delete_fulfillments_for_orders",
                side_effect=AppError(ErrorCode.CONFLICT, "1 fulfillment record(s) are still present"),
            ),
        ):
            with pytest.raises(AppError) as excinfo:
                delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1")

        assert excinfo.value.error_code == ErrorCode.CONFLICT
        mock_tables.orders.delete_item.assert_not_called()

    def test_a_failed_pin_is_a_retryable_conflict_that_names_the_unfinished_order(self) -> None:
        from botocore.exceptions import ClientError

        order_item = {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1", "fulfillmentVersion": Decimal("2")}
        mock_tables = self._tables(order_item)
        mock_tables.orders.delete_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "The conditional check failed."}},
            "DeleteItem",
        )
        mock_logger = MagicMock()
        with (
            patch("src.handlers.campaign_operations.tables", mock_tables),
            patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", return_value=0),
            pytest.raises(AppError) as excinfo,
        ):
            delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1", logger=mock_logger)

        assert excinfo.value.error_code == ErrorCode.CONFLICT
        assert "ORDER#1 was fulfilled while its delete was in flight" in excinfo.value.message
        mock_logger.warning.assert_called_once()

    def test_a_throttled_order_delete_keeps_the_shared_transient_verdict(self) -> None:
        from botocore.exceptions import ClientError

        order_item = {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1", "fulfillmentVersion": Decimal("2")}
        mock_tables = self._tables(order_item)
        mock_tables.orders.delete_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}},
            "DeleteItem",
        )
        with (
            patch("src.handlers.campaign_operations.tables", mock_tables),
            patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", return_value=0),
            pytest.raises(AppError) as excinfo,
        ):
            delete_order_and_fulfillments("CAMPAIGN#c1", "ORDER#1")

        assert excinfo.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_the_version_the_delete_pins_is_the_version_the_row_carries(self) -> None:
        assert _order_fulfillment_version({"fulfillmentVersion": Decimal("7")}) == 7
        assert _order_fulfillment_version({}) == 0


class TestDeleteConditionMatchesTheFulfillmentWriteOwner:
    """The delete pin and the fulfillment write must be the same guard.

    `campaign_operations` spells the guard locally rather than importing
    `order_fulfillment_models`, because that module drags `inventory` and `units` into the
    import closure of Lambdas that never read them -- a cost the closure gate
    (`test_lambda_table_env_closure.py`) would force the deployments to pay. Duplication
    is only safe if it is checked, so this compares the two spellings attribute for
    attribute. The one intended difference is encoding: the owner feeds the low-level
    client and returns `wire_value` form, this one feeds the resource client.
    """

    @staticmethod
    def _wire_to_python(values: Dict[str, Any]) -> Dict[str, int]:
        return {name: int(value["N"]) for name, value in values.items()}

    def test_every_version_spells_the_same_guard(self) -> None:
        for version in (0, 1, 2, 99):
            owner = fulfillment_version_condition(version)
            cascade = _fulfillment_version_delete_condition(version)

            assert cascade["ConditionExpression"] == owner["ConditionExpression"], f"version {version}"
            assert cascade["ExpressionAttributeNames"] == owner["ExpressionAttributeNames"], f"version {version}"
            assert self._wire_to_python(owner["ExpressionAttributeValues"]) == cascade["ExpressionAttributeValues"], (
                f"version {version}"
            )

    def test_the_guard_still_requires_the_row_itself(self) -> None:
        # The parenthesised version test alone would pass against a MISSING item, which is
        # how an unfulfilled Order deleted mid-flight gets recreated as a partial row.
        for version in (0, 3):
            assert "attribute_exists(#orderId)" in _fulfillment_version_delete_condition(version)["ConditionExpression"]


class TestBatchDeleteKeys:
    """Tests for batch_delete_keys helper."""

    def test_empty_keys_returns_zero(self) -> None:
        """Test that an empty keys list returns 0 without calling BatchWriteItem."""
        mock_table = batch_delete_table()
        count = batch_delete_keys(mock_table, [])
        assert count == 0
        mock_table.meta.client.batch_write_item.assert_not_called()

    def test_duplicate_keys_are_deleted_once(self) -> None:
        """Test that duplicate keys collapse to a single DeleteRequest."""
        mock_table = batch_delete_table()
        keys = [{"pk": "1", "sk": "a"}, {"pk": "1", "sk": "b"}, {"pk": "1", "sk": "a"}]

        count = batch_delete_keys(mock_table, keys, ["pk", "sk"])

        assert count == 2
        sent = mock_table.meta.client.batch_write_item.call_args.kwargs["RequestItems"]["test-table"]
        assert [request["DeleteRequest"]["Key"] for request in sent] == [{"pk": "1", "sk": "a"}, {"pk": "1", "sk": "b"}]

    def test_unprocessed_items_are_retried_until_they_clear(self) -> None:
        """Test that UnprocessedItems drive a bounded retry that eventually succeeds."""
        mock_table = batch_delete_table()
        keys = [{"id": "1"}]
        requests = [{"DeleteRequest": {"Key": {"id": "1"}}}]
        unprocessed_batches(mock_table, requests, attempts=2)

        with patch("src.handlers.campaign_operations.time.sleep") as mock_sleep:
            count = batch_delete_keys(mock_table, keys)

        assert count == 1
        assert mock_table.meta.client.batch_write_item.call_count == 3
        assert [call.args[0] for call in mock_sleep.call_args_list] == [0.05, 0.1]

    def test_unprocessed_items_at_the_attempt_cap_raise_resource_busy(self) -> None:
        """Test that items still unprocessed at the cap surface as RESOURCE_BUSY, not a spin."""
        from src.handlers.campaign_operations import MAX_BATCH_WRITE_ATTEMPTS

        mock_table = batch_delete_table()
        keys = [{"id": "1"}]
        requests = [{"DeleteRequest": {"Key": {"id": "1"}}}]
        unprocessed_batches(mock_table, requests, attempts=MAX_BATCH_WRITE_ATTEMPTS)

        with patch("src.handlers.campaign_operations.time.sleep") as mock_sleep:
            with pytest.raises(AppError) as exc_info:
                batch_delete_keys(mock_table, keys)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert mock_table.meta.client.batch_write_item.call_count == MAX_BATCH_WRITE_ATTEMPTS
        assert mock_sleep.call_count == MAX_BATCH_WRITE_ATTEMPTS - 1

    def test_throttling_raises_resource_busy(self) -> None:
        """Test that persistent throttling raises AppError with RESOURCE_BUSY."""
        from botocore.exceptions import ClientError

        mock_table = batch_delete_table()
        mock_table.meta.client.batch_write_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}},
            "BatchWriteItem",
        )
        keys = [{"id": "1"}]
        with pytest.raises(AppError) as exc_info:
            batch_delete_keys(mock_table, keys)
        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_non_throttling_client_error_raises_internal_error(self) -> None:
        """Test that non-throttling ClientError raises AppError with INTERNAL_ERROR."""
        from botocore.exceptions import ClientError

        mock_table = batch_delete_table()
        mock_table.meta.client.batch_write_item.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
            "BatchWriteItem",
        )
        keys = [{"id": "1"}]
        with pytest.raises(AppError) as exc_info:
            batch_delete_keys(mock_table, keys)
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_unexpected_exception_raises_internal_error(self) -> None:
        """Test that unexpected non-ClientError raises AppError with INTERNAL_ERROR."""
        mock_table = batch_delete_table()
        mock_table.meta.client.batch_write_item.side_effect = RuntimeError("network crash")
        keys = [{"id": "1"}]
        with pytest.raises(AppError) as exc_info:
            batch_delete_keys(mock_table, keys)
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_custom_logger_used(self) -> None:
        """Test that a custom logger is invoked during deletion."""
        mock_table = batch_delete_table()
        mock_logger = MagicMock()

        keys = [{"id": "1"}, {"id": "2"}]
        count = batch_delete_keys(mock_table, keys, logger=mock_logger)
        assert count == 2
        mock_logger.info.assert_called_once()


class TestDeleteOrdersForCampaign:
    """Tests for delete_orders_for_campaign helper."""

    def test_each_order_is_swept_then_deleted_pinned_and_the_set_is_verified(self) -> None:
        """One lifecycle per Order, and the campaign verifies the whole set afterwards."""
        orders = [
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#2"},
        ]
        mock_logger = MagicMock()
        with (
            patch("src.handlers.campaign_operations._query_order_keys_for_campaign", return_value=orders),
            patch(
                "src.handlers.campaign_operations.delete_order_and_fulfillments",
                return_value=(True, 3),
            ) as mock_delete,
            patch("src.handlers.campaign_operations._verify_order_keys_deleted") as mock_verify,
        ):
            count = delete_orders_for_campaign("CAMPAIGN#c1", logger=mock_logger)

        assert count == 2
        assert [call.args for call in mock_delete.call_args_list] == [
            ("CAMPAIGN#c1", "ORDER#1"),
            ("CAMPAIGN#c1", "ORDER#2"),
        ]
        for call in mock_delete.call_args_list:
            assert call.kwargs == {"logger": mock_logger}
        mock_verify.assert_called_once_with(orders)
        mock_logger.info.assert_called_once()

    def test_an_order_another_path_already_removed_is_not_counted_as_deleted(self) -> None:
        orders = [
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#2"},
        ]
        with (
            patch("src.handlers.campaign_operations._query_order_keys_for_campaign", return_value=orders),
            patch(
                "src.handlers.campaign_operations.delete_order_and_fulfillments", side_effect=[(False, 0), (True, 0)]
            ),
            patch("src.handlers.campaign_operations._verify_order_keys_deleted"),
        ):
            assert delete_orders_for_campaign("CAMPAIGN#c1") == 1

    def test_a_pinned_delete_that_fails_stops_the_campaign_delete(self) -> None:
        """ARCH-1 (round-3 review): a failed lifecycle is a stop, not a completed delete.

        The cascade enumerates its work by reading Orders, so it must not walk past an
        Order whose cleanup failed: the surviving Order is the only record that its
        partition still needs sweeping.
        """
        orders = [
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#c1", "orderId": "ORDER#2"},
        ]
        with (
            patch("src.handlers.campaign_operations._query_order_keys_for_campaign", return_value=orders),
            patch(
                "src.handlers.campaign_operations.delete_order_and_fulfillments",
                side_effect=AppError(
                    ErrorCode.CONFLICT,
                    "ORDER#1 was fulfilled while its delete was in flight; nothing was deleted for it, re-read and retry",
                ),
            ) as mock_delete,
            patch("src.handlers.campaign_operations._verify_order_keys_deleted") as mock_verify,
        ):
            with pytest.raises(AppError) as excinfo:
                delete_orders_for_campaign("CAMPAIGN#c1")

        assert excinfo.value.error_code == ErrorCode.CONFLICT
        assert mock_delete.call_count == 1, "the cascade stops at the Order it could not clean up"
        mock_verify.assert_not_called()

    def test_no_orders_means_no_partitions_left_to_sweep(self) -> None:
        """The empty answer is evidence now, not a guess.

        Every path that removes an Order row (this cascade, the profile cascade, the
        AppSync deleteOrder step) pins the delete to the Order's fulfillmentVersion and
        sweeps the partition in the same step, so an absent Order row cannot have
        surviving history under it.
        """
        with (
            patch("src.handlers.campaign_operations._query_order_keys_for_campaign", return_value=[]),
            patch("src.handlers.campaign_operations.delete_order_and_fulfillments") as mock_delete,
        ):
            assert delete_orders_for_campaign("CAMPAIGN#empty") == 0

        mock_delete.assert_not_called()


class TestFulfillmentKeysForOrders:
    """ARCH-1: the delete sweep reads only key pairs, from the base table, per Order."""

    def test_one_strongly_consistent_partition_read_per_order(self) -> None:
        """Test that each Order is read from the base table with ConsistentRead."""
        row = {"pk": "ORDER#1", "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#ful-1"}
        with (
            patch("src.handlers.campaign_operations.tables"),
            patch("src.handlers.campaign_operations.query_all_items", return_value=[row]) as mock_query,
        ):
            keys = fulfillment_keys_for_orders(["ORDER#1", "ORDER#2"])

        assert keys == [{"pk": "ORDER#1", "sk": row["sk"]}] * 2
        assert mock_query.call_count == 2
        for call in mock_query.call_args_list:
            params = call.args[1]
            assert params["ConsistentRead"] is True
            assert params["KeyConditionExpression"] == "pk = :pk"

    def test_a_row_without_its_key_pair_is_never_handed_to_the_batch_writer(self) -> None:
        """Test that a malformed row is skipped rather than sent as an incomplete key.

        DynamoDB rejects the whole BatchWriteItem for one key missing `sk`, which would
        strand every sibling record of the sweep, so the sweep keeps only complete pairs.
        """
        rows = [{"pk": "ORDER#1"}, {"sk": "FULFILLMENT#x"}, "not-a-row", {"pk": "ORDER#1", "sk": "FULFILLMENT#a"}]
        with (
            patch("src.handlers.campaign_operations.tables"),
            patch("src.handlers.campaign_operations.query_all_items", return_value=rows),
        ):
            keys = fulfillment_keys_for_orders(["ORDER#1"])

        assert keys == [{"pk": "ORDER#1", "sk": "FULFILLMENT#a"}]


class TestDeleteFulfillmentsForOrders:
    """ARCH-1: the sweep deletes the children, then refuses to call it done while any remain."""

    def test_orders_without_history_touch_nothing(self) -> None:
        """Test that an empty sweep does not open a batch writer."""
        with (
            patch("src.handlers.campaign_operations.tables"),
            patch("src.handlers.campaign_operations.query_all_items", return_value=[]),
            patch("src.handlers.campaign_operations.batch_delete_keys") as mock_delete,
        ):
            assert delete_fulfillments_for_orders(["ORDER#1"]) == 0

        mock_delete.assert_not_called()

    def test_the_children_are_deleted_and_counted(self) -> None:
        """Test the sweep -> batch delete -> verify path reports the deleted count."""
        keys = [{"pk": "ORDER#1", "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#ful-1"}]
        mock_logger = MagicMock()
        with (
            patch("src.handlers.campaign_operations.tables"),
            patch("src.handlers.campaign_operations.query_all_items", side_effect=[keys, []]) as mock_query,
            patch("src.handlers.campaign_operations.batch_delete_keys", return_value=1) as mock_delete,
        ):
            assert delete_fulfillments_for_orders(["ORDER#1"], logger=mock_logger) == 1

        assert mock_query.call_count == 2, "the sweep verifies the rows it deleted are gone"
        mock_delete.assert_called_once()
        assert mock_delete.call_args.args[1] == keys
        assert mock_delete.call_args.args[2] == ["pk", "sk"]
        mock_logger.info.assert_called_once()

    def test_history_that_survives_the_batch_delete_stops_the_cascade(self) -> None:
        """Test that a record still present after the batch delete is a hard stop.

        Silent survival here is the same defect one level down from the one being fixed:
        the cascade would report success while leaving behind an orphan no surface can
        reverse or read, next to an inventory movement that already moved stock.
        """
        keys = [{"pk": "ORDER#1", "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#ful-1"}]
        with (
            patch("src.handlers.campaign_operations.tables"),
            patch("src.handlers.campaign_operations.query_all_items", side_effect=[keys, keys]),
            patch("src.handlers.campaign_operations.batch_delete_keys", return_value=1),
        ):
            with pytest.raises(AppError) as excinfo:
                delete_fulfillments_for_orders(["ORDER#1"])

        assert excinfo.value.error_code == ErrorCode.CONFLICT
        assert "1 fulfillment record(s) are still present" in excinfo.value.message
