"""Query resolvers for AppSync GraphQL API."""

from pathlib import Path
from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR


def create_query_resolvers(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
    functions: dict[str, appsync.AppsyncFunction],
    profile_delete_functions: dict[str, appsync.AppsyncFunction],
) -> None:
    """
    Create all AppSync query resolvers.

    Args:
        scope: CDK construct scope
        api: AppSync GraphQL API
        env_name: Environment name (dev, prod, etc.)
        datasources: Dictionary of AppSync data sources
        lambda_datasources: Dictionary of Lambda data sources
        functions: Dictionary of reusable AppSync functions
        profile_delete_functions: Dictionary of profile-related AppSync functions
    """
    # === ACCOUNT & PROFILE QUERIES ===

    # getMyAccount (VTL)
    datasources["accounts"].create_resolver(
        "GetMyAccountResolver",
        type_name="Query",
        field_name="getMyAccount",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_my_account_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_my_account_response.vtl")
        ),
    )

    # getProfile Pipeline
    appsync.Resolver(
        scope,
        "GetProfileResolver",
        api=api,
        type_name="Query",
        field_name="getProfile",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_profile_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_profile_response.vtl")
        ),
        pipeline_config=[
            functions["fetch_profile"],
            functions["check_profile_read_auth"],
        ],
    )

    # listMyProfiles (JS)
    api.create_resolver(
        "ListMyProfilesResolver",
        type_name="Query",
        field_name="listMyProfiles",
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_profiles_fn.js")),
    )

    # listMyShares (JS)
    api.create_resolver(
        "ListMySharesResolverV2",  # Changed ID to force replacement
        type_name="Query",
        field_name="listMyShares",
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_shares_resolver.js")),
    )

    # === CAMPAIGN QUERIES ===

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

    # === ORDER QUERIES ===

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

    # === SHARE & INVITE QUERIES ===

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

    # === CATALOG QUERIES ===

    # getCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "GetCatalogResolver",
        type_name="Query",
        field_name="getCatalog",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_catalog_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_catalog_response.vtl")
        ),
    )

    # listPublicCatalogs (JS)
    api.create_resolver(
        "ListPublicCatalogsResolver",
        type_name="Query",
        field_name="listPublicCatalogs",
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_public_catalogs_resolver.js")),
    )

    # listMyCatalogs (JS)
    api.create_resolver(
        "ListMyCatalogsResolver",
        type_name="Query",
        field_name="listMyCatalogs",
        data_source=datasources["catalogs"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_catalogs_resolver.js")),
    )

    # === SHARED CAMPAIGN QUERIES ===

    # getSharedCampaign (VTL)
    datasources["shared_campaigns"].create_resolver(
        "GetSharedCampaignResolver",
        type_name="Query",
        field_name="getSharedCampaign",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_shared_campaign_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "get_shared_campaign_response.vtl")
        ),
    )

    # listMySharedCampaigns (JS)
    api.create_resolver(
        "ListMySharedCampaignsResolver",
        type_name="Query",
        field_name="listMySharedCampaigns",
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "list_my_shared_campaigns_resolver.js")),
    )

    # findSharedCampaigns (JS)
    api.create_resolver(
        "FindSharedCampaignsResolver",
        type_name="Query",
        field_name="findSharedCampaigns",
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "find_shared_campaigns_resolver.js")),
    )

    # === REPORTING QUERIES ===

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
