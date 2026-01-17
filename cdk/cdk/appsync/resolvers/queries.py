"""Query resolvers for AppSync GraphQL API."""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR
from ..resolver_builder import ResolverBuilder


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
    # Initialize the resolver builder
    builder = ResolverBuilder(api, datasources, lambda_datasources, scope)

    # === ACCOUNT & PROFILE QUERIES ===

    # getMyAccount (VTL)
    builder.create_vtl_resolver(
        field_name="getMyAccount",
        type_name="Query",
        datasource_name="accounts",
        request_template=MAPPING_TEMPLATES_DIR / "get_my_account_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "get_my_account_response.vtl",
        id_suffix="GetMyAccountResolver",
    )

    # getProfile Pipeline (VTL with pipeline config)
    builder.create_vtl_pipeline_resolver(
        field_name="getProfile",
        type_name="Query",
        functions=[
            functions["fetch_profile"],
            functions["check_profile_read_auth"],
        ],
        request_template=MAPPING_TEMPLATES_DIR / "get_profile_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "get_profile_response.vtl",
        id_suffix="GetProfileResolver",
    )

    # listMyProfiles (JS)
    builder.create_js_resolver_on_api(
        field_name="listMyProfiles",
        type_name="Query",
        datasource_name="profiles",
        code_file=RESOLVERS_DIR / "list_my_profiles_fn.js",
        id_suffix="ListMyProfilesResolver",
    )

    # listMyShares (Lambda - handles orphaned shares gracefully)
    builder.create_lambda_resolver(
        field_name="listMyShares",
        type_name="Query",
        lambda_datasource_name="list_my_shares_fn",
        id_suffix="ListMySharesResolverV2",  # Keep same ID to do in-place update
    )

    # === CAMPAIGN QUERIES ===

    # getCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="getCampaign",
        type_name="Query",
        functions=[
            functions["query_campaign"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["return_campaign"],
        ],
        code_file=RESOLVERS_DIR / "get_campaign_resolver.js",
        id_suffix="GetCampaignResolver",
    )

    # listCampaignsByProfile Pipeline
    builder.create_pipeline_resolver(
        field_name="listCampaignsByProfile",
        type_name="Query",
        functions=[
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_campaigns"],
        ],
        code_file=RESOLVERS_DIR / "list_campaigns_by_profile_resolver.js",
        id_suffix="ListCampaignsByProfileResolver",
    )

    # === ORDER QUERIES ===

    # getOrder Pipeline
    builder.create_pipeline_resolver(
        field_name="getOrder",
        type_name="Query",
        functions=[
            functions["query_order"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["return_order"],
        ],
        code_file=RESOLVERS_DIR / "get_order_resolver.js",
        id_suffix="GetOrderResolver",
    )

    # listOrdersByCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="listOrdersByCampaign",
        type_name="Query",
        functions=[
            functions["lookup_campaign_for_orders"],
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_orders_by_campaign"],
        ],
        code_file=RESOLVERS_DIR / "list_orders_by_campaign_resolver.js",
        id_suffix="ListOrdersByCampaignResolver",
    )

    # listOrdersByProfile Pipeline
    builder.create_pipeline_resolver(
        field_name="listOrdersByProfile",
        type_name="Query",
        functions=[
            functions["verify_profile_read_access"],
            functions["check_share_read_permissions"],
            functions["query_orders_by_profile"],
        ],
        code_file=RESOLVERS_DIR / "list_orders_by_profile_resolver.js",
        id_suffix="ListOrdersByProfileResolver",
    )

    # === SHARE & INVITE QUERIES ===

    # listSharesByProfile Pipeline
    builder.create_pipeline_resolver(
        field_name="listSharesByProfile",
        type_name="Query",
        functions=[
            functions["verify_profile_write_or_owner"],
            functions["check_write_permission"],
            functions["query_shares"],
        ],
        code_file=RESOLVERS_DIR / "list_shares_by_profile_resolver.js",
        id_suffix="ListSharesByProfileResolver",
    )

    # listInvitesByProfile Pipeline (VTL-style with appsync.Resolver construct)
    # NOTE: Uses create_pipeline_resolver_on_scope to maintain backwards compatibility
    # with existing CloudFormation resource that doesn't have 'Api' prefix
    builder.create_pipeline_resolver_on_scope(
        field_name="listInvitesByProfile",
        type_name="Query",
        functions=[
            functions["verify_profile_write_or_owner"],
            functions["check_write_permission"],
            functions["query_invites"],
        ],
        code_file=RESOLVERS_DIR / "list_invites_by_profile_pipeline_resolver.js",
        id_suffix="ListInvitesByProfilePipelineResolver",
    )

    # === CATALOG QUERIES ===

    # getCatalog (VTL)
    builder.create_vtl_resolver(
        field_name="getCatalog",
        type_name="Query",
        datasource_name="catalogs",
        request_template=MAPPING_TEMPLATES_DIR / "get_catalog_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "get_catalog_response.vtl",
        id_suffix="GetCatalogResolver",
    )

    # listManagedCatalogs (JS)
    builder.create_js_resolver_on_api(
        field_name="listManagedCatalogs",
        type_name="Query",
        datasource_name="catalogs",
        code_file=RESOLVERS_DIR / "list_public_catalogs_resolver.js",
        id_suffix="ListManagedCatalogsResolver",
    )

    # listMyCatalogs (JS)
    builder.create_js_resolver_on_api(
        field_name="listMyCatalogs",
        type_name="Query",
        datasource_name="catalogs",
        code_file=RESOLVERS_DIR / "list_my_catalogs_resolver.js",
        id_suffix="ListMyCatalogsResolver",
    )

    # === SHARED CAMPAIGN QUERIES ===

    # getSharedCampaign (VTL)
    builder.create_vtl_resolver(
        field_name="getSharedCampaign",
        type_name="Query",
        datasource_name="shared_campaigns",
        request_template=MAPPING_TEMPLATES_DIR / "get_shared_campaign_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "get_shared_campaign_response.vtl",
        id_suffix="GetSharedCampaignResolver",
    )

    # listMySharedCampaigns (JS)
    builder.create_js_resolver_on_api(
        field_name="listMySharedCampaigns",
        type_name="Query",
        datasource_name="shared_campaigns",
        code_file=RESOLVERS_DIR / "list_my_shared_campaigns_resolver.js",
        id_suffix="ListMySharedCampaignsResolver",
    )

    # findSharedCampaigns (JS)
    builder.create_js_resolver_on_api(
        field_name="findSharedCampaigns",
        type_name="Query",
        datasource_name="shared_campaigns",
        code_file=RESOLVERS_DIR / "find_shared_campaigns_resolver.js",
        id_suffix="FindSharedCampaignsResolver",
    )

    # === REPORTING QUERIES ===

    # getUnitReport (Lambda)
    builder.create_lambda_resolver(
        field_name="getUnitReport",
        type_name="Query",
        lambda_datasource_name="unit_reporting_fn",
        id_suffix="GetUnitReportResolver",
    )

    # listUnitCatalogs (Lambda - deprecated)
    builder.create_lambda_resolver(
        field_name="listUnitCatalogs",
        type_name="Query",
        lambda_datasource_name="list_unit_catalogs_fn",
        id_suffix="ListUnitCatalogsResolver",
    )

    # listUnitCampaignCatalogs (Lambda)
    builder.create_lambda_resolver(
        field_name="listUnitCampaignCatalogs",
        type_name="Query",
        lambda_datasource_name="list_unit_campaign_catalogs_fn",
        id_suffix="ListUnitCampaignCatalogsResolver",
    )

    # === PAYMENT METHODS QUERIES ===

    # myPaymentMethods Pipeline
    # Simple pipeline: fetch custom methods, inject globals, set owner in stash for field resolver
    builder.create_pipeline_resolver(
        field_name="myPaymentMethods",
        type_name="Query",
        functions=[
            functions["get_payment_methods"],
            functions["inject_global_payment_methods"],
            functions["set_owner_account_id_in_stash"],
        ],
        code_file=RESOLVERS_DIR / "my_payment_methods_pipeline_resolver.js",
        id_suffix="MyPaymentMethodsResolver",
    )

    # paymentMethodsForProfile Pipeline
    # Simplified to use field resolver for presigned URLs
    if "check_payment_methods_access" in functions:
        builder.create_pipeline_resolver(
            field_name="paymentMethodsForProfile",
            type_name="Query",
            functions=[
                functions["fetch_profile"],
                functions["check_payment_methods_access"],
                functions["get_owner_payment_methods"],
                functions["filter_payment_methods_by_access"],
            ],
            code_file=RESOLVERS_DIR / "payment_methods_for_profile_pipeline_resolver.js",
            id_suffix="PaymentMethodsForProfileResolver",
        )

