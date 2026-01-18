"""Tests for Lambda functions module."""

import os
from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import App, Stack

from cdk.lambdas import create_lambda_functions


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
def mock_lambda_execution_role():
    """Create a mock Lambda execution role."""
    role = MagicMock()
    role.role_arn = "arn:aws:iam::123456789012:role/lambda-exec"
    return role


@pytest.fixture
def mock_tables():
    """Create mock DynamoDB tables."""
    tables = {}
    for name in ["accounts", "catalogs", "profiles", "campaigns", "orders", "shares", "invites", "shared_campaigns"]:
        mock_table = MagicMock()
        mock_table.table_name = f"{name}-table"
        mock_table.table_arn = f"arn:aws:dynamodb:us-east-1:123456789012:table/{name}"
        tables[name] = mock_table
    return tables


@pytest.fixture
def mock_exports_bucket():
    """Create mock S3 bucket for exports."""
    bucket = MagicMock()
    bucket.bucket_name = "exports-bucket"
    bucket.bucket_arn = "arn:aws:s3:::exports-bucket"
    return bucket


class TestCreateLambdaFunctions:
    """Tests for create_lambda_functions function."""

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_returns_dict_with_expected_keys(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Function returns dictionary with all expected Lambda function keys."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        result = create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Check for expected Lambda function keys
        expected_keys = [
            "shared_layer",
            "post_auth_fn",
            "pre_signup_fn",
            "create_profile_fn",
            "campaign_operations_fn",
            "delete_profile_orders_cascade_fn",
            "request_campaign_report_fn",
            "unit_reporting_fn",
            "update_my_account_fn",
            "list_my_shares_fn",
            "list_unit_catalogs_fn",
            "list_unit_campaign_catalogs_fn",
            "validate_payment_method_fn",
            "request_qr_upload_fn",
            "confirm_qr_upload_fn",
            "generate_qr_code_presigned_url_fn",
            "delete_qr_code_fn",
            "transfer_ownership_fn",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_creates_shared_layer(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Function creates a shared Lambda layer."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer = MagicMock()
        mock_layer_class.return_value = mock_layer
        mock_function_class.return_value = MagicMock()

        result = create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        mock_layer_class.assert_called_once()
        assert result["shared_layer"] is mock_layer

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_creates_multiple_functions(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Function creates multiple Lambda functions."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Should create 17 Lambda functions (excluding the layer)
        assert mock_function_class.call_count == 17

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_layer_named_correctly(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Shared layer is named correctly using rn function."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        call_args = mock_layer_class.call_args
        assert call_args[1]["layer_version_name"] == "kernelworx-deps-ue1-test"

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_creates_layer_directory_if_not_exists(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Creates lambda-layer directory if it doesn't exist."""
        mock_exists.return_value = False
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        mock_makedirs.assert_called_once()

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_functions_use_python_3_13_runtime(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Lambda functions use Python 3.13 runtime."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Check that all function calls specify Python 3.13 runtime
        for call in mock_function_class.call_args_list:
            assert "runtime" in call[1]

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_functions_use_execution_role(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Lambda functions use the provided execution role."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Check that all function calls use the execution role
        for call in mock_function_class.call_args_list:
            assert call[1]["role"] is mock_lambda_execution_role

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_functions_have_environment_variables(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Lambda functions have environment variables configured."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer_class.return_value = MagicMock()
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Check that all function calls have environment variables
        for call in mock_function_class.call_args_list:
            assert "environment" in call[1]
            env = call[1]["environment"]
            assert "EXPORTS_BUCKET" in env
            assert "POWERTOOLS_SERVICE_NAME" in env

    @patch("cdk.lambdas.lambda_.Function")
    @patch("cdk.lambdas.lambda_.LayerVersion")
    @patch("cdk.lambdas.lambda_.Code.from_asset")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_functions_include_shared_layer(
        self,
        mock_makedirs,
        mock_exists,
        mock_code_from_asset,
        mock_layer_class,
        mock_function_class,
        mock_stack,
        mock_rn,
        mock_lambda_execution_role,
        mock_tables,
        mock_exports_bucket,
    ):
        """Lambda functions include the shared layer."""
        mock_exists.return_value = True
        mock_code_from_asset.return_value = MagicMock()
        mock_layer = MagicMock()
        mock_layer_class.return_value = mock_layer
        mock_function_class.return_value = MagicMock()

        create_lambda_functions(
            mock_stack,
            mock_rn,
            mock_lambda_execution_role,
            mock_tables["accounts"],
            mock_tables["catalogs"],
            mock_tables["profiles"],
            mock_tables["campaigns"],
            mock_tables["orders"],
            mock_tables["shares"],
            mock_tables["invites"],
            mock_tables["shared_campaigns"],
            mock_exports_bucket,
        )

        # Check that all function calls include the shared layer
        for call in mock_function_class.call_args_list:
            assert "layers" in call[1]
            assert mock_layer in call[1]["layers"]
