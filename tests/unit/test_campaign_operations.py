"""Unit tests for delete_campaign_orders Lambda handler and deletion helpers."""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.campaign_operations import (
    _delete_order_keys,
    _query_order_keys_for_campaign,
    _verify_campaign_deleted,
    _verify_order_keys_deleted,
    delete_campaign_orders,
)
from src.utils.errors import AppError, ErrorCode


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

    def test_delete_campaign_orders_chunks_batches(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
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
        """Test that missing campaignId raises an error."""
        event = {"arguments": {}, "identity": {"sub": self._OWNER_SUB}}
        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

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

        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders({"arguments": {"campaignId": campaign_id}}, lambda_context)

        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_delete_campaign_orders_campaign_not_found(
        self,
        campaigns_table: Any,
        lambda_context: Any,
    ) -> None:
        """Test that deleting a nonexistent campaign raises NOT_FOUND."""
        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(self._event("CAMPAIGN#ghost", self._OWNER_SUB), lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

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
            with pytest.raises(AppError) as exc_info:
                delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_delete_campaign_orders_denied_non_owner(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
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

        with pytest.raises(AppError) as exc_info:
            delete_campaign_orders(self._event(campaign_id, "intruder-sub"), lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
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

        with patch("src.handlers.campaign_operations._delete_orders_for_campaign") as mock_delete:
            mock_delete.side_effect = RuntimeError("unexpected failure")

            with pytest.raises(AppError) as exc_info:
                delete_campaign_orders(self._event(campaign_id, self._OWNER_SUB), lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete campaign orders" in exc_info.value.message

    def test_delete_campaign_orders_verifies_order_id_gsi(
        self,
        orders_table: Any,
        campaigns_table: Any,
        profiles_table: Any,
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
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        order_keys = [
            {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#1"},
            {"campaignId": "CAMPAIGN#batch", "orderId": "ORDER#2"},
        ]

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.orders = mock_table
            _verify_order_keys_deleted(order_keys)

        assert mock_table.get_item.call_count == 2
        for call, key in zip(mock_table.get_item.call_args_list, order_keys):
            assert call.kwargs["Key"] == {"campaignId": key["campaignId"], "orderId": key["orderId"]}
            assert call.kwargs["ConsistentRead"] is True

    def test_raises_when_an_order_key_persists(self) -> None:
        """Test that verification raises INTERNAL_ERROR when an order persists."""
        mock_table = MagicMock()
        mock_table.get_item.side_effect = [{}, {"Item": {"campaignId": "CAMPAIGN#x", "orderId": "ORDER#2"}}]

        with (
            patch("src.handlers.campaign_operations.tables") as mock_tables,
            pytest.raises(AppError) as exc_info,
        ):
            mock_tables.orders = mock_table
            _verify_order_keys_deleted(
                [
                    {"campaignId": "CAMPAIGN#x", "orderId": "ORDER#1"},
                    {"campaignId": "CAMPAIGN#x", "orderId": "ORDER#2"},
                ]
            )

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to delete order" in str(exc_info.value.message)


class TestVerifyCampaignDeleted:
    """Tests for the base-table campaign deletion verification helper."""

    def test_returns_when_campaign_is_absent(self) -> None:
        """Test that verification succeeds when the deleted campaign is gone."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.campaigns = mock_table
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#gone")

        mock_table.get_item.assert_called_once_with(
            Key={"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#gone"},
            ConsistentRead=True,
        )

    def test_raises_when_campaign_persists(self) -> None:
        """Test that verification raises INTERNAL_ERROR when the campaign persists."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#stuck"}}

        with (
            patch("src.handlers.campaign_operations.tables") as mock_tables,
            pytest.raises(AppError) as exc_info,
        ):
            mock_tables.campaigns = mock_table
            _verify_campaign_deleted("PROFILE#1", "CAMPAIGN#stuck")

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to delete campaign" in str(exc_info.value.message)


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


class TestDeleteOrderKeys:
    """Tests for the order batch delete helper."""

    def test_deletes_orders_in_batches(self) -> None:
        """Test that _delete_order_keys deletes orders using the batch writer."""
        mock_table = MagicMock()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_writer)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        orders = [{"campaignId": "CAMPAIGN#batch", "orderId": f"ORDER#{i}"} for i in range(3)]

        with patch("src.handlers.campaign_operations.tables") as mock_tables:
            mock_tables.orders = mock_table
            count = _delete_order_keys(orders)

        assert count == 3
        assert mock_writer.delete_item.call_count == 3
