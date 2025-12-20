"""Unit tests for unit reporting Lambda handler."""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.unit_reporting import get_unit_report


class TestGetUnitReport:
    """Tests for get_unit_report Lambda handler."""

    @pytest.fixture
    def event(self) -> Dict[str, Any]:
        """Sample AppSync event for unit report request."""
        return {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "seasonName": "Fall",
                "seasonYear": 2024,
                "catalogId": "catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

    @pytest.fixture
    def sample_profiles(self) -> list[Dict[str, Any]]:
        """Sample profiles in a unit."""
        return [
            {
                "profileId": "PROFILE#profile1",
                "ownerAccountId": "test-account-123",
                "sellerName": "Scout 1",
                "unitType": "Pack",
                "unitNumber": 158,
            },
            {
                "profileId": "PROFILE#profile2",
                "ownerAccountId": "test-account-456",
                "sellerName": "Scout 2",
                "unitType": "Pack",
                "unitNumber": 158,
            },
        ]

    @pytest.fixture
    def sample_seasons(self) -> list[Dict[str, Any]]:
        """Sample seasons for profiles."""
        return [
            {
                "seasonId": "SEASON#season1",
                "profileId": "PROFILE#profile1",
                "seasonName": "Fall",
                "seasonYear": 2024,
            },
            {
                "seasonId": "SEASON#season2",
                "profileId": "PROFILE#profile2",
                "seasonName": "Fall",
                "seasonYear": 2024,
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

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_success(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test successful unit report generation."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True

        # Return seasons one at a time
        mock_seasons_table.query.side_effect = [
            {"Items": [sample_seasons[0]]},  # profile1
            {"Items": [sample_seasons[1]]},  # profile2
        ]

        # Return orders one at a time
        mock_orders_table.query.side_effect = [
            {"Items": sample_orders["SEASON#season1"]},  # season1
            {"Items": sample_orders["SEASON#season2"]},  # season2
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

        # Check seller details
        seller1 = next(s for s in result["sellers"] if s["sellerName"] == "Scout 1")
        assert seller1["totalSales"] == 100.0
        assert seller1["orderCount"] == 1
        assert len(seller1["orders"]) == 1

        seller2 = next(s for s in result["sellers"] if s["sellerName"] == "Scout 2")
        assert seller2["totalSales"] == 200.0
        assert seller2["orderCount"] == 1

    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_no_profiles_found(
        self,
        mock_profiles_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test report when no profiles exist for unit."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": []}

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

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_no_access(
        self,
        mock_profiles_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller has no access to any profiles."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = False

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_partial_access(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test report when caller only has access to some profiles."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}

        # Grant access only to profile1
        def check_access_side_effect(*args, **kwargs):
            return kwargs["profile_id"] == "PROFILE#profile1"

        mock_check_access.side_effect = check_access_side_effect

        mock_seasons_table.query.return_value = {"Items": sample_seasons[:1]}

        mock_orders_table.query.return_value = {"Items": sample_orders["SEASON#season1"]}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert len(result["sellers"]) == 1
        assert result["sellers"][0]["sellerName"] == "Scout 1"
        assert result["totalSales"] == 100.0
        assert result["totalOrders"] == 1

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_no_orders(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report when profiles exist but have no orders."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True

        mock_seasons_table.query.return_value = {"Items": sample_seasons}
        mock_orders_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0
        assert result["totalOrders"] == 0

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_seller_sorting(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        sample_seasons: list[Dict[str, Any]],
        sample_orders: Dict[str, list[Dict[str, Any]]],
        lambda_context: Any,
    ) -> None:
        """Test that sellers are sorted by total sales descending."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True

        mock_seasons_table.query.side_effect = [
            {"Items": [sample_seasons[0]]},
            {"Items": [sample_seasons[1]]},
        ]

        mock_orders_table.query.side_effect = [
            {"Items": sample_orders["SEASON#season1"]},
            {"Items": sample_orders["SEASON#season2"]},
        ]

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        # Sellers should be sorted by totalSales descending
        assert result["sellers"][0]["totalSales"] == 200.0  # Scout 2
        assert result["sellers"][1]["totalSales"] == 100.0  # Scout 1

    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_error_handling(
        self,
        mock_profiles_table: MagicMock,
        event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error handling when DynamoDB fails."""
        # Arrange
        mock_profiles_table.scan.side_effect = Exception("DynamoDB error")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            get_unit_report(event, lambda_context)

        assert "DynamoDB error" in str(exc_info.value)

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_different_season_year(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        sample_profiles: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report filters by season year correctly."""
        # Arrange
        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "seasonName": "Spring",
                "seasonYear": 2023,  # Different year
                "catalogId": "catalog-123",
            },
            "identity": {"sub": "test-account-123"},
        }

        mock_profiles_table.scan.return_value = {"Items": sample_profiles}
        mock_check_access.return_value = True

        # No seasons for Spring 2023
        mock_seasons_table.query.return_value = {"Items": []}

        # Act
        result = get_unit_report(event, lambda_context)

        # Assert
        assert result["seasonName"] == "Spring"
        assert result["seasonYear"] == 2023
        assert result["sellers"] == []
        assert result["totalSales"] == 0.0

    @patch("src.handlers.unit_reporting.check_profile_access")
    @patch("src.handlers.unit_reporting.orders_table")
    @patch("src.handlers.unit_reporting.seasons_table")
    @patch("src.handlers.unit_reporting.profiles_table")
    def test_get_unit_report_multiple_orders_per_seller(
        self,
        mock_profiles_table: MagicMock,
        mock_seasons_table: MagicMock,
        mock_orders_table: MagicMock,
        mock_check_access: MagicMock,
        event: Dict[str, Any],
        sample_profiles: list[Dict[str, Any]],
        lambda_context: Any,
    ) -> None:
        """Test report with seller having multiple orders."""
        # Arrange
        mock_profiles_table.scan.return_value = {"Items": [sample_profiles[0]]}  # Only profile1
        mock_check_access.return_value = True

        mock_seasons_table.query.return_value = {
            "Items": [
                {
                    "seasonId": "SEASON#season1",
                    "profileId": "PROFILE#profile1",
                    "seasonName": "Fall",
                    "seasonYear": 2024,
                }
            ]
        }

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
