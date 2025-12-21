"""Unit tests for campaign reporting Lambda handler (GSI3-based implementation)."""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.campaign_reporting import get_unit_report


class TestGetUnitReport:
    """Tests for get_unit_report Lambda handler using GSI3 season queries."""

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
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
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
    def sample_seasons(self) -> list[Dict[str, Any]]:
        """Sample seasons returned from GSI3 query."""
        return [
            {
                "seasonId": "SEASON#season1",
                "profileId": "PROFILE#profile1",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
                "unitSeasonKey": "Pack#158#Springfield#IL#Fall#2024",
            },
            {
                "seasonId": "SEASON#season2",
                "profileId": "PROFILE#profile2",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
                "unitSeasonKey": "Pack#158#Springfield#IL#Fall#2024",
            },
        ]

    @pytest.fixture
    def sample_orders(self) -> Dict[str, list[Dict[str, Any]]]:
        """Sample orders by season."""
        return {
            "SEASON#season1": [
                {
                    "orderId": "ORDER#order1",
                    "seasonId": "SEASON#season1",
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
            "SEASON#season2": [
                {
                    "orderId": "ORDER#order2",
                    "seasonId": "SEASON#season2",
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

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_success(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test successful unit report generation using GSI3."""
        # Arrange - GSI3 query returns seasons directly
        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = True

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        # Return orders for each season
        mock_orders_table.query.side_effect = [
            {"Items": sample_orders["SEASON#season1"]},
            {"Items": sample_orders["SEASON#season2"]},
        ]

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 158
        assert result["seasonName"] == "Fall"
        assert result["seasonYear"] == 2024
        assert len(result["sellers"]) == 2
        assert result["totalSales"] == 300.0
        assert result["totalOrders"] == 2

        # Verify GSI3 query was called correctly
        mock_seasons_table.query.assert_called_once()
        call_kwargs = mock_seasons_table.query.call_args.kwargs
        assert call_kwargs["IndexName"] == "GSI3"

    @patch("src.handlers.campaign_reporting.seasons_table")
    def test_get_unit_report_no_seasons_found(
        self,
        mock_seasons_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test report when no seasons exist for unit+season."""
        # Arrange - GSI3 query returns no seasons
        mock_seasons_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 158
        assert result["seasonName"] == "Fall"
        assert result["seasonYear"] == 2024
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.seasons_table")
    def test_get_unit_report_no_access(
        self,
        mock_seasons_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_seasons: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller has no access to any profiles."""
        # Arrange
        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = False

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_partial_access(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller only has access to some profiles."""
        # Arrange
        mock_seasons_table.query.return_value = {"Items": sample_seasons}

        # Grant access only to profile1
        def check_access_side_effect(*args: Any, **kwargs: Any) -> bool:
            return kwargs["profile_id"] == "PROFILE#profile1"

        mock_check_access.side_effect = check_access_side_effect

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        mock_orders_table.query.return_value = {"Items": sample_orders["SEASON#season1"]}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert len(result["sellers"]) == 1
        assert result["sellers"][0]["sellerName"] == "Scout 1"
        assert result["totalSales"] == 100.0
        assert result["totalOrders"] == 1

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_no_orders(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when seasons exist but have no orders."""
        # Arrange
        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = True

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)
        mock_orders_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert - no sellers because they have no orders/sales
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_seller_sorting(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test that sellers are sorted by total sales descending."""
        # Arrange
        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = True

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        mock_orders_table.query.side_effect = [
            {"Items": sample_orders["SEASON#season1"]},
            {"Items": sample_orders["SEASON#season2"]},
        ]

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert - Sellers sorted by totalSales descending
        assert result["sellers"][0]["totalSales"] == 200.0  # Scout 2
        assert result["sellers"][1]["totalSales"] == 100.0  # Scout 1

    @patch("src.handlers.campaign_reporting.seasons_table")
    def test_get_unit_report_error_handling(
        self,
        mock_seasons_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error handling when DynamoDB fails."""
        # Arrange
        mock_seasons_table.query.side_effect = Exception("DynamoDB error")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            get_unit_report(event, lambda_context)

        assert "DynamoDB error" in str(exc_info.value)

    @patch("src.handlers.campaign_reporting.seasons_table")
    def test_get_unit_report_different_season_year(
        self,
        mock_seasons_table: MagicMock,
        lambda_context: Any,
    ) -> None:
        """Test report filters by season year correctly via GSI3 key."""
        # Arrange - Different season
        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "seasonName": "Spring",
                "seasonYear": 2023,
                "catalogId": "catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

        # GSI3 query returns no seasons for Spring 2023
        mock_seasons_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["seasonName"] == "Spring"
        assert result["seasonYear"] == 2023
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_multiple_seasons_same_profile(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report with one profile having multiple seasons (covers branch 109->111)."""
        # Arrange - Same profile has TWO seasons for the same unit+season
        multi_seasons = [
            {
                "seasonId": "SEASON#season1",
                "profileId": "PROFILE#profile1",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
                "unitSeasonKey": "Pack#158#Springfield#IL#Fall#2024",
            },
            {
                "seasonId": "SEASON#season1b",
                "profileId": "PROFILE#profile1",  # Same profile!
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
                "unitSeasonKey": "Pack#158#Springfield#IL#Fall#2024",
            },
        ]
        mock_seasons_table.query.return_value = {"Items": multi_seasons}
        mock_check_access.return_value = True

        # Mock profile lookups using query on profileId-index
        self._setup_profile_query_mock(mock_profiles_table, sample_profiles)

        # Order for first season only
        mock_orders_table.query.return_value = {
            "Items": [
                {
                    "orderId": "ORDER#order1",
                    "seasonId": "SEASON#season1",
                    "customerName": "Customer 1",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("50.00"),
                    "lineItems": [],
                },
            ]
        }

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert - Profile appears once even with 2 seasons
        assert len(result["sellers"]) == 1
        assert result["sellers"][0]["sellerName"] == "Scout 1"
        # Orders from both seasons are queried (same mock response for both)
        assert result["totalOrders"] == 2
        assert result["totalSales"] == 100.0  # 50.00 * 2 seasons

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_multiple_orders_per_seller(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: Dict[str, Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report with seller having multiple orders."""
        # Arrange - Only one profile/season
        single_season = [
            {
                "seasonId": "SEASON#season1",
                "profileId": "PROFILE#profile1",
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
                "unitSeasonKey": "Pack#158#Springfield#IL#Fall#2024",
            }
        ]
        mock_seasons_table.query.return_value = {"Items": single_season}
        mock_check_access.return_value = True

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        # Multiple orders for season1
        mock_orders_table.query.return_value = {
            "Items": [
                {
                    "orderId": "ORDER#order1",
                    "seasonId": "SEASON#season1",
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
                    "seasonId": "SEASON#season1",
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

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.orders_table")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_without_city_state(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        sample_profiles: Dict[str, Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test report works with empty city/state (backward compatibility)."""
        # Arrange - event without city/state
        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = True

        def get_item_side_effect(Key: Dict[str, str]) -> Dict[str, Any]:
            profile_id = Key["profileId"]
            if profile_id in sample_profiles:
                return {"Item": sample_profiles[profile_id]}
            return {}

        mock_profiles_table.get_item.side_effect = get_item_side_effect

        mock_orders_table.query.side_effect = [
            {"Items": sample_orders["SEASON#season1"]},
            {"Items": sample_orders["SEASON#season2"]},
        ]

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert - should still work, will use empty strings for city/state
        assert result["unitType"] == "Pack"
        assert result["unitNumber"] == 158

    @patch("src.handlers.campaign_reporting.check_profile_access")
    @patch("src.handlers.campaign_reporting.seasons_table")
    @patch("src.handlers.campaign_reporting.profiles_table")
    def test_get_unit_report_profile_not_found(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_seasons: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report handles missing profile gracefully."""
        # Arrange
        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_check_access.return_value = True

        # Profile query returns empty
        mock_profiles_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert - no accessible profiles since they couldn't be fetched
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0
