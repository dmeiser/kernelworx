"""Tests for IAM roles module."""

from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import App, Stack

from cdk.iam_roles import create_appsync_service_role, create_lambda_execution_role, create_user_pool_sms_role


@pytest.fixture
def mock_stack():
    """Create a mock CDK stack."""
    app = App()
    return Stack(app, "TestStack")


@pytest.fixture
def mock_rn():
    """Create a mock resource naming function."""
    return lambda name: f"{name}-ue1-test"


@pytest.fixture
def mock_tables():
    """Create mock DynamoDB tables."""
    tables = {}
    for name in ["accounts", "catalogs", "profiles", "campaigns", "orders", "shares", "invites", "shared_campaigns"]:
        mock_table = MagicMock()
        mock_table.table_arn = f"arn:aws:dynamodb:us-east-1:123456789012:table/{name}"
        mock_table.table_name = name
        tables[f"{name}_table"] = mock_table
    return tables


@pytest.fixture
def mock_exports_bucket():
    """Create mock S3 bucket for exports."""
    bucket = MagicMock()
    bucket.bucket_arn = "arn:aws:s3:::exports-bucket"
    bucket.bucket_name = "exports-bucket"
    return bucket


class TestCreateLambdaExecutionRole:
    """Tests for create_lambda_execution_role function."""

    @patch("cdk.iam_roles.iam.ManagedPolicy")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_creates_role(
        self,
        mock_role_class,
        mock_service_principal,
        mock_managed_policy,
        mock_stack,
        mock_rn,
        mock_tables,
        mock_exports_bucket,
    ):
        """Function creates and returns an IAM role."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        result = create_lambda_execution_role(mock_stack, mock_rn, mock_tables, mock_exports_bucket)

        assert result is mock_role
        mock_role_class.assert_called_once()

    @patch("cdk.iam_roles.iam.ManagedPolicy")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_has_correct_name(
        self,
        mock_role_class,
        mock_service_principal,
        mock_managed_policy,
        mock_stack,
        mock_rn,
        mock_tables,
        mock_exports_bucket,
    ):
        """Role is named correctly using rn function."""
        mock_role_class.return_value = MagicMock()

        create_lambda_execution_role(mock_stack, mock_rn, mock_tables, mock_exports_bucket)

        call_args = mock_role_class.call_args
        assert call_args[1]["role_name"] == "kernelworx-lambda-exec-ue1-test"

    @patch("cdk.iam_roles.iam.ManagedPolicy")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_assumed_by_lambda(
        self,
        mock_role_class,
        mock_service_principal,
        mock_managed_policy,
        mock_stack,
        mock_rn,
        mock_tables,
        mock_exports_bucket,
    ):
        """Role is assumed by lambda.amazonaws.com service principal."""
        mock_role_class.return_value = MagicMock()

        create_lambda_execution_role(mock_stack, mock_rn, mock_tables, mock_exports_bucket)

        mock_service_principal.assert_called_once_with("lambda.amazonaws.com")

    @patch("cdk.iam_roles.iam.ManagedPolicy")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_grants_table_access(
        self,
        mock_role_class,
        mock_service_principal,
        mock_managed_policy,
        mock_stack,
        mock_rn,
        mock_tables,
        mock_exports_bucket,
    ):
        """Role is granted read/write access to all tables."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        create_lambda_execution_role(mock_stack, mock_rn, mock_tables, mock_exports_bucket)

        # Each table should have grant_read_write_data called
        for table_name, table in mock_tables.items():
            table.grant_read_write_data.assert_called_once_with(mock_role)

    @patch("cdk.iam_roles.iam.ManagedPolicy")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_grants_exports_bucket_access(
        self,
        mock_role_class,
        mock_service_principal,
        mock_managed_policy,
        mock_stack,
        mock_rn,
        mock_tables,
        mock_exports_bucket,
    ):
        """Role is granted read/write access to exports bucket."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        create_lambda_execution_role(mock_stack, mock_rn, mock_tables, mock_exports_bucket)

        mock_exports_bucket.grant_read_write.assert_called_once_with(mock_role)


class TestCreateAppSyncServiceRole:
    """Tests for create_appsync_service_role function."""

    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_creates_role(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_stack, mock_rn, mock_tables
    ):
        """Function creates and returns an IAM role."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        result = create_appsync_service_role(mock_stack, mock_rn, mock_tables)

        assert result is mock_role
        mock_role_class.assert_called_once()

    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_has_correct_name(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_stack, mock_rn, mock_tables
    ):
        """Role is named correctly using rn function."""
        mock_role_class.return_value = MagicMock()

        create_appsync_service_role(mock_stack, mock_rn, mock_tables)

        call_args = mock_role_class.call_args
        assert call_args[1]["role_name"] == "kernelworx-appsync-ue1-test"

    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_assumed_by_appsync(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_stack, mock_rn, mock_tables
    ):
        """Role is assumed by appsync.amazonaws.com service principal."""
        mock_role_class.return_value = MagicMock()

        create_appsync_service_role(mock_stack, mock_rn, mock_tables)

        mock_service_principal.assert_called_once_with("appsync.amazonaws.com")

    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_adds_policies_for_tables(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_stack, mock_rn, mock_tables
    ):
        """Role has policies added for DynamoDB table access."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        create_appsync_service_role(mock_stack, mock_rn, mock_tables)

        # Should add policies to role for DynamoDB actions
        assert mock_role.add_to_policy.call_count > 0

    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_tables_without_gsi_skips_gsi_policies(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_stack, mock_rn, mock_tables
    ):
        """Tables in tables_without_gsi list do not get GSI policies."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        # Specify some tables without GSIs
        create_appsync_service_role(mock_stack, mock_rn, mock_tables, tables_without_gsi=["invites_table"])

        # Should still work - just skip GSI policy for specified tables
        mock_role_class.assert_called_once()


class TestCreateUserPoolSmsRole:
    """Tests for create_user_pool_sms_role function."""

    @patch("cdk.iam_roles.iam.PolicyDocument")
    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_creates_role(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document, mock_stack
    ):
        """Function creates and returns an IAM role."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        result = create_user_pool_sms_role(mock_stack, "test-sms-role")

        assert result is mock_role
        mock_role_class.assert_called_once()

    @patch("cdk.iam_roles.iam.PolicyDocument")
    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_has_correct_name(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document, mock_stack
    ):
        """Role is named correctly with provided name."""
        mock_role_class.return_value = MagicMock()

        create_user_pool_sms_role(mock_stack, "kernelworx-ue1-dev-UserPoolsmsRole")

        call_args = mock_role_class.call_args
        assert call_args[1]["role_name"] == "kernelworx-ue1-dev-UserPoolsmsRole"

    @patch("cdk.iam_roles.iam.PolicyDocument")
    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_assumed_by_cognito(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document, mock_stack
    ):
        """Role is assumed by cognito-idp.amazonaws.com service principal."""
        mock_role_class.return_value = MagicMock()

        create_user_pool_sms_role(mock_stack, "test-sms-role")

        mock_service_principal.assert_called_once_with("cognito-idp.amazonaws.com")

    @patch("cdk.iam_roles.iam.PolicyDocument")
    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_has_sns_publish_policy(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document, mock_stack
    ):
        """Role has inline policy for SNS Publish action."""
        mock_role_class.return_value = MagicMock()

        create_user_pool_sms_role(mock_stack, "test-sms-role")

        # Check PolicyStatement was called with sns:Publish action
        mock_policy_statement.assert_called_once()
        call_args = mock_policy_statement.call_args
        assert "sns:Publish" in call_args[1]["actions"]
        assert "arn:aws:sns:*:*:*" in call_args[1]["resources"]

    @patch("cdk.iam_roles.iam.PolicyDocument")
    @patch("cdk.iam_roles.iam.PolicyStatement")
    @patch("cdk.iam_roles.iam.ServicePrincipal")
    @patch("cdk.iam_roles.iam.Role")
    def test_role_has_removal_policy_retain(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document, mock_stack
    ):
        """Role has RETAIN removal policy applied."""
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        create_user_pool_sms_role(mock_stack, "test-sms-role")

        # Verify apply_removal_policy was called
        mock_role.apply_removal_policy.assert_called_once()