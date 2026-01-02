"""Field resolvers for AppSync GraphQL API types."""

from pathlib import Path
from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR


def create_field_resolvers(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
    functions: dict[str, appsync.AppsyncFunction],
    profile_delete_functions: dict[str, appsync.AppsyncFunction],
) -> None:
    """
    Create all AppSync field resolvers for nested types.

    Args:
        scope: CDK construct scope
        api: AppSync GraphQL API
        env_name: Environment name (dev, prod, etc.)
        datasources: Dictionary of AppSync data sources
        lambda_datasources: Dictionary of Lambda data sources
        functions: Dictionary of reusable AppSync functions
        profile_delete_functions: Dictionary of profile-related AppSync functions
    """
    # === CAMPAIGN FIELD RESOLVERS ===

    # Campaign.catalog (VTL)
    datasources["catalogs"].create_resolver(
        "CampaignCatalogResolver",
        type_name="Campaign",
        field_name="catalog",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_catalog_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_catalog_response.vtl")
        ),
    )

    # Campaign.totalOrders (VTL)
    datasources["orders"].create_resolver(
        "CampaignTotalOrdersResolver",
        type_name="Campaign",
        field_name="totalOrders",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_total_orders_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_total_orders_response.vtl")
        ),
    )

    # Campaign.totalRevenue (VTL)
    datasources["orders"].create_resolver(
        "CampaignTotalRevenueResolver",
        type_name="Campaign",
        field_name="totalRevenue",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_total_revenue_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "campaign_total_revenue_response.vtl")
        ),
    )

    # === SELLER PROFILE FIELD RESOLVERS ===

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

    # === SHARED CAMPAIGN FIELD RESOLVERS ===

    # SharedCampaign.catalog (VTL)
    datasources["catalogs"].create_resolver(
        "SharedCampaignCatalogResolver",
        type_name="SharedCampaign",
        field_name="catalog",
        request_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "shared_campaign_catalog_request.vtl")
        ),
        response_mapping_template=appsync.MappingTemplate.from_file(
            str(MAPPING_TEMPLATES_DIR / "shared_campaign_catalog_response.vtl")
        ),
    )

    # === SHARE FIELD RESOLVERS ===

    # Share.targetAccount (JS)
    datasources["accounts"].create_resolver(
        "ShareTargetAccountResolver",
        type_name="Share",
        field_name="targetAccount",
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "share_target_account_resolver.js")),
    )

    # === SHARED PROFILE FIELD RESOLVERS ===

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

    # === ACCOUNT & CATALOG FIELD RESOLVERS ===

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
