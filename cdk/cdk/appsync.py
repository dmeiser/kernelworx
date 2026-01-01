"""
AppSync GraphQL API module for kernelworx.

This module creates the AppSync GraphQL API, datasources, functions, and resolvers.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_iam as iam
from aws_cdk import aws_route53 as route53
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_cognito as cognito
    from aws_cdk import aws_dynamodb as dynamodb
    from aws_cdk import aws_lambda as lambda_


# Path to resolvers directory (relative to this file)
RESOLVERS_DIR = Path(__file__).parent / "resolvers"


@dataclass
class AppSyncResources:
    """Container for all AppSync resources created by setup_appsync."""

    api: appsync.GraphqlApi
    dynamodb_datasources: dict[str, appsync.DynamoDbDataSource]
    lambda_datasources: dict[str, appsync.LambdaDataSource]
    none_datasource: appsync.NoneDataSource
    functions: dict[str, appsync.AppsyncFunction]
    profile_delete_functions: dict[str, appsync.AppsyncFunction]
    domain_name: appsync.CfnDomainName | None
    domain_association: Any | None
    dns_record: Any | None


def setup_appsync(
    scope: Construct,
    env_name: str,
    resource_name: Any,  # Callable[[str], str]
    user_pool: "cognito.IUserPool",
    api_domain: str,
    api_certificate: Any,
    hosted_zone: "route53.IHostedZone",
    tables: dict[str, "dynamodb.ITable"],
    lambda_functions: dict[str, "lambda_.IFunction"],
) -> AppSyncResources:
    """
    Set up the complete AppSync GraphQL API infrastructure.

    This is the main entry point for creating all AppSync resources.

    Args:
        scope: CDK construct scope
        env_name: Environment name (dev, prod, etc.)
        resource_name: Function to generate resource names
        user_pool: Cognito User Pool for authentication
        api_domain: Custom domain for the API
        api_certificate: ACM certificate for the custom domain
        hosted_zone: Route53 hosted zone for DNS records
        tables: Dictionary of DynamoDB tables
        lambda_functions: Dictionary of Lambda functions

    Returns:
        AppSyncResources containing all created resources
    """
    # Create the GraphQL API
    api = create_appsync_api(
        scope=scope,
        env_name=env_name,
        resource_name=resource_name,
        user_pool=user_pool,
        api_domain=api_domain,
        api_certificate=api_certificate,
        hosted_zone=hosted_zone,
    )

    # Create DynamoDB data sources
    dynamodb_datasources = create_dynamodb_datasources(scope, api, tables)

    # Create NONE data source for computed fields
    none_datasource = create_none_datasource(api)
    dynamodb_datasources["none"] = none_datasource  # type: ignore

    # Create Lambda data sources
    lambda_datasources = create_lambda_datasources(api, lambda_functions)

    # Create AppSync functions
    functions = create_appsync_functions(scope, api, env_name, dynamodb_datasources)

    # Create profile delete functions
    profile_delete_functions = create_profile_delete_functions(
        scope, api, env_name, dynamodb_datasources
    )

    # Create all resolvers
    create_resolvers(
        scope=scope,
        api=api,
        env_name=env_name,
        datasources=dynamodb_datasources,
        lambda_datasources=lambda_datasources,
        functions=functions,
        profile_delete_functions=profile_delete_functions,
    )

    # Create custom domain (if certificate available)
    domain_name, domain_association, dns_record = create_appsync_custom_domain(
        scope=scope,
        api=api,
        api_domain=api_domain,
        api_certificate=api_certificate,
        hosted_zone=hosted_zone,
    )

    return AppSyncResources(
        api=api,
        dynamodb_datasources=dynamodb_datasources,
        lambda_datasources=lambda_datasources,
        none_datasource=none_datasource,
        functions=functions,
        profile_delete_functions=profile_delete_functions,
        domain_name=domain_name,
        domain_association=domain_association,
        dns_record=dns_record,
    )


def create_appsync_api(
    scope: Construct,
    env_name: str,
    resource_name: Any,  # Callable[[str], str]
    user_pool: "cognito.IUserPool",
    api_domain: str,
    api_certificate: Any,  # ICertificate
    hosted_zone: "route53.IHostedZone",
) -> appsync.GraphqlApi:
    """
    Create the AppSync GraphQL API with authorization.

    Args:
        scope: CDK construct scope
        env_name: Environment name (dev, prod, etc.)
        resource_name: Function to generate resource names
        user_pool: Cognito User Pool for authentication
        api_domain: Custom domain for the API
        api_certificate: ACM certificate for the custom domain
        hosted_zone: Route53 hosted zone for DNS records

    Returns:
        The created GraphQL API
    """
    # Read GraphQL schema from file
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "schema.graphql")

    # Determine if logging should be enabled
    enable_appsync_logging = os.getenv("ENABLE_APPSYNC_LOGGING", "true").lower() == "true"

    # Create AppSync GraphQL API
    api_name = resource_name("kernelworx-api")
    print(f"Creating AppSync API: {api_name}")

    api = appsync.GraphqlApi(
        scope,
        "Api",
        name=api_name,
        definition=appsync.Definition.from_file(schema_path),
        authorization_config=appsync.AuthorizationConfig(
            default_authorization=appsync.AuthorizationMode(
                authorization_type=appsync.AuthorizationType.USER_POOL,
                user_pool_config=appsync.UserPoolConfig(user_pool=user_pool),
            ),
        ),
        xray_enabled=True,
        log_config=(
            appsync.LogConfig(
                field_log_level=appsync.FieldLogLevel.ALL,
                exclude_verbose_content=False,
            )
            if enable_appsync_logging
            else None
        ),
    )
    api.apply_removal_policy(RemovalPolicy.RETAIN)

    CfnOutput(
        scope,
        "AppSyncApiKey",
        value="NOT_AVAILABLE",
        description="AppSync API Key for unauthenticated access to public catalogs",
    )

    return api


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
        ("create_profile", "CreateProfileDS"),
        ("request_campaign_report", "RequestCampaignReportDS"),
        ("unit_reporting", "UnitReportingDS"),
        ("list_unit_catalogs", "ListUnitCatalogsDS"),
        ("list_unit_campaign_catalogs", "ListUnitCampaignCatalogsDS"),
        ("campaign_operations", "CampaignOperationsDS"),
        ("update_my_account", "UpdateMyAccountDS"),
        ("transfer_ownership", "TransferOwnershipDS"),
    ]

    for fn_key, ds_name in lambda_ds_configs:
        if fn_key in lambda_functions:
            datasources[fn_key] = api.add_lambda_data_source(
                ds_name, lambda_function=lambda_functions[fn_key]
            )

    return datasources


def create_appsync_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for pipeline resolvers.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # === PROFILE SHARING FUNCTIONS ===

    # VerifyProfileOwnerForInviteFn
    functions["verify_profile_owner_for_invite"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForInviteFn",
        name=f"VerifyProfileOwnerForInviteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_invite_fn.js")),
    )

    # CreateInviteFn
    functions["create_invite"] = appsync.AppsyncFunction(
        scope,
        "CreateInviteFn",
        name=f"CreateInviteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_invite_fn.js")),
    )

    # VerifyProfileOwnerForRevokeFn
    functions["verify_profile_owner_for_revoke"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForRevokeFn",
        name=f"VerifyProfileOwnerForRevokeFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_revoke_fn.js")),
    )

    # DeleteShareFn
    functions["delete_share"] = appsync.AppsyncFunction(
        scope,
        "DeleteShareFn",
        name=f"DeleteShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_share_fn.js")),
    )

    # DeleteProfileInviteFn
    functions["delete_profile_invite"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileInviteFn",
        name=f"DeleteProfileInviteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_invite_fn.js")),
    )

    # DeleteInviteItemFn
    functions["delete_invite_item"] = appsync.AppsyncFunction(
        scope,
        "DeleteInviteItemFn",
        name=f"DeleteInviteItemFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_invite_item_fn.js")),
    )

    # === SHARED AUTHORIZATION FUNCTIONS ===

    # VerifyProfileWriteAccessFn
    functions["verify_profile_write_access"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileWriteAccessFn",
        name=f"VerifyProfileWriteAccessFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_write_access_fn.js")),
    )

    # CheckSharePermissionsFn
    functions["check_share_permissions"] = appsync.AppsyncFunction(
        scope,
        "CheckSharePermissionsFn",
        name=f"CheckSharePermissionsFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_share_permissions_fn.js")),
    )

    # VerifyProfileReadAccessFn
    functions["verify_profile_read_access"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileReadAccessFn",
        name=f"VerifyProfileReadAccessFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_read_access_fn.js")),
    )

    # CheckShareReadPermissionsFn
    functions["check_share_read_permissions"] = appsync.AppsyncFunction(
        scope,
        "CheckShareReadPermissionsFn",
        name=f"CheckShareReadPermissionsFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_share_read_permissions_fn.js")),
    )

    # === CAMPAIGN OPERATION FUNCTIONS ===

    # LookupCampaignFn
    functions["lookup_campaign"] = appsync.AppsyncFunction(
        scope,
        "LookupCampaignFn",
        name=f"LookupCampaignFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_campaign_fn.js")),
    )

    # UpdateCampaignFn
    functions["update_campaign"] = appsync.AppsyncFunction(
        scope,
        "UpdateCampaignFn",
        name=f"UpdateCampaignFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_campaign_fn.js")),
    )

    # LookupCampaignForDeleteFn
    functions["lookup_campaign_for_delete"] = appsync.AppsyncFunction(
        scope,
        "LookupCampaignForDeleteFn",
        name=f"LookupCampaignForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_campaign_for_delete_fn.js")),
    )

    # QueryCampaignOrdersForDeleteFn
    functions["query_campaign_orders_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryCampaignOrdersForDeleteFn",
        name=f"QueryCampaignOrdersForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_campaign_orders_for_delete_fn.js")),
    )

    # DeleteCampaignOrdersFn
    functions["delete_campaign_orders"] = appsync.AppsyncFunction(
        scope,
        "DeleteCampaignOrdersFn",
        name=f"DeleteCampaignOrdersFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_campaign_orders_fn.js")),
    )

    # DeleteCampaignFn
    functions["delete_campaign"] = appsync.AppsyncFunction(
        scope,
        "DeleteCampaignFn",
        name=f"DeleteCampaignFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_campaign_fn.js")),
    )

    # === ORDER OPERATION FUNCTIONS ===

    # LookupOrderFn
    functions["lookup_order"] = appsync.AppsyncFunction(
        scope,
        "LookupOrderFn",
        name=f"LookupOrderFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_order_fn.js")),
    )

    # GetCatalogForUpdateOrderFn
    functions["get_catalog_for_update_order"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogForUpdateOrderFn",
        name=f"GetCatalogForUpdateOrderFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_for_update_order_fn.js")),
    )

    # FetchCatalogForUpdateFn
    functions["fetch_catalog_for_update"] = appsync.AppsyncFunction(
        scope,
        "FetchCatalogForUpdateFn",
        name=f"FetchCatalogForUpdateFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "fetch_catalog_for_update_fn.js")),
    )

    # UpdateOrderFn
    functions["update_order"] = appsync.AppsyncFunction(
        scope,
        "UpdateOrderFn",
        name=f"UpdateOrderFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_order_fn.js")),
    )

    # LookupOrderForDeleteFn
    functions["lookup_order_for_delete"] = appsync.AppsyncFunction(
        scope,
        "LookupOrderForDeleteFn",
        name=f"LookupOrderForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_order_for_delete_fn.js")),
    )

    # DeleteOrderFn
    functions["delete_order"] = appsync.AppsyncFunction(
        scope,
        "DeleteOrderFn",
        name=f"DeleteOrderFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_order_fn.js")),
    )

    # GetCampaignForOrderFn
    functions["get_campaign_for_order"] = appsync.AppsyncFunction(
        scope,
        "GetCampaignForOrderFn",
        name=f"GetCampaignForOrderFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_campaign_for_order_fn.js")),
    )

    # EnsureCatalogForOrderFn (defensive): if stash.catalogId missing, query campaign and set it
    functions["ensure_catalog_for_order"] = appsync.AppsyncFunction(
        scope,
        "EnsureCatalogForOrderFn",
        name=f"EnsureCatalogForOrderFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "ensure_catalog_for_order_fn.js")),
    )

    # GetCatalogFn
    functions["get_catalog"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogFn",
        name=f"GetCatalogFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_fn.js")),
    )

    # GetCatalogTryRawFn - try raw catalogId before prefixed lookup
    functions["get_catalog_try_raw"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogTryRawFn",
        name=f"GetCatalogTryRawFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_try_raw_fn.js")),
    )

    # GetCatalogTryPrefixedFn - fallback prefixed lookup
    functions["get_catalog_try_prefixed"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogTryPrefixedFn",
        name=f"GetCatalogTryPrefixedFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_try_prefixed_fn.js")),
    )

    # Diagnostic function to help debug pipeline stash issues (dev-only)
    functions["diagnose_catalog_for_order"] = appsync.AppsyncFunction(
        scope,
        "DiagnoseCatalogForOrderFn",
        name=f"DiagnoseCatalogForOrderFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "diagnose_catalog_for_order_fn.js")),
    )

    # EnsureCatalogFinalFn (defensive): query campaign and stash catalogId if missing
    functions["ensure_catalog_final"] = appsync.AppsyncFunction(
        scope,
        "EnsureCatalogFinalFn",
        name=f"EnsureCatalogFinalFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "ensure_catalog_final_fn.js")),
    )

    # Dev-only: LogCreateOrderState - None data source for final pipeline diagnostics
    functions["log_create_order_state"] = appsync.AppsyncFunction(
        scope,
        "LogCreateOrderStateFn",
        name=f"LogCreateOrderStateFn_{env_name}",
        api=api,
        data_source=datasources["none"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "log_create_order_state_fn.js")),
    )

    # CreateOrderFn
    functions["create_order"] = appsync.AppsyncFunction(
        scope,
        "CreateOrderFn",
        name=f"CreateOrderFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_order_fn.js")),
    )

    # Dev-only: Inspect prepared PutItem (diagnostic) - None data source so it only logs ctx.prev.result
    functions["inspect_put_item"] = appsync.AppsyncFunction(
        scope,
        "InspectPutItemFn",
        name=f"InspectPutItemFn_{env_name}",
        api=api,
        data_source=datasources["none"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "inspect_put_item_fn.js")),
    )


    # === PROFILE SHARING (DIRECT) FUNCTIONS ===

    # VerifyProfileOwnerForShareFn
    functions["verify_profile_owner_for_share"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForShareFn",
        name=f"VerifyProfileOwnerForShareFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_share_fn.js")),
    )

    # LookupAccountByEmailFn
    functions["lookup_account_by_email"] = appsync.AppsyncFunction(
        scope,
        "LookupAccountByEmailFn",
        name=f"LookupAccountByEmailFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_account_by_email_fn.js")),
    )

    # CheckExistingShareFn
    functions["check_existing_share"] = appsync.AppsyncFunction(
        scope,
        "CheckExistingShareFn",
        name=f"CheckExistingShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_existing_share_fn.js")),
    )

    # CreateShareFn
    functions["create_share"] = appsync.AppsyncFunction(
        scope,
        "CreateShareFn",
        name=f"CreateShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_share_fn.js")),
    )

    # === INVITE REDEMPTION FUNCTIONS ===

    # LookupInviteFn
    functions["lookup_invite"] = appsync.AppsyncFunction(
        scope,
        "LookupInviteFn",
        name=f"LookupInviteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_invite_fn.js")),
    )

    # MarkInviteUsedFn
    functions["mark_invite_used"] = appsync.AppsyncFunction(
        scope,
        "MarkInviteUsedFn",
        name=f"MarkInviteUsedFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "mark_invite_used_fn.js")),
    )

    # === QUERY FUNCTIONS ===

    # FetchProfileFn
    functions["fetch_profile"] = appsync.AppsyncFunction(
        scope,
        "FetchProfileFn",
        name=f"FetchProfileFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "fetch_profile_fn.js")),
    )

    # CheckProfileReadAuthFn
    functions["check_profile_read_auth"] = appsync.AppsyncFunction(
        scope,
        "CheckProfileReadAuthFn",
        name=f"CheckProfileReadAuthFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_profile_read_auth_fn.js")),
    )

    # QueryCampaignFn
    functions["query_campaign"] = appsync.AppsyncFunction(
        scope,
        "QueryCampaignFn",
        name=f"QueryCampaignFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_campaign_fn.js")),
    )

    # ReturnCampaignFn
    functions["return_campaign"] = appsync.AppsyncFunction(
        scope,
        "ReturnCampaignFn",
        name=f"ReturnCampaignFn_{env_name}",
        api=api,
        data_source=datasources["none"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "return_campaign_fn.js")),
    )

    # QueryCampaignsFn
    functions["query_campaigns"] = appsync.AppsyncFunction(
        scope,
        "QueryCampaignsFn",
        name=f"QueryCampaignsFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_campaigns_fn.js")),
    )

    # QueryOrderFn
    functions["query_order"] = appsync.AppsyncFunction(
        scope,
        "QueryOrderFn",
        name=f"QueryOrderFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_order_fn.js")),
    )

    # ReturnOrderFn
    functions["return_order"] = appsync.AppsyncFunction(
        scope,
        "ReturnOrderFn",
        name=f"ReturnOrderFn_{env_name}",
        api=api,
        data_source=datasources["none"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "return_order_fn.js")),
    )

    # LookupCampaignForOrdersFn
    functions["lookup_campaign_for_orders"] = appsync.AppsyncFunction(
        scope,
        "LookupCampaignForOrdersFn",
        name=f"LookupCampaignForOrdersFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_campaign_for_orders_fn.js")),
    )

    # QueryOrdersByCampaignFn
    functions["query_orders_by_campaign"] = appsync.AppsyncFunction(
        scope,
        "QueryOrdersByCampaignFn",
        name=f"QueryOrdersByCampaignFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_orders_by_campaign_fn.js")),
    )

    # QueryOrdersByProfileFn
    functions["query_orders_by_profile"] = appsync.AppsyncFunction(
        scope,
        "QueryOrdersByProfileFn",
        name=f"QueryOrdersByProfileFn_{env_name}",
        api=api,
        data_source=datasources["orders"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_orders_by_profile_fn.js")),
    )

    # QuerySharesFn
    functions["query_shares"] = appsync.AppsyncFunction(
        scope,
        "QuerySharesFn",
        name=f"QuerySharesFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_shares_fn.js")),
    )

    # VerifyProfileWriteAccessOrOwnerFn
    functions["verify_profile_write_or_owner"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileWriteAccessOrOwnerFn",
        name=f"VerifyProfileWriteAccessOrOwnerFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(
            str(RESOLVERS_DIR / "verify_profile_write_access_or_owner_fn.js")
        ),
    )

    # CheckWritePermissionFn
    functions["check_write_permission"] = appsync.AppsyncFunction(
        scope,
        "CheckWritePermissionFn",
        name=f"CheckWritePermissionFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_write_permission_fn.js")),
    )

    # QueryInvitesFn
    functions["query_invites"] = appsync.AppsyncFunction(
        scope,
        "QueryInvitesFn",
        name=f"QueryInvitesFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_invites_fn.js")),
    )

    # === SHARED CAMPAIGN FUNCTIONS ===

    # CountUserSharedCampaignsFn
    functions["count_user_shared_campaigns"] = appsync.AppsyncFunction(
        scope,
        "CountUserSharedCampaignsFn",
        name=f"CountUserSharedCampaignsFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "count_user_shared_campaigns_fn.js")),
    )

    # GetCatalogForSharedCampaignFn
    functions["get_catalog_for_shared_campaign"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogForSharedCampaignFn",
        name=f"GetCatalogForSharedCampaignFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_for_shared_campaign_fn.js")),
    )

    # GetAccountForSharedCampaignFn
    functions["get_account_for_shared_campaign"] = appsync.AppsyncFunction(
        scope,
        "GetAccountForSharedCampaignFn",
        name=f"GetAccountForSharedCampaignFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_account_for_shared_campaign_fn.js")),
    )

    # CreateSharedCampaignFn
    functions["create_shared_campaign"] = appsync.AppsyncFunction(
        scope,
        "CreateSharedCampaignFn",
        name=f"CreateSharedCampaignFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_shared_campaign_fn.js")),
    )

    # GetSharedCampaignForUpdateFn
    functions["get_shared_campaign_for_update"] = appsync.AppsyncFunction(
        scope,
        "GetSharedCampaignForUpdateFn",
        name=f"GetSharedCampaignForUpdateFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_shared_campaign_for_update_fn.js")),
    )

    # UpdateSharedCampaignFn
    functions["update_shared_campaign"] = appsync.AppsyncFunction(
        scope,
        "UpdateSharedCampaignFn",
        name=f"UpdateSharedCampaignFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_shared_campaign_fn.js")),
    )

    # DeleteSharedCampaignFn
    functions["delete_shared_campaign"] = appsync.AppsyncFunction(
        scope,
        "DeleteSharedCampaignFn",
        name=f"DeleteSharedCampaignFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_shared_campaign_fn.js")),
    )

    # === CATALOG FUNCTIONS ===

    # CreateCatalogFn
    functions["create_catalog"] = appsync.AppsyncFunction(
        scope,
        "CreateCatalogFn",
        name=f"CreateCatalogFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_catalog_fn.js")),
    )

    # GetCatalogForDeleteFn
    functions["get_catalog_for_delete"] = appsync.AppsyncFunction(
        scope,
        "GetCatalogForDeleteFn",
        name=f"GetCatalogForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_catalog_for_delete_fn.js")),
    )

    # DeleteCatalogFn
    functions["delete_catalog"] = appsync.AppsyncFunction(
        scope,
        "DeleteCatalogFn",
        name=f"DeleteCatalogFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_catalog_fn.js")),
    )

    # UpdateCatalogFn
    functions["update_catalog"] = appsync.AppsyncFunction(
        scope,
        "UpdateCatalogFn",
        name=f"UpdateCatalogFn_{env_name}",
        api=api,
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_catalog_fn.js")),
    )

    return functions


def create_profile_delete_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for deleteSellerProfile pipeline.

    These functions support the multi-step profile deletion process.
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # LookupProfileForUpdateFn
    functions["lookup_profile_for_update"] = appsync.AppsyncFunction(
        scope,
        "LookupProfileForUpdateFn",
        name=f"LookupProfileForUpdateFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_profile_for_update_fn.js")),
    )

    # UpdateProfileFn
    functions["update_profile"] = appsync.AppsyncFunction(
        scope,
        "UpdateProfileFn",
        name=f"UpdateProfileFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_profile_fn.js")),
    )

    # VerifyProfileOwnerForDeleteFn
    functions["verify_profile_owner_for_delete"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForDeleteFn",
        name=f"VerifyProfileOwnerForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_delete_fn.js")),
    )

    # QueryProfileSharesForDeleteFn
    functions["query_profile_shares_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileSharesForDeleteFn",
        name=f"QueryProfileSharesForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_profile_shares_for_delete_fn.js")),
    )

    # QueryProfileInvitesForDeleteFn
    functions["query_profile_invites_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileInvitesForDeleteFn",
        name=f"QueryProfileInvitesForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_profile_invites_for_delete_fn.js")),
    )

    # DeleteProfileSharesFn
    functions["delete_profile_shares"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileSharesFn",
        name=f"DeleteProfileSharesFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_shares_fn.js")),
    )

    # DeleteProfileInvitesFn
    functions["delete_profile_invites"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileInvitesFn",
        name=f"DeleteProfileInvitesFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_invites_fn.js")),
    )

    # QueryProfileCampaignsForDeleteFn
    functions["query_profile_campaigns_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileCampaignsForDeleteFn",
        name=f"QueryProfileCampaignsForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(
            str(RESOLVERS_DIR / "query_profile_campaigns_for_delete_fn.js")
        ),
    )

    # DeleteProfileCampaignsFn
    functions["delete_profile_campaigns"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileCampaignsFn",
        name=f"DeleteProfileCampaignsFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_campaigns_fn.js")),
    )

    # DeleteProfileOwnershipFn (no-op in new design)
    functions["delete_profile_ownership"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileOwnershipFn",
        name=f"DeleteProfileOwnershipFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_ownership_fn.js")),
    )

    # DeleteProfileMetadataFn
    functions["delete_profile_metadata"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileMetadataFn",
        name=f"DeleteProfileMetadataFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_metadata_fn.js")),
    )

    # GetSharedCampaignForDeleteFn
    functions["get_shared_campaign_for_delete"] = appsync.AppsyncFunction(
        scope,
        "GetSharedCampaignForDeleteFn",
        name=f"GetSharedCampaignForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_shared_campaign_for_delete_fn.js")),
    )

    # CheckCatalogUsageFn
    functions["check_catalog_usage"] = appsync.AppsyncFunction(
        scope,
        "CheckCatalogUsageFn",
        name=f"CheckCatalogUsageFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_catalog_usage_fn.js")),
    )

    return functions


def create_appsync_custom_domain(
    scope: Construct,
    api: appsync.GraphqlApi,
    api_domain: str,
    api_certificate: Any,
    hosted_zone: "route53.IHostedZone",
) -> tuple[appsync.CfnDomainName | None, Any, Any]:
    """
    Create AppSync custom domain and DNS records.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        api_domain: Custom domain name
        api_certificate: ACM certificate
        hosted_zone: Route53 hosted zone

    Returns:
        Tuple of (domain_name, domain_association, dns_record)
    """
    print(f"Creating AppSync custom domain: {api_domain}")

    domain_name = appsync.CfnDomainName(
        scope,
        "ApiDomainNameV2",
        certificate_arn=api_certificate.certificate_arn,
        domain_name=api_domain,
    )
    domain_name.apply_removal_policy(RemovalPolicy.RETAIN)

    # Associate custom domain with API
    domain_association = appsync.CfnDomainNameApiAssociation(
        scope,
        "ApiDomainAssociation",
        api_id=api.api_id,
        domain_name=domain_name.attr_domain_name,
    )
    domain_association.add_dependency(domain_name)

    # Route53 record for AppSync custom domain
    dns_record = route53.CnameRecord(
        scope,
        "ApiDomainRecord",
        zone=hosted_zone,
        record_name=api_domain,
        domain_name=domain_name.attr_app_sync_domain_name,
    )
    dns_record.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)  # type: ignore

    return domain_name, domain_association, dns_record


def create_resolvers(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
    functions: dict[str, appsync.AppsyncFunction],
    profile_delete_functions: dict[str, appsync.AppsyncFunction],
) -> None:
    """
    Create all AppSync resolvers for the GraphQL API.

    This function creates both pipeline resolvers and simple VTL/JS resolvers.
    """
    # === MUTATION RESOLVERS ===

    # createProfileInvite Pipeline
    api.create_resolver(
        "CreateProfileInvitePipelineResolver",
        type_name="Mutation",
        field_name="createProfileInvite",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_owner_for_invite"],
            functions["create_invite"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_profile_invite_pipeline_resolver.js")),
    )

    # revokeShare Pipeline
    api.create_resolver(
        "RevokeSharePipelineResolver",
        type_name="Mutation",
        field_name="revokeShare",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_owner_for_revoke"],
            functions["delete_share"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "revoke_share_pipeline_resolver.js")),
    )

    # deleteProfileInvite Pipeline
    api.create_resolver(
        "DeleteProfileInvitePipelineResolver",
        type_name="Mutation",
        field_name="deleteProfileInvite",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["delete_profile_invite"],
            functions["delete_invite_item"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_invite_pipeline_resolver.js")),
    )

    # updateCampaign Pipeline
    api.create_resolver(
        "UpdateCampaignPipelineResolverV2",
        type_name="Mutation",
        field_name="updateCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_campaign"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["update_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_campaign_pipeline_resolver_v2.js")),
    )

    # deleteCampaign Pipeline
    api.create_resolver(
        "DeleteCampaignPipelineResolverV2",
        type_name="Mutation",
        field_name="deleteCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_campaign_for_delete"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["query_campaign_orders_for_delete"],
            functions["delete_campaign_orders"],
            functions["delete_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_campaign_pipeline_resolver_v2.js")),
    )

    # updateOrder Pipeline
    api.create_resolver(
        "UpdateOrderPipelineResolverV2",
        type_name="Mutation",
        field_name="updateOrder",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_order"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["get_catalog_for_update_order"],
            functions["fetch_catalog_for_update"],
            functions["update_order"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_order_pipeline_resolver_v2.js")),
    )

    # deleteOrder Pipeline
    api.create_resolver(
        "DeleteOrderPipelineResolverV2",
        type_name="Mutation",
        field_name="deleteOrder",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_order_for_delete"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["delete_order"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_order_pipeline_resolver_v2.js")),
    )

    # createOrder Pipeline
    api.create_resolver(
        "CreateOrderPipelineResolver",
        type_name="Mutation",
        field_name="createOrder",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["get_campaign_for_order"],
            functions["ensure_catalog_for_order"],
            functions["get_catalog_try_raw"],
            functions["get_catalog_try_prefixed"],
            functions["ensure_catalog_final"],
            functions["get_catalog"],
            functions["create_order"],
            functions["log_create_order_state"],  # Dev-only logging: captures prev.result after create
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_order_pipeline_resolver.js")),
    )

    # shareProfileDirect Pipeline
    api.create_resolver(
        "ShareProfileDirectPipelineResolver",
        type_name="Mutation",
        field_name="shareProfileDirect",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_owner_for_share"],
            functions["lookup_account_by_email"],
            functions["check_existing_share"],
            functions["create_share"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "share_profile_direct_pipeline_resolver.js")),
    )

    # redeemProfileInvite Pipeline
    api.create_resolver(
        "RedeemProfileInvitePipelineResolver",
        type_name="Mutation",
        field_name="redeemProfileInvite",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_invite"],
            functions["check_existing_share"],
            functions["create_share"],
            functions["mark_invite_used"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "redeem_profile_invite_pipeline_resolver.js")),
    )

    # === QUERY RESOLVERS ===

    # getMyAccount
    datasources["accounts"].create_resolver(
        "GetMyAccountResolver",
        type_name="Query",
        field_name="getMyAccount",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
#set($accountId = "ACCOUNT#$ctx.identity.sub")
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "accountId": $util.dynamodb.toDynamoDBJson($accountId)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.isEmpty())
    $util.error("Account not found", "NotFound")
#end
#set($account = $ctx.result)
{
  "accountId": $util.toJson($account.accountId),
  "email": $util.toJson($account.email),
  "givenName": $util.toJson($account.givenName),
  "familyName": $util.toJson($account.familyName),
  "city": $util.toJson($account.city),
  "state": $util.toJson($account.state),
  "unitType": $util.toJson($account.unitType),
  #if($account.unitNumber && $account.unitNumber != "")
  "unitNumber": $util.parseJson($account.unitNumber),
  #else
  "unitNumber": null,
  #end
  "preferences": $util.toJson($account.preferences),
  "createdAt": $util.toJson($account.createdAt),
  "updatedAt": $util.toJson($account.updatedAt)
}
            """
        ),
    )

    # getProfile Pipeline
    appsync.Resolver(
        scope,
        "GetProfileResolver",
        api=api,
        type_name="Query",
        field_name="getProfile",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2018-05-29"
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
$util.toJson($ctx.result)
            """
        ),
        pipeline_config=[
            functions["fetch_profile"],
            functions["check_profile_read_auth"],
        ],
    )

    # listMyProfiles
    api.create_resolver(
        "ListMyProfilesResolver",
        type_name="Query",
        field_name="listMyProfiles",
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_profiles_fn.js")),
    )

    # listMyShares - Just query shares, use field resolvers for profile data
    api.create_resolver(
        "ListMySharesResolverV2",  # Changed ID to force replacement
        type_name="Query",
        field_name="listMyShares",
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_shares_resolver.js")),
    )

    # getCampaign Pipeline
    api.create_resolver(
        "GetCampaignResolver",
        type_name="Query",
        field_name="getCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["query_campaign"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["return_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_campaign_resolver.js")),
    )

    # listCampaignsByProfile Pipeline
    api.create_resolver(
        "ListCampaignsByProfileResolver",
        type_name="Query",
        field_name="listCampaignsByProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_campaigns"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_campaigns_by_profile_resolver.js")),
    )

    # getOrder Pipeline
    api.create_resolver(
        "GetOrderResolver",
        type_name="Query",
        field_name="getOrder",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["query_order"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["return_order"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_order_resolver.js")),
    )

    # listOrdersByCampaign Pipeline
    api.create_resolver(
        "ListOrdersByCampaignResolver",
        type_name="Query",
        field_name="listOrdersByCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["lookup_campaign_for_orders"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_orders_by_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_orders_by_campaign_resolver.js")),
    )

    # listOrdersByProfile Pipeline
    api.create_resolver(
        "ListOrdersByProfileResolver",
        type_name="Query",
        field_name="listOrdersByProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_orders_by_profile"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_orders_by_profile_resolver.js")),
    )

    # listSharesByProfile Pipeline
    api.create_resolver(
        "ListSharesByProfileResolver",
        type_name="Query",
        field_name="listSharesByProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_write_or_owner"],
            functions["check_write_permission"],
            functions["query_shares"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_shares_by_profile_resolver.js")),
    )

    # listInvitesByProfile Pipeline
    # Note: Using appsync.Resolver directly (not api.create_resolver) to match original logical ID
    appsync.Resolver(
        scope,
        "ListInvitesByProfilePipelineResolver",
        api=api,
        type_name="Query",
        field_name="listInvitesByProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["verify_profile_write_or_owner"],
            functions["check_write_permission"],
            functions["query_invites"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_invites_by_profile_pipeline_resolver.js")),
    )

    # getCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "GetCatalogResolver",
        type_name="Query",
        field_name="getCatalog",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if(!$ctx.result || $ctx.result.isEmpty())
    $util.toJson(null)
#else
    ## Check authorization: Allow if catalog is public OR caller is owner
    #set($catalog = $ctx.result)
    #set($callerAccountId = $util.defaultIfNull($ctx.identity.sub, ""))
    #set($isPublic = $catalog.isPublic == "true")
    #set($isOwner = $catalog.ownerAccountId == "ACCOUNT#${callerAccountId}")
    
    #if($isPublic || $isOwner)
        $util.toJson($catalog)
    #else
        ## Non-owner accessing private catalog: return null
        $util.toJson(null)
    #end
#end
            """
        ),
    )

    # listPublicCatalogs
    api.create_resolver(
        "ListPublicCatalogsResolver",
        type_name="Query",
        field_name="listPublicCatalogs",
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_public_catalogs_resolver.js")),
    )

    # listMyCatalogs
    api.create_resolver(
        "ListMyCatalogsResolver",
        type_name="Query",
        field_name="listMyCatalogs",
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_catalogs_resolver.js")),
    )

    # === SHARED CAMPAIGN RESOLVERS ===

    # getSharedCampaign (VTL)
    datasources["shared_campaigns"].create_resolver(
        "GetSharedCampaignResolver",
        type_name="Query",
        field_name="getSharedCampaign",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "sharedCampaignCode": $util.dynamodb.toDynamoDBJson($ctx.args.sharedCampaignCode)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
## Return null if not found or inactive
#if(!$ctx.result || $ctx.result.isEmpty())
    $util.toJson(null)
#else
    #if($ctx.result.isActive == false)
        $util.toJson(null)
    #else
        $util.toJson($ctx.result)
    #end
#end
            """
        ),
    )

    # listMySharedCampaigns
    api.create_resolver(
        "ListMySharedCampaignsResolver",
        type_name="Query",
        field_name="listMySharedCampaigns",
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_shared_campaigns_resolver.js")),
    )

    # findSharedCampaigns
    api.create_resolver(
        "FindSharedCampaignsResolver",
        type_name="Query",
        field_name="findSharedCampaigns",
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "find_shared_campaigns_resolver.js")),
    )

    # createSharedCampaign Pipeline
    api.create_resolver(
        "CreateSharedCampaignPipelineResolver",
        type_name="Mutation",
        field_name="createSharedCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["count_user_shared_campaigns"],
            functions["get_catalog_for_shared_campaign"],
            functions["get_account_for_shared_campaign"],
            functions["create_shared_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_shared_campaign_pipeline_resolver.js")),
    )

    # updateSharedCampaign Pipeline
    api.create_resolver(
        "UpdateSharedCampaignPipelineResolver",
        type_name="Mutation",
        field_name="updateSharedCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["get_shared_campaign_for_update"],
            functions["update_shared_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_shared_campaign_pipeline_resolver.js")),
    )

    # deleteSharedCampaign Pipeline
    api.create_resolver(
        "DeleteSharedCampaignPipelineResolver",
        type_name="Mutation",
        field_name="deleteSharedCampaign",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            profile_delete_functions["get_shared_campaign_for_delete"],
            functions["delete_shared_campaign"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_shared_campaign_pipeline_resolver.js")),
    )

    # === FIELD RESOLVERS ===

    # Campaign.catalog (VTL)
    datasources["catalogs"].create_resolver(
        "CampaignCatalogResolver",
        type_name="Campaign",
        field_name="catalog",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.source.catalogId)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
            """
        ),
    )

    # Campaign.totalOrders (VTL)
    datasources["orders"].create_resolver(
        "CampaignTotalOrdersResolver",
        type_name="Campaign",
        field_name="totalOrders",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "campaignId = :campaignId",
        "expressionValues": {
        ":campaignId": $util.dynamodb.toDynamoDBJson($ctx.source.campaignId)
        }
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$ctx.result.items.size()
            """
        ),
    )

    # Campaign.totalRevenue (VTL)
    datasources["orders"].create_resolver(
        "CampaignTotalRevenueResolver",
        type_name="Campaign",
        field_name="totalRevenue",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "campaignId = :campaignId",
        "expressionValues": {
        ":campaignId": $util.dynamodb.toDynamoDBJson($ctx.source.campaignId)
        }
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#set($total = 0.0)
#foreach($order in $ctx.result.items)
    #set($total = $total + $order.totalAmount)
#end
$total
            """
        ),
    )

    # SellerProfile.ownerAccountId (JS)
    datasources["none"].create_resolver(
        "SellerProfileOwnerAccountIdResolver",
        type_name="SellerProfile",
        field_name="ownerAccountId",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "seller_profile_owner_account_id_resolver.js")),
    )

    # SellerProfile.profileId (JS)
    datasources["none"].create_resolver(
        "SellerProfileIdResolver",
        type_name="SellerProfile",
        field_name="profileId",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "seller_profile_id_resolver.js")),
    )

    # SellerProfile.isOwner (JS)
    datasources["none"].create_resolver(
        "SellerProfileIsOwnerResolver",
        type_name="SellerProfile",
        field_name="isOwner",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "seller_profile_is_owner_resolver.js")),
    )

    # SellerProfile.permissions (JS)
    datasources["shares"].create_resolver(
        "SellerProfilePermissionsResolver",
        type_name="SellerProfile",
        field_name="permissions",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "seller_profile_permissions_resolver.js")),
    )

    # SharedCampaign.catalog (VTL)
    datasources["catalogs"].create_resolver(
        "SharedCampaignCatalogResolver",
        type_name="SharedCampaign",
        field_name="catalog",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.source.catalogId)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
            """
        ),
    )

    # Share.targetAccount (JS)
    datasources["accounts"].create_resolver(
        "ShareTargetAccountResolver",
        type_name="Share",
        field_name="targetAccount",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "share_target_account_resolver.js")),
    )

    # SharedProfile field resolvers - fetch profile data from profiles table
    shared_profile_fields = [
        ("sellerName", "SellerName"),
        ("ownerAccountId", "OwnerAccountId"),
        ("unitType", "UnitType"),
        ("unitNumber", "UnitNumber"),
        ("createdAt", "CreatedAt"),
        ("updatedAt", "UpdatedAt"),
    ]
    for field_name, construct_suffix in shared_profile_fields:
        datasources["profiles"].create_resolver(
            f"SharedProfile{construct_suffix}Resolver",
            type_name="SharedProfile",
            field_name=field_name,
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "shared_profile_field_resolver.js")),
        )

    # Account.accountId (JS) - Strip "ACCOUNT#" prefix
    datasources["none"].create_resolver(
        "AccountIdResolver",
        type_name="Account",
        field_name="accountId",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "account_id_resolver.js")),
    )

    # Catalog.ownerAccountId (JS)
    datasources["none"].create_resolver(
        "CatalogOwnerAccountIdResolver",
        type_name="Catalog",
        field_name="ownerAccountId",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "catalog_owner_account_id_resolver.js")),
    )

    # === CRUD MUTATION RESOLVERS ===

    # createSellerProfile (Lambda)
    lambda_datasources["create_profile"].create_resolver(
        "CreateSellerProfileResolver",
        type_name="Mutation",
        field_name="createSellerProfile",
    )

    # updateSellerProfile Pipeline
    api.create_resolver(
        "UpdateSellerProfileResolver",
        type_name="Mutation",
        field_name="updateSellerProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            profile_delete_functions["lookup_profile_for_update"],
            profile_delete_functions["update_profile"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_seller_profile_resolver.js")),
    )

    # deleteSellerProfile Pipeline
    api.create_resolver(
        "DeleteSellerProfileResolver",
        type_name="Mutation",
        field_name="deleteSellerProfile",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            profile_delete_functions["verify_profile_owner_for_delete"],
            profile_delete_functions["query_profile_shares_for_delete"],
            profile_delete_functions["query_profile_invites_for_delete"],
            profile_delete_functions["delete_profile_shares"],
            profile_delete_functions["delete_profile_invites"],
            profile_delete_functions["query_profile_campaigns_for_delete"],
            profile_delete_functions["delete_profile_campaigns"],
            profile_delete_functions["delete_profile_ownership"],
            profile_delete_functions["delete_profile_metadata"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_seller_profile_resolver.js")),
    )

    # createCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "CreateCatalogResolver",
        type_name="Mutation",
        field_name="createCatalog",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
## Validate products array is not empty
#if($ctx.args.input.products.size() == 0)
    $util.error("Products array cannot be empty", "ValidationException")
#end
#set($catalogId = "CATALOG#$util.autoId()")
#set($now = $util.time.nowISO8601())
## Add productId to each product
#set($productsWithIds = [])
#foreach($product in $ctx.args.input.products)
    #set($productId = "PRODUCT#$util.autoId()")
    #set($productWithId = {
        "productId": $productId,
        "productName": $product.productName,
        "price": $product.price,
        "sortOrder": $product.sortOrder
    })
    #if($product.description)
        $util.qr($productWithId.put("description", $product.description))
    #end
    $util.qr($productsWithIds.add($productWithId))
#end
## Convert isPublic boolean to string for GSI
#if($ctx.args.input.isPublic)
    #set($isPublicStr = "true")
#else
    #set($isPublicStr = "false")
#end
{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($catalogId)
    },
    "attributeValues": {
        "catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
        "catalogType": $util.dynamodb.toDynamoDBJson("USER_CREATED"),
        "ownerAccountId": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "isPublic": $util.dynamodb.toDynamoDBJson($isPublicStr),
        "isPublicStr": $util.dynamodb.toDynamoDBJson($isPublicStr),
        "products": $util.dynamodb.toDynamoDBJson($productsWithIds),
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now)
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
            """
        ),
    )

    # updateCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "UpdateCatalogResolver",
        type_name="Mutation",
        field_name="updateCatalog",
        request_mapping_template=appsync.MappingTemplate.from_string(
            """
#set($now = $util.time.nowISO8601())
## Add productId to each product if not present
#set($productsWithIds = [])
#foreach($product in $ctx.args.input.products)
    #set($productWithId = {
        "productName": $product.productName,
        "price": $product.price,
        "sortOrder": $product.sortOrder
    })
    ## Preserve existing productId or generate new one
    #if($product.productId)
        $util.qr($productWithId.put("productId", $product.productId))
    #else
        #set($newProductId = "PRODUCT#$util.autoId()")
        $util.qr($productWithId.put("productId", $newProductId))
    #end
    #if($product.description)
        $util.qr($productWithId.put("description", $product.description))
    #end
    $util.qr($productsWithIds.add($productWithId))
#end
## Convert isPublic boolean to string for GSI
#if($ctx.args.input.isPublic)
    #set($isPublicStr = "true")
#else
    #set($isPublicStr = "false")
#end
#set($ownerWithPrefix = "ACCOUNT#$ctx.identity.sub")
{
    "version": "2017-02-28",
    "operation": "UpdateItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    },
    "update": {
        "expression": "SET catalogName = :catalogName, isPublic = :isPublic, isPublicStr = :isPublicStr, products = :products, updatedAt = :updatedAt",
        "expressionValues": {
        ":catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
        ":isPublic": $util.dynamodb.toDynamoDBJson($isPublicStr),
        ":isPublicStr": $util.dynamodb.toDynamoDBJson($isPublicStr),
        ":products": $util.dynamodb.toDynamoDBJson($productsWithIds),
        ":updatedAt": $util.dynamodb.toDynamoDBJson($now)
        }
    },
    "condition": {
        "expression": "attribute_exists(catalogId) AND ownerAccountId = :ownerId",
        "expressionValues": {
        ":ownerId": $util.dynamodb.toDynamoDBJson($ownerWithPrefix)
        }
    }
}
            """
        ),
        response_mapping_template=appsync.MappingTemplate.from_string(
            """
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Catalog not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson($ctx.result)
            """
        ),
    )

    # deleteCatalog Pipeline
    appsync.Resolver(
        scope,
        "DeleteCatalogPipelineResolver",
        api=api,
        type_name="Mutation",
        field_name="deleteCatalog",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        pipeline_config=[
            functions["get_catalog_for_delete"],
            profile_delete_functions["check_catalog_usage"],
            functions["delete_catalog"],
        ],
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_catalog_pipeline_resolver.js")),
    )

    # createCampaign (Lambda - transaction support)
    lambda_datasources["campaign_operations"].create_resolver(
        "CreateCampaignResolver",
        type_name="Mutation",
        field_name="createCampaign",
    )

    # requestCampaignReport (Lambda)
    lambda_datasources["request_campaign_report"].create_resolver(
        "RequestCampaignReportResolver",
        type_name="Mutation",
        field_name="requestCampaignReport",
    )

    # getUnitReport (Lambda)
    lambda_datasources["unit_reporting"].create_resolver(
        "GetUnitReportResolver",
        type_name="Query",
        field_name="getUnitReport",
    )

    # listUnitCatalogs (Lambda - deprecated)
    lambda_datasources["list_unit_catalogs"].create_resolver(
        "ListUnitCatalogsResolver",
        type_name="Query",
        field_name="listUnitCatalogs",
    )

    # listUnitCampaignCatalogs (Lambda)
    lambda_datasources["list_unit_campaign_catalogs"].create_resolver(
        "ListUnitCampaignCatalogsResolver",
        type_name="Query",
        field_name="listUnitCampaignCatalogs",
    )

    # updateMyAccount (Lambda)
    lambda_datasources["update_my_account"].create_resolver(
        "UpdateMyAccountResolver",
        type_name="Mutation",
        field_name="updateMyAccount",
    )

    # transferProfileOwnership (Lambda)
    lambda_datasources["transfer_ownership"].create_resolver(
        "TransferProfileOwnershipResolver",
        type_name="Mutation",
        field_name="transferProfileOwnership",
    )

    # updateMyPreferences (JS)
    datasources["accounts"].create_resolver(
        "UpdateMyPreferencesResolver",
        type_name="Mutation",
        field_name="updateMyPreferences",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_my_preferences_resolver.js")),
    )
