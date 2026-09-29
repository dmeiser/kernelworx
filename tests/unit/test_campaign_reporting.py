"""Unit tests for campaign reporting Lambda handler (unitCampaignKey-index-based implementation)."""

import json
import threading
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.campaign_reporting import (
    _ORDER_QUERY_CONCURRENCY,
    MAX_UNIT_REPORT_CAMPAIGN_QUERIES,
    _build_order_detail,
    _get_accessible_profiles,
    get_unit_report,
)
from src.utils.report_limits import (
    APPSYNC_RESPONSE_LIMIT_BYTES,
    MAX_UNIT_REPORT_GRAPH_BYTES,
    OrderGraphBudget,
    order_graph_bytes,
)


def _orders_by_campaign_query(orders_by_campaign: Dict[str, list[Dict[str, Any]]]) -> Any:
    """Return a DynamoDB ``query`` stand-in that answers per campaignId.

    The handler reads each campaign's orders on its own worker thread, so a
    stand-in keyed by call order would make these tests depend on scheduling.
    Every orders query carries the campaign it reads in its key condition, so the
    stand-in answers from that and stays correct however the reads are scheduled.
    """

    def query(**kwargs: Any) -> Dict[str, Any]:
        campaign_id = kwargs["KeyConditionExpression"].get_expression()["values"][1]
        return {"Items": orders_by_campaign.get(campaign_id, [])}

    return query


class TestGetUnitReport:
    """Tests for get_unit_report Lambda handler using unitCampaignKey-index campaign queries."""

    def _setup_profile_query_mock(
        self, mock_profiles_table: MagicMock, sample_profiles: Dict[str, Dict[str, Any]]
    ) -> None:
        """Helper to mock profiles_table.query for profileId-index lookups."""

        def query_side_effect(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            # Extract profileId from ExpressionAttributeValues
            expr_values = kwargs.get("ExpressionAttributeValues", {})
            profile_id = expr_values.get(":profileId")
            if profile_id and profile_id in sample_profiles:
                return {"Items": [sample_profiles[profile_id]]}
            return {"Items": []}

        mock_profiles_table.query.side_effect = query_side_effect

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for unit report request with city/state."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def sample_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Sample profiles by profileId (for get_item mocking)."""
        return {
            "PROFILE#profile1": {
                "profileId": "PROFILE#profile1",
                "ownerAccountId": "test-account-123",
                "sellerName": "Scout 1",
            },
            "PROFILE#profile2": {
                "profileId": "PROFILE#profile2",
                "ownerAccountId": "test-account-456",
                "sellerName": "Scout 2",
            },
        }

    @pytest.fixture
    def sample_campaigns(self) -> list[Dict[str, Any]]:
        """Sample campaigns returned from unitCampaignKey-index query."""
        return [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            },
            {
                "campaignId": "CAMPAIGN#campaign2",
                "profileId": "PROFILE#profile2",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            },
        ]

    @pytest.fixture
    def sample_orders(self) -> Dict[str, list[Dict[str, Any]]]:
        """Sample orders by campaign."""
        return {
            "CAMPAIGN#campaign1": [
                {
                    "orderId": "ORDER#order1",
                    "campaignId": "CAMPAIGN#campaign1",
                    "customerName": "Customer 1",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("100.00"),
                    "lineItems": [
                        {
                            "productId": "PROD#1",
                            "productName": "Caramel Corn",
                            "quantity": 10,
                            "pricePerUnit": Decimal("10.00"),
                            "subtotal": Decimal("100.00"),
                        }
                    ],
                },
            ],
            "CAMPAIGN#campaign2": [
                {
                    "orderId": "ORDER#order2",
                    "campaignId": "CAMPAIGN#campaign2",
                    "customerName": "Customer 2",
                    "orderDate": "2024-10-02T12:00:00Z",
                    "totalAmount": Decimal("200.00"),
                    "lineItems": [
                        {
                            "productId": "PROD#2",
                            "productName": "Cheese Corn",
                            "quantity": 20,
                            "pricePerUnit": Decimal("10.00"),
                            "subtotal": Decimal("200.00"),
                        }
                    ],
                },
            ],
        }

    def test_get_unit_report_success(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_campaigns: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test successful unit report generation using unitCampaignKey-index."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange - unitCampaignKey-index query returns campaigns directly
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        # Return orders for each campaign
        mock_orders_table.query.side_effect = _orders_by_campaign_query(sample_orders)

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1", "PROFILE#profile2"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert result["unitType"] == "Pack"
            assert result["unitNumber"] == 158
            assert result["campaignName"] == "Fall"
            assert result["campaignYear"] == 2024
            assert len(result["sellers"]) == 2
            assert result["totalSales"] == 300.0
            assert result["totalOrders"] == 2

            # Verify unitCampaignKey-index query was called correctly
            mock_campaigns_table.query.assert_called_once()
            call_kwargs = mock_campaigns_table.query.call_args.kwargs
            assert call_kwargs["IndexName"] == "unitCampaignKey-index"

    def test_get_unit_report_no_campaigns_found(
        self,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test report when no campaigns exist for unit+campaign."""
        mock_campaigns_table = MagicMock()

        # Arrange - unitCampaignKey-index query returns no campaigns
        mock_campaigns_table.query.return_value = {"Items": []}

        with patch("src.handlers.campaign_reporting.tables") as mock_tables:
            mock_tables.campaigns = mock_campaigns_table

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert result["unitType"] == "Pack"
            assert result["unitNumber"] == 158
            assert result["campaignName"] == "Fall"
            assert result["campaignYear"] == 2024
            assert result["sellers"] == []
            assert result["totalSales"] == 0.0
            assert result["totalOrders"] == 0

    def test_get_unit_report_no_access(
        self,
        event: Dict[str, Any],
        sample_campaigns: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller has no access to any profiles."""
        mock_campaigns_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.campaigns = mock_campaigns_table
            mock_check_access.return_value = set()

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert result["sellers"] == []
            assert result["totalSales"] == 0.0
            assert result["totalOrders"] == 0

    def test_get_unit_report_partial_access(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_campaigns: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller only has access to some profiles."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        # Grant access only to profile1
        def check_access_side_effect(*args: Any, **kwargs: Any) -> set[str]:
            profile_ids = args[1] if len(args) > 1 else kwargs.get("profile_ids", [])
            return {"PROFILE#profile1"} if "PROFILE#profile1" in profile_ids else set()

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        mock_orders_table.query.return_value = {"Items": sample_orders["CAMPAIGN#campaign1"]}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.side_effect = check_access_side_effect

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert len(result["sellers"]) == 1
            assert result["sellers"][0]["sellerName"] == "Scout 1"
            assert result["totalSales"] == 100.0
            assert result["totalOrders"] == 1

    def test_get_unit_report_no_orders(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_campaigns: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when campaigns exist but have no orders."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)
        mock_orders_table.query.return_value = {"Items": []}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1", "PROFILE#profile2"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - no sellers because they have no orders/sales
            assert result["sellers"] == []
            assert result["totalSales"] == 0.0
            assert result["totalOrders"] == 0

    def test_get_unit_report_seller_sorting(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_campaigns: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test that sellers are sorted by total sales descending."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        mock_orders_table.query.side_effect = _orders_by_campaign_query(sample_orders)

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1", "PROFILE#profile2"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - Sellers sorted by totalSales descending
            assert result["sellers"][0]["totalSales"] == 200.0  # Scout 2
            assert result["sellers"][1]["totalSales"] == 100.0  # Scout 1

    def test_get_unit_report_error_handling(
        self,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error handling when DynamoDB fails."""
        mock_campaigns_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.side_effect = Exception("DynamoDB error")

        with patch("src.handlers.campaign_reporting.tables") as mock_tables:
            mock_tables.campaigns = mock_campaigns_table

            # Act & Assert: the with_error_handling decorator converts the
            # unexpected DynamoDB error into an INTERNAL_ERROR error payload.
            result = get_unit_report(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == "INTERNAL_ERROR"
            assert result["message"] == "Failed to generate unit report"

    def test_get_unit_report_different_campaign_year(
        self,
        lambda_context: Any,
    ) -> None:
        """Test report filters by campaign year correctly via unitCampaignKey."""
        mock_campaigns_table = MagicMock()

        # Arrange - Different campaign
        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Spring",
                "campaignYear": 2023,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

        # unitCampaignKey-index query returns no campaigns for Spring 2023
        mock_campaigns_table.query.return_value = {"Items": []}

        with patch("src.handlers.campaign_reporting.tables") as mock_tables:
            mock_tables.campaigns = mock_campaigns_table

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert result["campaignName"] == "Spring"
            assert result["campaignYear"] == 2023
            assert result["sellers"] == []
            assert result["totalSales"] == 0.0

    def test_get_unit_report_multiple_campaigns_same_profile(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report with one profile having multiple campaigns (covers branch 109->111)."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange - Same profile has TWO campaigns for the same unit+campaign
        multi_campaigns = [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            },
            {
                "campaignId": "CAMPAIGN#campaign1b",
                "profileId": "PROFILE#profile1",  # Same profile!
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            },
        ]
        mock_campaigns_table.query.return_value = {"Items": multi_campaigns}

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        # Order for first campaign only
        mock_orders_table.query.return_value = {
            "Items": [
                {
                    "orderId": "ORDER#order1",
                    "campaignId": "CAMPAIGN#campaign1",
                    "customerName": "Customer 1",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("50.00"),
                    "lineItems": [],
                },
            ]
        }

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - Profile appears once even with 2 campaigns
            assert len(result["sellers"]) == 1
            assert result["sellers"][0]["sellerName"] == "Scout 1"
            # Orders from both campaigns are queried (same mock response for both)
            assert result["totalOrders"] == 2
            assert result["totalSales"] == 100.0  # 50.00 * 2 campaigns

    def test_get_unit_report_multiple_orders_per_seller(
        self,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report with seller having multiple orders."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange - Only one profile/campaign
        single_campaign = [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            }
        ]
        mock_campaigns_table.query.return_value = {"Items": single_campaign}

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        # Multiple orders for campaign1
        mock_orders_table.query.return_value = {
            "Items": [
                {
                    "orderId": "ORDER#order1",
                    "campaignId": "CAMPAIGN#campaign1",
                    "customerName": "Customer 1",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("100.00"),
                    "lineItems": [
                        {
                            "productId": "PROD#1",
                            "productName": "Caramel Corn",
                            "quantity": 10,
                            "pricePerUnit": Decimal("10.00"),
                            "subtotal": Decimal("100.00"),
                        }
                    ],
                },
                {
                    "orderId": "ORDER#order2",
                    "campaignId": "CAMPAIGN#campaign1",
                    "customerName": "Customer 2",
                    "orderDate": "2024-10-02T12:00:00Z",
                    "totalAmount": Decimal("150.00"),
                    "lineItems": [
                        {
                            "productId": "PROD#2",
                            "productName": "Cheese Corn",
                            "quantity": 15,
                            "pricePerUnit": Decimal("10.00"),
                            "subtotal": Decimal("150.00"),
                        }
                    ],
                },
            ]
        }

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert
            assert len(result["sellers"]) == 1
            seller = result["sellers"][0]
            assert seller["orderCount"] == 2
            assert seller["totalSales"] == 250.0
            assert len(seller["orders"]) == 2
            assert result["totalSales"] == 250.0
            assert result["totalOrders"] == 2

    def test_get_unit_report_without_city_state(
        self,
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_campaigns: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test report works with empty city/state (backward compatibility)."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange - event without city/state
        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        mock_orders_table.query.side_effect = _orders_by_campaign_query(sample_orders)

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1", "PROFILE#profile2"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - should still work, will use empty strings for city/state
            assert result["unitType"] == "Pack"
            assert result["unitNumber"] == 158

    def test_get_unit_report_profile_not_found(
        self,
        event: Dict[str, Any],
        sample_campaigns: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report handles missing profile gracefully."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()

        # Arrange
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        # Profile query returns empty
        mock_profiles_table.query.return_value = {"Items": []}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_check_access.return_value = {"PROFILE#profile1", "PROFILE#profile2"}

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - no accessible profiles since they couldn't be fetched
            assert result["sellers"] == []
            assert result["totalSales"] == 0.0
            assert result["totalOrders"] == 0

    def test_get_unit_report_orphaned_profile_is_skipped(
        self,
        event: Dict[str, Any],
        sample_campaigns: list[Dict[str, Any]],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test that one orphaned profile (NOT_FOUND from access check) doesn't kill the whole report."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        # Arrange - campaigns reference two profiles
        mock_campaigns_table.query.return_value = {"Items": sample_campaigns}

        def check_access_side_effect(*args: Any, **kwargs: Any) -> set[str]:
            # Orphaned profile is simply not accessible; second profile is accessible.
            return {"PROFILE#profile2"}

        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)
        mock_orders_table.query.return_value = {"Items": sample_orders["CAMPAIGN#campaign2"]}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.side_effect = check_access_side_effect

            # Act
            result = get_unit_report(event, lambda_context)

            # Assert - Report succeeds with the remaining accessible profile
            assert len(result["sellers"]) == 1
            assert result["sellers"][0]["sellerName"] == "Scout 2"
            assert result["totalSales"] == 200.0
            assert result["totalOrders"] == 1

    def test_get_unit_report_decimal_precision_drift(
        self,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that accumulating many orders does not suffer from float precision drift."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        campaigns = [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            }
        ]
        profiles = {
            "PROFILE#profile1": {
                "profileId": "PROFILE#profile1",
                "ownerAccountId": "test-account-123",
                "sellerName": "Scout 1",
            }
        }
        orders = [
            {
                "orderId": f"ORDER#order_{i}",
                "campaignId": "CAMPAIGN#campaign1",
                "customerName": f"Customer {i}",
                "orderDate": "2024-10-01T12:00:00Z",
                "totalAmount": "1.99",
                "lineItems": [
                    {
                        "productId": "PROD#1",
                        "productName": "Popcorn",
                        "quantity": 1,
                        "pricePerUnit": "1.99",
                        "subtotal": "1.99",
                    }
                ],
            }
            for i in range(100)
        ]

        mock_campaigns_table.query.return_value = {"Items": campaigns}
        self._setup_profile_query_mock(mock_profiles_table, profiles)
        mock_orders_table.query.return_value = {"Items": orders}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1"}

            result = get_unit_report(event, lambda_context)

            assert len(result["sellers"]) == 1
            assert result["sellers"][0]["totalSales"] == 199.0
            assert result["totalSales"] == 199.0
            assert result["totalOrders"] == 100

    def test_get_unit_report_legacy_drifted_floats(
        self,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that legacy drifted floats (e.g. 0.30000000000000004) are quantized to cents."""
        mock_profiles_table = MagicMock()
        mock_campaigns_table = MagicMock()
        mock_orders_table = MagicMock()

        campaigns = [
            {
                "campaignId": "CAMPAIGN#campaign1",
                "profileId": "PROFILE#profile1",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
            }
        ]
        profiles = {
            "PROFILE#profile1": {
                "profileId": "PROFILE#profile1",
                "ownerAccountId": "test-account-123",
                "sellerName": "Scout 1",
            }
        }
        orders = [
            {
                "orderId": "ORDER#1",
                "campaignId": "CAMPAIGN#campaign1",
                "customerName": "Customer 1",
                "orderDate": "2024-10-01T12:00:00Z",
                "totalAmount": 0.30000000000000004,
                "lineItems": [
                    {
                        "productId": "PROD#1",
                        "productName": "Item 1",
                        "quantity": 1,
                        "pricePerUnit": 0.30000000000000004,
                        "subtotal": 0.30000000000000004,
                    }
                ],
            },
            {
                "orderId": "ORDER#2",
                "campaignId": "CAMPAIGN#campaign1",
                "customerName": "Customer 2",
                "orderDate": "2024-10-01T12:00:00Z",
                "totalAmount": 0.6000000000000001,
                "lineItems": [
                    {
                        "productId": "PROD#2",
                        "productName": "Item 2",
                        "quantity": 2,
                        "pricePerUnit": 0.30000000000000004,
                        "subtotal": 0.6000000000000001,
                    }
                ],
            },
        ]

        mock_campaigns_table.query.return_value = {"Items": campaigns}
        self._setup_profile_query_mock(mock_profiles_table, profiles)
        mock_orders_table.query.return_value = {"Items": orders}

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = mock_profiles_table
            mock_tables.campaigns = mock_campaigns_table
            mock_tables.orders = mock_orders_table
            mock_check_access.return_value = {"PROFILE#profile1"}

            result = get_unit_report(event, lambda_context)

            assert len(result["sellers"]) == 1
            assert result["sellers"][0]["totalSales"] == 0.90
            assert result["totalSales"] == 0.90
            assert result["totalOrders"] == 2


class TestGetAccessibleProfilesBatching:
    """Dedicated tests for parallel batch profile querying in _get_accessible_profiles (#450)."""

    def test_get_accessible_profiles_empty_input(self) -> None:
        """Empty profile_ids returns empty dict with zero calls."""
        with patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_auth:
            result = _get_accessible_profiles([], "ACCOUNT#caller")
            assert result == {}
            mock_auth.assert_not_called()

    def test_get_accessible_profiles_no_accessible_ids(self) -> None:
        """When batch_check_profile_access returns empty set, returns empty dict without querying."""
        with (
            patch("src.handlers.campaign_reporting.batch_check_profile_access", return_value=set()) as mock_auth,
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
        ):
            result = _get_accessible_profiles(["PROFILE#1"], "ACCOUNT#caller")
            assert result == {}
            mock_auth.assert_called_once()
            mock_tables.profiles.query.assert_not_called()

    def test_get_accessible_profiles_chunking_over_100(self) -> None:
        """More than 100 accessible profiles are chunked and queried in parallel batches."""
        profile_ids = [f"PROFILE#{i:03d}" for i in range(150)]
        mock_profiles_table = MagicMock()

        def query_side_effect(**kwargs: Any) -> Dict[str, Any]:
            pid = kwargs["ExpressionAttributeValues"][":profileId"]
            return {"Items": [{"profileId": pid, "sellerName": f"Seller {pid}"}]}

        mock_profiles_table.query.side_effect = query_side_effect

        with (
            patch("src.handlers.campaign_reporting.batch_check_profile_access", return_value=set(profile_ids)),
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
        ):
            mock_tables.profiles = mock_profiles_table
            result = _get_accessible_profiles(profile_ids, "ACCOUNT#caller")

        assert len(result) == 150
        assert mock_profiles_table.query.call_count == 150
        for pid in profile_ids:
            assert pid in result
            assert result[pid]["sellerName"] == f"Seller {pid}"

    def test_get_accessible_profiles_profile_missing_in_gsi(self) -> None:
        """Profiles not found in GSI are omitted from returned dict."""
        mock_profiles_table = MagicMock()

        def query_side_effect(**kwargs: Any) -> Dict[str, Any]:
            pid = kwargs["ExpressionAttributeValues"][":profileId"]
            if pid == "PROFILE#exists":
                return {"Items": [{"profileId": pid, "sellerName": "Found"}]}
            return {"Items": []}

        mock_profiles_table.query.side_effect = query_side_effect

        with (
            patch(
                "src.handlers.campaign_reporting.batch_check_profile_access",
                return_value={"PROFILE#exists", "PROFILE#missing"},
            ),
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
        ):
            mock_tables.profiles = mock_profiles_table
            result = _get_accessible_profiles(["PROFILE#exists", "PROFILE#missing"], "ACCOUNT#caller")

        assert len(result) == 1
        assert "PROFILE#exists" in result
        assert "PROFILE#missing" not in result


def _ceiling_override(max_bytes: int) -> Any:
    """Return an ``OrderGraphBudget`` stand-in that enforces a test-sized ceiling."""

    def factory(subject: str, _max_bytes: int) -> OrderGraphBudget:
        return OrderGraphBudget(subject, max_bytes)

    return factory


class TestUnitReportOrderGraphCeiling:
    """Tests for the unit-wide order-graph ceiling on get_unit_report (#577).

    The handler used to materialise every order and every line item for the whole
    unit, so the largest units - the ones the report exists for - exhausted the
    Lambda's memory and returned a response AppSync truncates, surfacing as a
    generic INTERNAL_ERROR. The shared ceiling is measured in the bytes the order
    details serialise to, is charged on each detail as it is built and before it
    is accumulated, and turns an over-sized unit into a typed RESOURCE_BUSY
    error.
    """

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """AppSync event for a single-campaign unit."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

    def _campaign(self, index: int = 1) -> Dict[str, Any]:
        """Build a campaign belonging to profile1."""
        return {
            "campaignId": f"CAMPAIGN#campaign{index}",
            "profileId": "PROFILE#profile1",
            "campaignName": "Fall",
            "campaignYear": 2024,
            "catalogId": "CATALOG#catalog-123",
            "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
        }

    def _order(self, campaign_index: int, order_index: int, line_items: int = 1) -> Dict[str, Any]:
        """Build an order whose line items are as wide as a real bulk popcorn order."""
        return {
            "orderId": f"ORDER#2f1c9d4a-8b3e-4a21-9c77-1f0d5e6a7b8c-{order_index}",
            "campaignId": f"CAMPAIGN#campaign{campaign_index}",
            "customerName": "Alexandra Montgomery-Whitfield",
            "orderDate": "2024-10-01T12:00:00.000Z",
            "totalAmount": Decimal("12345.67"),
            "lineItems": [
                {
                    "productId": f"PRODUCT#7d9a1c2e-4b3a-4c8d-9e0f-1a2b3c4d5e6f-{item}",
                    "productName": "White Chocolate Caramel Popcorn (16oz Bucket)",
                    "quantity": 12,
                    "pricePerUnit": Decimal("12.50"),
                    "subtotal": Decimal("150.00"),
                }
                for item in range(line_items)
            ],
        }

    def _detail_bytes(self, orders: list[Dict[str, Any]]) -> int:
        """Return what the handler charges for these orders: the details it returns."""
        return sum(order_graph_bytes(_build_order_detail(order)) for order in orders)

    def _run(
        self,
        event: Dict[str, Any],
        campaigns: list[Dict[str, Any]],
        orders_by_campaign: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
        max_graph_bytes: int | None = None,
    ) -> Dict[str, Any]:
        """Run get_unit_report with the given campaigns and per-campaign orders."""
        profiles_table = MagicMock()
        campaigns_table = MagicMock()
        orders_table = MagicMock()
        campaigns_table.query.return_value = {"Items": campaigns}
        profiles_table.query.side_effect = lambda **kwargs: {
            "Items": [
                {
                    "profileId": kwargs["ExpressionAttributeValues"][":profileId"],
                    "ownerAccountId": "test-account-123",
                    "sellerName": "Scout 1",
                }
            ]
        }
        # Orders are queried one campaign at a time; the stand-in answers per campaignId.
        orders_table.query.side_effect = _orders_by_campaign_query(orders_by_campaign)

        budget = OrderGraphBudget if max_graph_bytes is None else _ceiling_override(max_graph_bytes)
        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
            patch("src.handlers.campaign_reporting.OrderGraphBudget", budget),
        ):
            mock_tables.profiles = profiles_table
            mock_tables.campaigns = campaigns_table
            mock_tables.orders = orders_table
            mock_check_access.return_value = {c["profileId"] for c in campaigns}
            return get_unit_report(event, lambda_context)

    def test_unit_report_refuses_order_graph_over_the_budget(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """A unit whose order details exceed the ceiling fails with a typed RESOURCE_BUSY error."""
        orders = [self._order(1, i) for i in range(3)]

        result = self._run(
            event,
            [self._campaign()],
            {"CAMPAIGN#campaign1": orders},
            lambda_context,
            self._detail_bytes(orders) - 1,
        )

        assert result["__isError"] is True
        assert result["errorCode"] == "RESOURCE_BUSY"
        assert "too large" in result["message"]
        # No partial report is returned when the ceiling is reached.
        assert "sellers" not in result

    def test_unit_report_returns_orders_within_the_budget(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """A unit whose order details fit the ceiling still returns its full report."""
        orders = [self._order(1, i) for i in range(2)]

        result = self._run(
            event, [self._campaign()], {"CAMPAIGN#campaign1": orders}, lambda_context, self._detail_bytes(orders)
        )
        assert result["totalOrders"] == 2
        assert result["totalSales"] == 24691.34
        assert len(result["sellers"][0]["orders"]) == 2
        assert result["sellers"][0]["orders"][0]["lineItems"][0]["subtotal"] == 150.0

    def test_budget_counts_line_items_not_just_orders(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """The same ceiling admits narrow orders and refuses wide ones of the same count."""
        narrow = [self._order(1, i) for i in range(3)]
        wide = [self._order(1, i, line_items=20) for i in range(3)]
        budget_bytes = self._detail_bytes(narrow)

        admitted = self._run(event, [self._campaign()], {"CAMPAIGN#campaign1": narrow}, lambda_context, budget_bytes)
        refused = self._run(event, [self._campaign()], {"CAMPAIGN#campaign1": wide}, lambda_context, budget_bytes)

        assert admitted["totalOrders"] == 3
        assert refused["__isError"] is True
        assert refused["errorCode"] == "RESOURCE_BUSY"

    def test_budget_spans_the_whole_unit(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """The ceiling is unit-wide: order details across several sellers accumulate against it."""
        campaigns = [
            self._campaign(1),
            {**self._campaign(2), "profileId": "PROFILE#profile2"},
        ]
        orders_by_campaign = {
            "CAMPAIGN#campaign1": [self._order(1, 0), self._order(1, 1)],
            "CAMPAIGN#campaign2": [self._order(2, 2)],
        }
        budget_bytes = self._detail_bytes([o for orders in orders_by_campaign.values() for o in orders]) - 1

        result = self._run(event, campaigns, orders_by_campaign, lambda_context, budget_bytes)

        assert result["__isError"] is True
        assert result["errorCode"] == "RESOURCE_BUSY"

    def test_worst_case_unit_report_fits_the_response_ceiling(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """A realistic worst-case unit that the budget admits serialises within the ceiling.

        200 orders of 20 line items is a wide, long-season unit report: the real
        response is measured against the same ceiling the handler enforces, so a
        change to the query or detail shape that makes the charge fiction fails
        here instead of reaching AppSync's 5 MB response limit.
        """
        orders = [self._order(1, i, line_items=20) for i in range(200)]

        result = self._run(event, [self._campaign()], {"CAMPAIGN#campaign1": orders}, lambda_context)

        assert result["totalOrders"] == 200
        assert len(json.dumps(result, default=float).encode("utf-8")) <= MAX_UNIT_REPORT_GRAPH_BYTES
        assert sum(len(order["lineItems"]) for order in result["sellers"][0]["orders"]) == 4000

    def test_worst_case_unit_report_beyond_the_ceiling_is_refused(
        self, event: Dict[str, Any], lambda_context: Any
    ) -> None:
        """Enough wide orders to cross the ceiling are refused rather than truncated."""
        orders = [self._order(1, i, line_items=20) for i in range(600)]

        result = self._run(event, [self._campaign()], {"CAMPAIGN#campaign1": orders}, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == "RESOURCE_BUSY"

    def test_a_realistic_pack_unit_still_reports(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """A 30-seller unit with 50 orders each reports, and its response fits the quota.

        This is the shape the report exists for - the largest unit the issue
        describes - and the one the ceiling must not start refusing. The real
        response is measured against AppSync's 5 MB quota, the bound the ceiling
        is derived from, rather than against the ceiling's own headroom.
        """
        campaigns = [{**self._campaign(index), "profileId": f"PROFILE#profile{index}"} for index in range(30)]
        orders_by_campaign = {
            f"CAMPAIGN#campaign{index}": [self._order(index, order) for order in range(50)] for index in range(30)
        }

        result = self._run(event, campaigns, orders_by_campaign, lambda_context)

        assert result["totalOrders"] == 1500
        assert len(result["sellers"]) == 30
        assert len(json.dumps(result, default=float).encode("utf-8")) <= APPSYNC_RESPONSE_LIMIT_BYTES

    def test_unit_report_stops_reading_once_the_budget_is_exhausted(
        self, event: Dict[str, Any], lambda_context: Any
    ) -> None:
        """Orders are streamed, so the refusal happens without paging the rest of the table."""
        campaigns_table = MagicMock()
        profiles_table = MagicMock()
        orders_table = MagicMock()
        campaigns_table.query.return_value = {"Items": [self._campaign(1)]}
        profiles_table.query.side_effect = lambda **kwargs: {
            "Items": [
                {
                    "profileId": kwargs["ExpressionAttributeValues"][":profileId"],
                    "sellerName": "Scout 1",
                }
            ]
        }
        pages = {"count": 0}

        def order_page(**kwargs: Any) -> Dict[str, Any]:
            pages["count"] += 1
            if pages["count"] > 50:  # pragma: no cover - guard against an unbounded read hanging
                raise AssertionError("orders query paged past the report ceiling")
            return {
                "Items": [self._order(1, i) for i in range(pages["count"] * 10, pages["count"] * 10 + 10)],
                "LastEvaluatedKey": {"orderId": f"ORDER#page{pages['count']}"},
            }

        orders_table.query.side_effect = order_page

        # Sized so the tenth order of the first page is the one that crosses.
        first_page_bytes = max(order_graph_bytes(_build_order_detail(self._order(1, index))) for index in range(10))

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
            patch(
                "src.handlers.campaign_reporting.OrderGraphBudget",
                _ceiling_override(9 * first_page_bytes),
            ),
        ):
            mock_tables.profiles = profiles_table
            mock_tables.campaigns = campaigns_table
            mock_tables.orders = orders_table
            mock_check_access.return_value = {"PROFILE#profile1"}
            result = get_unit_report(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == "RESOURCE_BUSY"
        # One page is enough to reach the ceiling; the handler does not keep
        # following LastEvaluatedKey through the rest of the table.
        assert orders_table.query.call_count == 1


class TestUnitReportOrderQueryConcurrency:
    """Tests for how the unit report reads the orders table (#555).

    A report used to issue one orders-table Query per campaign of every
    accessible seller, one after the other, so its wall clock grew with
    sellers x campaigns and a large unit timed out with no report at all. The
    reads now run concurrently, capped, and a unit past the cap is refused with
    an actionable error rather than a timeout. These tests measure the reads the
    handler actually issues - a serial implementation fails them by blocking on
    the barrier, not by matching any source text.
    """

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """AppSync event for a unit campaign report."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": "CATALOG#catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

    def _campaign(self, index: int, profile_index: int | None = None) -> Dict[str, Any]:
        """Build a campaign of the unit, owned by its own profile."""
        return {
            "campaignId": f"CAMPAIGN#campaign{index}",
            "profileId": f"PROFILE#profile{index if profile_index is None else profile_index}",
            "campaignName": "Fall",
            "campaignYear": 2024,
            "catalogId": "CATALOG#catalog-123",
            "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2024",
        }

    def _order(self, campaign_index: int, order_index: int) -> Dict[str, Any]:
        """Build one order of a campaign, worth 10.00."""
        return {
            "orderId": f"ORDER#order{campaign_index}-{order_index}",
            "campaignId": f"CAMPAIGN#campaign{campaign_index}",
            "customerName": "Customer",
            "orderDate": "2024-10-01T12:00:00Z",
            "totalAmount": Decimal("10.00"),
            "lineItems": [
                {
                    "productId": "PRODUCT#1",
                    "productName": "Caramel Corn",
                    "quantity": 1,
                    "pricePerUnit": Decimal("10.00"),
                    "subtotal": Decimal("10.00"),
                }
            ],
        }

    def _orders_by_campaign(
        self, campaign_indexes: list[int], orders_per_campaign: int = 1
    ) -> Dict[str, list[Dict[str, Any]]]:
        """Build the orders each campaign returns, keyed by campaignId."""
        return {
            f"CAMPAIGN#campaign{index}": [self._order(index, n) for n in range(orders_per_campaign)]
            for index in campaign_indexes
        }

    def _concurrent_orders_query(
        self, orders_by_campaign: Dict[str, list[Dict[str, Any]]]
    ) -> tuple[Any, Dict[str, int]]:
        """Return an orders ``query`` stand-in that only answers when reads overlap.

        Every read blocks on a barrier sized to the concurrency cap, so a report
        that reads its campaigns one after another never gets past the first read
        (the barrier times out and the report fails) and a report that reads them
        all at once is recorded as such. The caller's numbers are how the
        concurrency is measured: how many queries were issued and how many were
        in flight at the busiest moment.
        """
        barrier = threading.Barrier(_ORDER_QUERY_CONCURRENCY, timeout=10)
        state = {"queries": 0, "in_flight": 0, "max_in_flight": 0}
        lock = threading.Lock()

        def query(**kwargs: Any) -> Dict[str, Any]:
            campaign_id = kwargs["KeyConditionExpression"].get_expression()["values"][1]
            with lock:
                state["queries"] += 1
                state["in_flight"] += 1
                state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            try:
                barrier.wait()
            finally:
                with lock:
                    state["in_flight"] -= 1
            return {"Items": orders_by_campaign.get(campaign_id, [])}

        return query, state

    def _run(
        self, event: Dict[str, Any], campaigns: list[Dict[str, Any]], lambda_context: Any
    ) -> tuple[Dict[str, Any], Dict[str, int]]:
        """Run get_unit_report over a unit's campaigns, with overlapping order reads."""
        orders_by_campaign = self._orders_by_campaign(
            [int(campaign["campaignId"].removeprefix("CAMPAIGN#campaign")) for campaign in campaigns]
        )
        orders_query, state = self._concurrent_orders_query(orders_by_campaign)
        orders_table = MagicMock()
        orders_table.query.side_effect = orders_query
        campaigns_table = MagicMock()
        campaigns_table.query.return_value = {"Items": campaigns}
        profiles_table = MagicMock()
        profiles_table.query.side_effect = lambda **kwargs: {
            "Items": [
                {
                    "profileId": kwargs["ExpressionAttributeValues"][":profileId"],
                    "sellerName": "Scout",
                }
            ]
        }

        with (
            patch("src.handlers.campaign_reporting.tables") as mock_tables,
            patch("src.handlers.campaign_reporting.batch_check_profile_access") as mock_check_access,
        ):
            mock_tables.profiles = profiles_table
            mock_tables.campaigns = campaigns_table
            mock_tables.orders = orders_table
            mock_check_access.return_value = {campaign["profileId"] for campaign in campaigns}
            return get_unit_report(event, lambda_context), state

    def test_campaign_order_reads_run_concurrently_and_capped(self, event: Dict[str, Any], lambda_context: Any) -> None:
        """A 30-seller unit reads its 30 campaigns' orders at the cap, not one at a time."""
        campaigns = [self._campaign(index) for index in range(30)]

        result, state = self._run(event, campaigns, lambda_context)

        assert "__isError" not in result
        assert state["queries"] == len(campaigns)
        assert state["max_in_flight"] == _ORDER_QUERY_CONCURRENCY

    def test_reads_scale_with_campaigns_not_with_seller_campaign_rounds(
        self, event: Dict[str, Any], lambda_context: Any
    ) -> None:
        """Sellers with several campaigns each read every campaign, still capped and correct."""
        campaigns = [
            self._campaign(profile_index * 4 + campaign, profile_index)
            for profile_index in range(30)
            for campaign in range(4)
        ]

        result, state = self._run(event, campaigns, lambda_context)

        assert "__isError" not in result
        assert len(result["sellers"]) == 30
        assert result["totalOrders"] == len(campaigns)
        assert result["totalSales"] == float(len(campaigns) * 10)
        # One read per campaign - the unit's 120 campaigns, not 120 rounds of
        # one, and never more than the cap in flight at a time.
        assert state["queries"] == len(campaigns)
        assert state["max_in_flight"] == _ORDER_QUERY_CONCURRENCY

    def test_a_unit_past_the_query_cap_is_refused_before_any_read(
        self, event: Dict[str, Any], lambda_context: Any
    ) -> None:
        """Too many campaigns for one report is a typed error, not a Lambda timeout."""
        campaigns = [self._campaign(index) for index in range(MAX_UNIT_REPORT_CAMPAIGN_QUERIES + 1)]

        result, state = self._run(event, campaigns, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == "RESOURCE_BUSY"
        assert str(MAX_UNIT_REPORT_CAMPAIGN_QUERIES) in result["message"]
        assert str(len(campaigns)) in result["message"]
        # The cap is enforced before the handler spends a minute on orders.
        assert state["queries"] == 0
