"""Lambda function definitions for the Popcorn Sales Manager stack.

This module creates all Lambda functions used by the application:
- Post-authentication and pre-signup Cognito triggers
- Profile operations (create profile)
- Campaign operations (create campaign with transaction support)
- Order operations (report generation, unit reporting)
- Account operations (update account)
- Profile sharing (list my shares)
- Catalog operations (list unit catalogs)
"""

import os
from typing import TYPE_CHECKING, Any

from aws_cdk import Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_dynamodb as dynamodb
    from aws_cdk import aws_s3 as s3


def create_lambda_functions(
    scope: Construct,
    rn: Any,  # Resource naming function
    lambda_execution_role: iam.Role,
    table: "dynamodb.Table",
    accounts_table: "dynamodb.Table",
    catalogs_table: "dynamodb.Table",
    profiles_table: "dynamodb.Table",
    campaigns_table: "dynamodb.Table",
    orders_table: "dynamodb.Table",
    shares_table: "dynamodb.Table",
    invites_table: "dynamodb.Table",
    exports_bucket: "s3.Bucket",
) -> dict[str, lambda_.Function | lambda_.LayerVersion]:
    """Create all Lambda functions for the stack.

    Args:
        scope: CDK construct scope
        rn: Resource naming function (name -> formatted name)
        lambda_execution_role: IAM role for Lambda execution
        table: Main DynamoDB table (legacy single-table)
        accounts_table: Accounts DynamoDB table
        catalogs_table: Catalogs DynamoDB table
        profiles_table: Profiles DynamoDB table
        campaigns_table: Campaigns DynamoDB table
        orders_table: Orders DynamoDB table
        shares_table: Shares DynamoDB table
        invites_table: Invites DynamoDB table
        exports_bucket: S3 bucket for exports

    Returns:
        Dictionary containing all Lambda functions and layer
    """
    # Common Lambda environment variables
    lambda_env = {
        "TABLE_NAME": table.table_name,
        "EXPORTS_BUCKET": exports_bucket.bucket_name,
        "POWERTOOLS_SERVICE_NAME": "kernelworx",
        "LOG_LEVEL": "INFO",
        # New multi-table design table names
        "ACCOUNTS_TABLE_NAME": accounts_table.table_name,
        "CATALOGS_TABLE_NAME": catalogs_table.table_name,
        "PROFILES_TABLE_NAME": profiles_table.table_name,
        "CAMPAIGNS_TABLE_NAME": campaigns_table.table_name,
        "ORDERS_TABLE_NAME": orders_table.table_name,
        "SHARES_TABLE_NAME": shares_table.table_name,
        "INVITES_TABLE_NAME": invites_table.table_name,
    }

    # Create Lambda Layer for shared dependencies
    lambda_layer_path = os.path.join(os.path.dirname(__file__), "..", "lambda-layer")

    # Check if layer exists, if not create it
    if not os.path.exists(lambda_layer_path):
        os.makedirs(lambda_layer_path, exist_ok=True)

    shared_layer = lambda_.LayerVersion(
        scope,
        "SharedDependenciesLayer",
        layer_version_name=rn("kernelworx-deps"),
        code=lambda_.Code.from_asset(lambda_layer_path),
        compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
        description="Shared Python dependencies for Lambda functions",
    )

    # Use only the src directory for Lambda code (not the entire repo)
    lambda_code_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")

    lambda_code = lambda_.Code.from_asset(
        lambda_code_path,
        exclude=[
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
        ],
    )

    # Profile Sharing Lambda Functions
    # NOTE: create_profile_invite Lambda REMOVED - replaced with JS resolver
    # NOTE: redeem_profile_invite Lambda REMOVED - replaced with pipeline resolver
    # NOTE: share_profile_direct Lambda REMOVED - replaced with pipeline resolver
    # NOTE: revoke_share Lambda REMOVED - replaced with VTL DynamoDB resolver
    # NOTE: update_campaign, delete_campaign Lambdas REMOVED - replaced with JS pipeline resolvers

    # List My Shares Lambda - uses Lambda due to AppSync BatchGetItem intermittent issues
    list_my_shares_fn = lambda_.Function(
        scope,
        "ListMySharesFn",
        function_name=rn("kernelworx-list-my-shares"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.profile_sharing.list_my_shares",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(30),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Order Operations Lambda Functions
    # NOTE: create_order Lambda REMOVED - replaced with pipeline resolver

    create_profile_fn = lambda_.Function(
        scope,
        "CreateProfileFnV2",
        function_name=rn("kernelworx-create-profile"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.scout_operations.create_seller_profile",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(30),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    request_campaign_report_fn = lambda_.Function(
        scope,
        "RequestCampaignReportFnV2",
        function_name=rn("kernelworx-request-report"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.report_generation.request_campaign_report",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(60),  # Reports may take longer
        memory_size=512,  # More memory for Excel generation
        role=lambda_execution_role,
        environment=lambda_env,
    )

    unit_reporting_fn = lambda_.Function(
        scope,
        "UnitReportingFnV2",
        function_name=rn("kernelworx-unit-reporting"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.campaign_reporting.get_unit_report",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(60),  # May need time for large units
        memory_size=512,  # More memory for aggregation
        role=lambda_execution_role,
        environment=lambda_env,
    )

    list_unit_catalogs_fn = lambda_.Function(
        scope,
        "ListUnitCatalogsFn",
        function_name=rn("kernelworx-list-unit-catalogs"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.list_unit_catalogs.list_unit_catalogs",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(30),
        memory_size=512,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # New list_unit_campaign_catalogs Lambda (uses unitCampaignKey-index for campaign-based queries)
    list_unit_campaign_catalogs_fn = lambda_.Function(
        scope,
        "ListUnitCampaignCatalogsFn",
        function_name=rn("kernelworx-list-unit-campaign-catalogs"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.list_unit_catalogs.list_unit_campaign_catalogs",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(30),
        memory_size=512,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Campaign Operations Lambda (with transaction support for Shared Campaign + share creation)
    campaign_operations_fn = lambda_.Function(
        scope,
        "CampaignOperationsFn",
        function_name=rn("kernelworx-campaign-operations"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.campaign_operations.create_campaign",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(30),
        memory_size=512,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Account Operations Lambda Functions
    update_my_account_fn = lambda_.Function(
        scope,
        "UpdateMyAccountFnV2",
        function_name=rn("kernelworx-update-account"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.account_operations.update_my_account",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Post-Authentication Lambda (Cognito Trigger)
    post_auth_fn = lambda_.Function(
        scope,
        "PostAuthenticationFnV2",
        function_name=rn("kernelworx-post-auth"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.post_authentication.lambda_handler",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Pre-Signup Lambda (Cognito Trigger)
    # Links federated identities (Google, Facebook, Apple) to existing users
    # with the same email to prevent duplicate accounts
    pre_signup_fn = lambda_.Function(
        scope,
        "PreSignupFn",
        function_name=rn("kernelworx-pre-signup"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.pre_signup.lambda_handler",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Payment Methods Lambda Functions
    request_qr_upload_fn = lambda_.Function(
        scope,
        "RequestQRUploadFn",
        function_name=rn("kernelworx-request-qr-upload"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.payment_methods_handlers.request_qr_upload",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    confirm_qr_upload_fn = lambda_.Function(
        scope,
        "ConfirmQRUploadFn",
        function_name=rn("kernelworx-confirm-qr-upload"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.payment_methods_handlers.confirm_qr_upload",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    # Field resolver for PaymentMethod.qrCodeUrl - generates presigned URL on-demand
    generate_qr_code_presigned_url_fn = lambda_.Function(
        scope,
        "GenerateQRCodePresignedURLFn",
        function_name=rn("kernelworx-generate-qr-code-presigned-url"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.generate_qr_code_presigned_url.generate_qr_code_presigned_url",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(3),
        memory_size=128,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    delete_qr_code_fn = lambda_.Function(
        scope,
        "DeleteQRCodeFn",
        function_name=rn("kernelworx-delete-qr-code"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.payment_methods_handlers.delete_qr_code",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    validate_payment_method_fn = lambda_.Function(
        scope,
        "ValidatePaymentMethodFn",
        function_name=rn("kernelworx-validate-payment-method"),
        runtime=lambda_.Runtime.PYTHON_3_13,
        handler="handlers.validate_payment_method.lambda_handler",
        code=lambda_code,
        layers=[shared_layer],
        timeout=Duration.seconds(10),
        memory_size=256,
        role=lambda_execution_role,
        environment=lambda_env,
    )

    return {
        "shared_layer": shared_layer,
        "list_my_shares_fn": list_my_shares_fn,
        "create_profile_fn": create_profile_fn,
        "request_campaign_report_fn": request_campaign_report_fn,
        "unit_reporting_fn": unit_reporting_fn,
        "list_unit_catalogs_fn": list_unit_catalogs_fn,
        "list_unit_campaign_catalogs_fn": list_unit_campaign_catalogs_fn,
        "campaign_operations_fn": campaign_operations_fn,
        "update_my_account_fn": update_my_account_fn,
        "post_auth_fn": post_auth_fn,
        "pre_signup_fn": pre_signup_fn,
        "request_qr_upload_fn": request_qr_upload_fn,
        "confirm_qr_upload_fn": confirm_qr_upload_fn,
        "generate_qr_code_presigned_url_fn": generate_qr_code_presigned_url_fn,
        "delete_qr_code_fn": delete_qr_code_fn,
        "validate_payment_method_fn": validate_payment_method_fn,
    }
