"""AppSync data source creation."""

from typing import TYPE_CHECKING

from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_iam as iam
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_dynamodb as dynamodb
    from aws_cdk import aws_lambda as lambda_


def create_dynamodb_datasources(
    scope: Construct,
    api: appsync.GraphqlApi,
    tables: dict[str, "dynamodb.ITable"],
) -> dict[str, appsync.DynamoDbDataSource]:
    """
    Create DynamoDB data sources for the AppSync API.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        tables: Dictionary of table name to DynamoDB table

    Returns:
        Dictionary of datasource name to DynamoDB data source
    """
    datasources: dict[str, appsync.DynamoDbDataSource] = {}

    # Multi-table datasources
    table_configs = [
        ("accounts", "AccountsDataSource"),
        ("catalogs", "CatalogsDataSource"),
        ("profiles", "ProfilesDataSource"),
        ("campaigns", "CampaignsDataSource"),
        ("orders", "OrdersDataSource"),
        ("shares", "SharesDataSource"),
        ("invites", "InvitesDataSource"),
        ("shared_campaigns", "SharedCampaignsDataSource"),
    ]

    for table_key, ds_name in table_configs:
        if table_key in tables:
            ds = api.add_dynamo_db_data_source(ds_name, table=tables[table_key])
            # Grant GSI permissions
            ds.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{tables[table_key].table_arn}/index/*"],
                )
            )
            datasources[table_key] = ds

    return datasources


def create_none_datasource(api: appsync.GraphqlApi) -> appsync.NoneDataSource:
    """Create NONE data source for computed fields."""
    return api.add_none_data_source("NoneDataSource", name="NoneDataSource")


def create_lambda_datasources(
    api: appsync.GraphqlApi,
    lambda_functions: dict[str, "lambda_.IFunction"],
) -> dict[str, appsync.LambdaDataSource]:
    """
    Create Lambda data sources for the AppSync API.

    Args:
        api: The AppSync GraphQL API
        lambda_functions: Dictionary of function name to Lambda function

    Returns:
        Dictionary of datasource name to Lambda data source
    """
    datasources: dict[str, appsync.LambdaDataSource] = {}

    lambda_ds_configs = [
        ("list_my_shares_fn", "ListMySharesDS"),
        ("create_profile_fn", "CreateProfileDS"),
        ("request_campaign_report_fn", "RequestCampaignReportDS"),
        ("unit_reporting_fn", "UnitReportingDS"),
        ("list_unit_catalogs_fn", "ListUnitCatalogsDS"),
        ("list_unit_campaign_catalogs_fn", "ListUnitCampaignCatalogsDS"),
        ("campaign_operations_fn", "CampaignOperationsDS"),
        ("update_my_account_fn", "UpdateMyAccountDS"),
        ("transfer_ownership_fn", "TransferOwnershipDS"),
        ("request_qr_upload_fn", "RequestQRUploadDS"),
        ("confirm_qr_upload_fn", "ConfirmQRUploadDS"),
        ("generate_qr_code_presigned_url_fn", "GenerateQRCodePresignedURLDS"),
        ("delete_qr_code_fn", "DeleteQRCodeDS"),
        ("validate_payment_method_fn", "ValidatePaymentMethodDS"),
    ]

    for fn_key, ds_name in lambda_ds_configs:
        if fn_key in lambda_functions:
            datasources[fn_key] = api.add_lambda_data_source(ds_name, lambda_function=lambda_functions[fn_key])
    
    return datasources
