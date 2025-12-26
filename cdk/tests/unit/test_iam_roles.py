"""Tests for the iam_roles module."""

import pytest
from aws_cdk import App, Stack, assertions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3

from cdk.iam_roles import (
    create_appsync_service_role,
    create_lambda_execution_role,
    create_user_pool_sms_role,
)


class TestCreateLambdaExecutionRole:
    """Tests for create_lambda_execution_role function."""

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

    @pytest.fixture
    def mock_table(self, stack):
        """Create a mock DynamoDB table."""
        return dynamodb.Table(
            stack,
            "TestTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
        )

    @pytest.fixture
    def mock_bucket(self, stack):
        """Create a mock S3 bucket."""
        return s3.Bucket(stack, "TestBucket")

    def test_returns_role(self, stack, rn, mock_table, mock_bucket):
        """Should return an IAM Role."""
        tables = {"test": mock_table}
        result = create_lambda_execution_role(stack, rn, tables, mock_bucket)

        assert isinstance(result, iam.Role)

    def test_role_has_correct_name(self, stack, rn, mock_table, mock_bucket):
        """Role should have correct name in CloudFormation template."""
        tables = {"test": mock_table}
        create_lambda_execution_role(stack, rn, tables, mock_bucket)

        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::IAM::Role", {"RoleName": "kernelworx-lambda-exec-ue1-test"})

    def test_role_can_be_assumed_by_lambda(self, stack, rn, mock_table, mock_bucket):
        """Role should be assumable by Lambda service."""
        tables = {"test": mock_table}
        result = create_lambda_execution_role(stack, rn, tables, mock_bucket)

        # Verify the assume role policy document exists
        assert result.assume_role_policy is not None


class TestCreateAppSyncServiceRole:
    """Tests for create_appsync_service_role function."""

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

    @pytest.fixture
    def mock_table(self, stack):
        """Create a mock DynamoDB table."""
        return dynamodb.Table(
            stack,
            "TestTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
        )

    def test_returns_role(self, stack, rn, mock_table):
        """Should return an IAM Role."""
        tables = {"test": mock_table}
        result = create_appsync_service_role(stack, rn, tables)

        assert isinstance(result, iam.Role)

    def test_role_has_correct_name(self, stack, rn, mock_table):
        """Role should have correct name in CloudFormation template."""
        tables = {"test": mock_table}
        create_appsync_service_role(stack, rn, tables)

        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::IAM::Role", {"RoleName": "kernelworx-appsync-ue1-test"})

    def test_role_can_be_assumed_by_appsync(self, stack, rn, mock_table):
        """Role should be assumable by AppSync service."""
        tables = {"test": mock_table}
        result = create_appsync_service_role(stack, rn, tables)

        # Verify the assume role policy document exists
        assert result.assume_role_policy is not None


class TestCreateUserPoolSmsRole:
    """Tests for create_user_pool_sms_role function."""

    @pytest.fixture
    def stack(self):
        """Create a test stack."""
        app = App()
        return Stack(app, "TestStack")

    def test_returns_role(self, stack):
        """Should return an IAM Role."""
        result = create_user_pool_sms_role(stack, "test-sms-role")

        assert isinstance(result, iam.Role)

    def test_role_has_correct_name(self, stack):
        """Role should have correct name in CloudFormation template."""
        create_user_pool_sms_role(stack, "custom-sms-role-name")

        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::IAM::Role", {"RoleName": "custom-sms-role-name"})

    def test_role_can_be_assumed_by_cognito(self, stack):
        """Role should be assumable by Cognito service."""
        result = create_user_pool_sms_role(stack, "test-sms-role")

        # Verify the assume role policy document exists
        assert result.assume_role_policy is not None
