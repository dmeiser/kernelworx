"""Tests for the dynamodb_tables module."""

import pytest
from aws_cdk import App, Stack, assertions
from aws_cdk import aws_dynamodb as dynamodb

from cdk.dynamodb_tables import create_dynamodb_tables


class TestCreateDynamoDBTables:
    """Tests for create_dynamodb_tables function."""

    @pytest.fixture
    def stack(self):
        """Create a test stack."""
        app = App()
        return Stack(app, "TestStack")

    @pytest.fixture
    def rn(self):
        """Create a resource naming function."""

        def _rn(name: str) -> str:
            return f"{name}-ue1-test"

        return _rn

    def test_returns_dict_with_all_tables(self, stack, rn):
        """Should return a dict with all expected tables."""
        result = create_dynamodb_tables(stack, rn)

        expected_keys = [
            "table",
            "accounts_table",
            "catalogs_table",
            "profiles_table",
            "shares_table",
            "invites_table",
            "campaigns_table",
            "orders_table",
            "shared_campaigns_table",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"
            assert isinstance(result[key], dynamodb.Table), f"{key} is not a Table"

    def test_main_table_has_correct_name(self, stack, rn):
        """Main table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-app-ue1-test"})

    def test_accounts_table_has_correct_name(self, stack, rn):
        """Accounts table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-accounts-ue1-test"})

    def test_catalogs_table_has_correct_name(self, stack, rn):
        """Catalogs table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-catalogs-ue1-test"})

    def test_profiles_table_has_correct_name(self, stack, rn):
        """Profiles table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-profiles-ue1-test"})

    def test_shares_table_has_correct_name(self, stack, rn):
        """Shares table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-shares-ue1-test"})

    def test_invites_table_has_correct_name(self, stack, rn):
        """Invites table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-invites-ue1-test"})

    def test_campaigns_table_has_correct_name(self, stack, rn):
        """Campaigns table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-campaigns-ue1-test"})

    def test_orders_table_has_correct_name(self, stack, rn):
        """Orders table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-orders-ue1-test"})

    def test_shared_campaigns_table_has_correct_name(self, stack, rn):
        """Shared campaigns table should have correct name in CloudFormation template."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-shared-campaigns-ue1-test"})

    def test_all_tables_use_pay_per_request(self, stack, rn):
        """All tables should use PAY_PER_REQUEST billing mode."""
        create_dynamodb_tables(stack, rn)
        template = assertions.Template.from_stack(stack)
        # Check that all tables use PAY_PER_REQUEST (no ProvisionedThroughput)
        template.resource_count_is("AWS::DynamoDB::Table", 9)

    def test_different_resource_namer(self, stack):
        """Should work with different resource naming function."""

        def custom_rn(name: str) -> str:
            return f"{name}-custom-prod"

        create_dynamodb_tables(stack, custom_rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-app-custom-prod"})
        template.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "kernelworx-accounts-custom-prod"})
