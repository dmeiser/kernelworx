"""Unit tests for delete_profile_orders_cascade Lambda handler."""

from unittest.mock import MagicMock, patch

import pytest

from src.handlers.delete_profile_orders_cascade import lambda_handler


class TestDeleteProfileOrdersCascade:
    """Tests for cascade order deletion during profile deletion."""

    def test_delete_no_orders_returns_zero(self) -> None:
        """Test that when there are no orders, zero is returned."""
        mock_orders_table = MagicMock()
        mock_orders_table.query.return_value = {"Items": []}

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {
                "campaignsToDelete": [
                    {"campaignId": "campaign-1"},
                    {"campaignId": "campaign-2"},
                ]
            },
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 0
            assert mock_orders_table.query.call_count == 2

    def test_delete_single_order(self) -> None:
        """Test deleting a single order from a single campaign."""
        mock_orders_table = MagicMock()
        mock_orders_table.query.return_value = {
            "Items": [
                {"campaignId": "campaign-1", "orderId": "order-1"},
            ]
        }
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 1
            mock_batch_writer.delete_item.assert_called_once_with(
                Key={"campaignId": "campaign-1", "orderId": "order-1"}
            )

    def test_delete_multiple_orders_single_campaign(self) -> None:
        """Test deleting multiple orders from a single campaign."""
        mock_orders_table = MagicMock()
        mock_orders_table.query.return_value = {
            "Items": [
                {"campaignId": "campaign-1", "orderId": "order-1"},
                {"campaignId": "campaign-1", "orderId": "order-2"},
                {"campaignId": "campaign-1", "orderId": "order-3"},
            ]
        }
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 3
            assert mock_batch_writer.delete_item.call_count == 3

    def test_delete_orders_multiple_campaigns(self) -> None:
        """Test deleting orders from multiple campaigns."""
        mock_orders_table = MagicMock()
        # First campaign: 2 orders, second campaign: 3 orders
        mock_orders_table.query.side_effect = [
            {
                "Items": [
                    {"campaignId": "campaign-1", "orderId": "order-1"},
                    {"campaignId": "campaign-1", "orderId": "order-2"},
                ]
            },
            {
                "Items": [
                    {"campaignId": "campaign-2", "orderId": "order-3"},
                    {"campaignId": "campaign-2", "orderId": "order-4"},
                    {"campaignId": "campaign-2", "orderId": "order-5"},
                ]
            },
        ]
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {
                "campaignsToDelete": [
                    {"campaignId": "campaign-1"},
                    {"campaignId": "campaign-2"},
                ]
            },
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 5
            assert mock_batch_writer.delete_item.call_count == 5

    def test_delete_handles_batch_size_limit(self) -> None:
        """Test that batch writes are split into chunks of 25 or fewer."""
        # Create 50 orders (should require 2 batches)
        mock_orders_table = MagicMock()
        items = [{"campaignId": "campaign-1", "orderId": f"order-{i}"} for i in range(1, 51)]
        mock_orders_table.query.return_value = {"Items": items}
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 50
            assert mock_batch_writer.delete_item.call_count == 50

    def test_pagination_handles_multiple_query_pages(self) -> None:
        """Test that pagination correctly handles multiple pages of query results."""
        # First page has 25 items, second page has 25 items
        first_page_items = [{"campaignId": "campaign-1", "orderId": f"order-{i}"} for i in range(1, 26)]
        second_page_items = [{"campaignId": "campaign-1", "orderId": f"order-{i}"} for i in range(26, 51)]

        mock_orders_table = MagicMock()
        # First call returns first page with LastEvaluatedKey
        # Second call returns second page with no LastEvaluatedKey (end of data)
        mock_orders_table.query.side_effect = [
            {"Items": first_page_items, "LastEvaluatedKey": {"campaignId": "campaign-1", "orderId": "order-25"}},
            {"Items": second_page_items},  # No LastEvaluatedKey = final page
        ]
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            # Should have deleted all 50 items across both pages
            assert result["ordersDeleted"] == 50
            # Query should have been called twice (once per page)
            assert mock_orders_table.query.call_count == 2
            # Verify second query call includes ExclusiveStartKey
            second_call_kwargs = mock_orders_table.query.call_args_list[1][1]
            assert "ExclusiveStartKey" in second_call_kwargs

    def test_empty_campaigns_no_batch_writer_call(self) -> None:
        """Test that empty campaigns list doesn't invoke batch_writer at all."""
        mock_orders_table = MagicMock()
        # Ensure query returns empty items
        mock_orders_table.query.return_value = {"Items": []}

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            # Should return 0 when campaign has no orders
            assert result["ordersDeleted"] == 0
            # batch_writer should not be called since there are no orders to delete
            mock_orders_table.batch_writer.assert_not_called()

    def test_missing_profile_id_raises_error(self) -> None:
        """Test that missing profileId raises ValueError."""
        event = {"arguments": {}, "stash": {"campaignsToDelete": []}}

        with pytest.raises(ValueError, match="profileId is required"):
            lambda_handler(event, None)

    def test_empty_campaigns_list(self) -> None:
        """Test that empty campaigns list results in zero orders deleted."""
        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": []},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = MagicMock()

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 0

    def test_missing_campaign_id_skipped(self) -> None:
        """Test that campaigns without campaignId are skipped gracefully."""
        mock_orders_table = MagicMock()

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": None}, {"campaignId": ""}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            assert result["ordersDeleted"] == 0
            # query should not be called for invalid campaigns
            mock_orders_table.query.assert_not_called()

    def test_query_error_continues_with_next_campaign(self) -> None:
        """Test that query errors don't prevent processing other campaigns."""
        mock_orders_table = MagicMock()
        # First campaign fails, second succeeds
        mock_orders_table.query.side_effect = [
            Exception("Query failed"),
            {
                "Items": [
                    {"campaignId": "campaign-2", "orderId": "order-1"},
                ]
            },
        ]
        mock_batch_writer = MagicMock()
        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {
                "campaignsToDelete": [
                    {"campaignId": "campaign-1"},
                    {"campaignId": "campaign-2"},
                ]
            },
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            result = lambda_handler(event, None)

            # Should still delete the 1 order from the second campaign
            assert result["ordersDeleted"] == 1

    def test_batch_write_error_continues_with_next_batch(self) -> None:
        """Test that batch write errors don't prevent processing other batches."""
        # Create 50 orders to trigger 2 batches
        mock_orders_table = MagicMock()
        items = [{"campaignId": "campaign-1", "orderId": f"order-{i}"} for i in range(1, 51)]
        mock_orders_table.query.return_value = {"Items": items}

        # First batch succeeds, second batch fails on its first item
        mock_batch_writer = MagicMock()
        mock_batch_writer.delete_item.side_effect = (
            [None] * 25
            + [
                Exception("Batch write failed"),
            ]
            + [None] * 24
        )

        mock_orders_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_orders_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        event = {
            "arguments": {"profileId": "profile-123"},
            "stash": {"campaignsToDelete": [{"campaignId": "campaign-1"}]},
        }

        with patch("src.handlers.delete_profile_orders_cascade.tables") as mock_tables:
            mock_tables.orders = mock_orders_table

            # Should not raise, should return count from successful batch
            result = lambda_handler(event, None)

            # First batch succeeded (25 items), second batch failed but handler continues
            assert result["ordersDeleted"] == 25
