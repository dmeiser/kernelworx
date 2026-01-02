"""Mutation resolvers for AppSync GraphQL API."""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR


def create_mutation_resolvers(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
    functions: dict[str, appsync.AppsyncFunction],
    profile_delete_functions: dict[str, appsync.AppsyncFunction],
) -> None:
    """
    Create all AppSync mutation resolvers.

    Args:
        scope: CDK construct scope
        api: AppSync GraphQL API
        env_name: Environment name (dev, prod, etc.)
        datasources: Dictionary of AppSync data sources
        lambda_datasources: Dictionary of Lambda data sources
        functions: Dictionary of reusable AppSync functions
        profile_delete_functions: Dictionary of profile-related AppSync functions
    """
    # === SHARING & INVITATION MUTATIONS ===

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

    # === CAMPAIGN MUTATIONS ===

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

    # createCampaign (Lambda - transaction support)
    lambda_datasources["campaign_operations"].create_resolver(
        "CreateCampaignResolver",
        type_name="Mutation",
        field_name="createCampaign",
    )

    # === ORDER MUTATIONS ===

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

    # === CATALOG MUTATIONS ===

    # createCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "CreateCatalogResolver",
        type_name="Mutation",
        field_name="createCatalog",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "create_catalog_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "create_catalog_response.vtl")
        ),
    )

    # updateCatalog (VTL)
    datasources["catalogs"].create_resolver(
        "UpdateCatalogResolver",
        type_name="Mutation",
        field_name="updateCatalog",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "update_catalog_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "update_catalog_response.vtl")
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

    # === SELLER PROFILE MUTATIONS ===

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

    # === SHARED CAMPAIGN MUTATIONS ===

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

    # === ACCOUNT & PREFERENCES MUTATIONS ===

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

    # requestCampaignReport (Lambda)
    lambda_datasources["request_campaign_report"].create_resolver(
        "RequestCampaignReportResolver",
        type_name="Mutation",
        field_name="requestCampaignReport",
    )
