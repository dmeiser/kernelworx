"""Field resolvers for AppSync GraphQL API types."""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR
from ..resolver_builder import ResolverBuilder


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
    # Initialize the resolver builder
    builder = ResolverBuilder(api, datasources, lambda_datasources, scope)

    # === CAMPAIGN FIELD RESOLVERS ===

    # Campaign.catalog (VTL)
    builder.create_vtl_resolver(
        field_name="catalog",
        type_name="Campaign",
        datasource_name="catalogs",
        request_template=MAPPING_TEMPLATES_DIR / "campaign_catalog_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "campaign_catalog_response.vtl",
        id_suffix="CampaignCatalogResolver",
    )

    # Campaign.totalOrders (VTL)
    builder.create_vtl_resolver(
        field_name="totalOrders",
        type_name="Campaign",
        datasource_name="orders",
        request_template=MAPPING_TEMPLATES_DIR / "campaign_total_orders_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "campaign_total_orders_response.vtl",
        id_suffix="CampaignTotalOrdersResolver",
    )

    # Campaign.totalRevenue (VTL)
    builder.create_vtl_resolver(
        field_name="totalRevenue",
        type_name="Campaign",
        datasource_name="orders",
        request_template=MAPPING_TEMPLATES_DIR / "campaign_total_revenue_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "campaign_total_revenue_response.vtl",
        id_suffix="CampaignTotalRevenueResolver",
    )

    # === SELLER PROFILE FIELD RESOLVERS ===

    # SellerProfile.ownerAccountId (JS)
    builder.create_js_resolver(
        field_name="ownerAccountId",
        type_name="SellerProfile",
        datasource_name="none",
        code_file=RESOLVERS_DIR / "seller_profile_owner_account_id_resolver.js",
        id_suffix="SellerProfileOwnerAccountIdResolver",
    )

    # SellerProfile.profileId (JS)
    builder.create_js_resolver(
        field_name="profileId",
        type_name="SellerProfile",
        datasource_name="none",
        code_file=RESOLVERS_DIR / "seller_profile_id_resolver.js",
        id_suffix="SellerProfileIdResolver",
    )

    # SellerProfile.isOwner (JS)
    builder.create_js_resolver(
        field_name="isOwner",
        type_name="SellerProfile",
        datasource_name="none",
        code_file=RESOLVERS_DIR / "seller_profile_is_owner_resolver.js",
        id_suffix="SellerProfileIsOwnerResolver",
    )

    # SellerProfile.permissions (JS)
    builder.create_js_resolver(
        field_name="permissions",
        type_name="SellerProfile",
        datasource_name="shares",
        code_file=RESOLVERS_DIR / "seller_profile_permissions_resolver.js",
        id_suffix="SellerProfilePermissionsResolver",
    )

    # === SHARED CAMPAIGN FIELD RESOLVERS ===

    # SharedCampaign.catalog (VTL)
    builder.create_vtl_resolver(
        field_name="catalog",
        type_name="SharedCampaign",
        datasource_name="catalogs",
        request_template=MAPPING_TEMPLATES_DIR / "shared_campaign_catalog_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "shared_campaign_catalog_response.vtl",
        id_suffix="SharedCampaignCatalogResolver",
    )

    # === SHARE FIELD RESOLVERS ===

    # Share.targetAccount (JS)
    builder.create_js_resolver(
        field_name="targetAccount",
        type_name="Share",
        datasource_name="accounts",
        code_file=RESOLVERS_DIR / "share_target_account_resolver.js",
        id_suffix="ShareTargetAccountResolver",
    )

    # === SHARED PROFILE FIELD RESOLVERS ===
    # NOTE: These field resolvers are NO LONGER NEEDED because the listMyShares 
    # Lambda now returns fully hydrated profile data. These were causing issues
    # when the Lambda returned valid data but then field resolvers would refetch
    # from DynamoDB and return nulls for profiles with missing fields.
    # Commented out in favor of Lambda returning complete data.
    # 
    # shared_profile_fields = [
    #     ("sellerName", "SellerName"),
    #     ("ownerAccountId", "OwnerAccountId"),
    #     ("unitType", "UnitType"),
    #     ("unitNumber", "UnitNumber"),
    #     ("createdAt", "CreatedAt"),
    #     ("updatedAt", "UpdatedAt"),
    # ]
    # for field_name, construct_suffix in shared_profile_fields:
    #     builder.create_js_resolver(
    #         field_name=field_name,
    #         type_name="SharedProfile",
    #         datasource_name="profiles",
    #         code_file=RESOLVERS_DIR / "shared_profile_field_resolver.js",
    #         id_suffix=f"SharedProfile{construct_suffix}Resolver",
    #     )

    # === ACCOUNT & CATALOG FIELD RESOLVERS ===

    # Account.accountId (JS) - Strip "ACCOUNT#" prefix
    builder.create_js_resolver(
        field_name="accountId",
        type_name="Account",
        datasource_name="none",
        code_file=RESOLVERS_DIR / "account_id_resolver.js",
        id_suffix="AccountIdResolver",
    )

    # Note: Catalog.ownerAccountId removed from GraphQL schema (Phase 3)
    # ownerAccountId still stored in DynamoDB for WRITE authorization but not exposed to clients

    # === PAYMENT METHOD FIELD RESOLVERS ===

    # PaymentMethod.qrCodeUrl - Generate presigned S3 URL on-demand
    # Uses Lambda to convert S3 key to presigned URL
    # Authorization: reads ownerAccountId from ctx.stash (set by query pipeline)
    if "generate_qr_code_presigned_url_fn" in lambda_datasources:
        # Create field resolver with JavaScript code that calls Lambda
        lambda_ds = lambda_datasources["generate_qr_code_presigned_url_fn"]
        api.create_resolver(
            "PaymentMethodQrCodeUrlResolver",
            type_name="PaymentMethod",
            field_name="qrCodeUrl",
            data_source=lambda_ds,
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "payment_method_qr_code_url_resolver.js")),
        )
