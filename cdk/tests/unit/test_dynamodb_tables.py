"""Tests for DynamoDB tables module."""

from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import App, Stack

from cdk.dynamodb_tables import create_dynamodb_tables


@pytest.fixture
def mock_stack():
    """Create a mock CDK stack."""
    app = App()
    return Stack(app, "TestStack")


@pytest.fixture
def mock_rn():
    """Create a mock resource naming function."""
    return lambda name: f"{name}-ue1-test"


class TestCreateDynamoDbTables:
    """Tests for create_dynamodb_tables function."""

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_returns_dict_with_all_tables(self, mock_table_class, mock_stack, mock_rn):
        """Function returns dictionary with all expected table keys."""
        # Mock table constructor to return unique mocks for each call
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        result = create_dynamodb_tables(mock_stack, mock_rn)

        assert "accounts_table" in result
        assert "catalogs_table" in result
        assert "profiles_table" in result
        assert "campaigns_table" in result
        assert "orders_table" in result
        assert "shares_table" in result
        assert "invites_table" in result
        assert "shared_campaigns_table" in result

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_creates_eight_tables(self, mock_table_class, mock_stack, mock_rn):
        """Function creates exactly 8 DynamoDB tables."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        assert mock_table_class.call_count == 8

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_accounts_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Accounts table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        # First call should be accounts table
        first_call = mock_table_class.call_args_list[0]
        assert first_call[1]["table_name"] == "kernelworx-accounts-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_catalogs_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Catalogs table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        # Second call should be catalogs table
        second_call = mock_table_class.call_args_list[1]
        assert second_call[1]["table_name"] == "kernelworx-catalogs-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_profiles_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Profiles table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        # Third call should be profiles table
        third_call = mock_table_class.call_args_list[2]
        assert third_call[1]["table_name"] == "kernelworx-profiles-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_shares_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Shares table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        fourth_call = mock_table_class.call_args_list[3]
        assert fourth_call[1]["table_name"] == "kernelworx-shares-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_invites_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Invites table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        fifth_call = mock_table_class.call_args_list[4]
        assert fifth_call[1]["table_name"] == "kernelworx-invites-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_campaigns_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Campaigns table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        sixth_call = mock_table_class.call_args_list[5]
        assert sixth_call[1]["table_name"] == "kernelworx-campaigns-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_orders_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Orders table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        seventh_call = mock_table_class.call_args_list[6]
        assert seventh_call[1]["table_name"] == "kernelworx-orders-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_shared_campaigns_table_has_correct_name(self, mock_table_class, mock_stack, mock_rn):
        """Shared campaigns table is named correctly using rn function."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        create_dynamodb_tables(mock_stack, mock_rn)

        eighth_call = mock_table_class.call_args_list[7]
        assert eighth_call[1]["table_name"] == "kernelworx-shared-campaigns-ue1-test"

    @patch("cdk.dynamodb_tables.ddb.Table")
    def test_tables_returned_match_created(self, mock_table_class, mock_stack, mock_rn):
        """Tables returned in dict match the ones created."""
        mock_tables = [MagicMock(name=f"table_{i}") for i in range(8)]
        mock_table_class.side_effect = mock_tables

        result = create_dynamodb_tables(mock_stack, mock_rn)

        # Verify returned tables match created ones
        assert result["accounts_table"] is mock_tables[0]
        assert result["catalogs_table"] is mock_tables[1]
        assert result["profiles_table"] is mock_tables[2]
        assert result["shares_table"] is mock_tables[3]
        assert result["invites_table"] is mock_tables[4]
        assert result["campaigns_table"] is mock_tables[5]
        assert result["orders_table"] is mock_tables[6]
        assert result["shared_campaigns_table"] is mock_tables[7]
