"""Mutation resolvers for AppSync GraphQL API."""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Import directory paths from parent api module
from ..api import MAPPING_TEMPLATES_DIR, RESOLVERS_DIR
from ..resolver_builder import ResolverBuilder


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
    # Initialize the resolver builder
    builder = ResolverBuilder(api, datasources, lambda_datasources, scope)

    # === SHARING & INVITATION MUTATIONS ===

    # createProfileInvite Pipeline
    builder.create_pipeline_resolver(
        field_name="createProfileInvite",
        type_name="Mutation",
        functions=[
            functions["verify_profile_owner_for_invite"],
            functions["create_invite"],
        ],
        code_file=RESOLVERS_DIR / "create_profile_invite_pipeline_resolver.js",
        id_suffix="CreateProfileInvitePipelineResolver",
    )

    # revokeShare Pipeline
    builder.create_pipeline_resolver(
        field_name="revokeShare",
        type_name="Mutation",
        functions=[
            functions["verify_profile_owner_for_revoke"],
            functions["delete_share"],
        ],
        code_file=RESOLVERS_DIR / "revoke_share_pipeline_resolver.js",
        id_suffix="RevokeSharePipelineResolver",
    )

    # deleteProfileInvite Pipeline
    builder.create_pipeline_resolver(
        field_name="deleteProfileInvite",
        type_name="Mutation",
        functions=[
            functions["delete_profile_invite"],
            functions["delete_invite_item"],
        ],
        code_file=RESOLVERS_DIR / "delete_profile_invite_pipeline_resolver.js",
        id_suffix="DeleteProfileInvitePipelineResolver",
    )

    # shareProfileDirect Pipeline
    builder.create_pipeline_resolver(
        field_name="shareProfileDirect",
        type_name="Mutation",
        functions=[
            functions["verify_profile_owner_for_share"],
            functions["lookup_account_by_email"],
            functions["check_existing_share"],
            functions["create_share"],
        ],
        code_file=RESOLVERS_DIR / "share_profile_direct_pipeline_resolver.js",
        id_suffix="ShareProfileDirectPipelineResolver",
    )

    # redeemProfileInvite Pipeline
    builder.create_pipeline_resolver(
        field_name="redeemProfileInvite",
        type_name="Mutation",
        functions=[
            functions["lookup_invite"],
            functions["check_existing_share"],
            functions["create_share"],
            functions["mark_invite_used"],
        ],
        code_file=RESOLVERS_DIR / "redeem_profile_invite_pipeline_resolver.js",
        id_suffix="RedeemProfileInvitePipelineResolver",
    )

    # === CAMPAIGN MUTATIONS ===

    # updateCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="updateCampaign",
        type_name="Mutation",
        functions=[
            functions["lookup_campaign"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["update_campaign"],
        ],
        code_file=RESOLVERS_DIR / "update_campaign_pipeline_resolver_v2.js",
        id_suffix="UpdateCampaignPipelineResolverV2",
    )

    # deleteCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="deleteCampaign",
        type_name="Mutation",
        functions=[
            functions["lookup_campaign_for_delete"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["query_campaign_orders_for_delete"],
            functions["delete_campaign_orders"],
            functions["delete_campaign"],
        ],
        code_file=RESOLVERS_DIR / "delete_campaign_pipeline_resolver_v2.js",
        id_suffix="DeleteCampaignPipelineResolverV2",
    )

    # createCampaign (Lambda - transaction support)
    builder.create_lambda_resolver(
        field_name="createCampaign",
        type_name="Mutation",
        lambda_datasource_name="campaign_operations_fn",
        id_suffix="CreateCampaignResolver",
    )

    # === ORDER MUTATIONS ===

    # updateOrder Pipeline
    builder.create_pipeline_resolver(
        field_name="updateOrder",
        type_name="Mutation",
        functions=[
            functions["lookup_order"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["get_catalog_for_update_order"],
            functions["fetch_catalog_for_update"],
            functions["update_order"],
        ],
        code_file=RESOLVERS_DIR / "update_order_pipeline_resolver_v2.js",
        id_suffix="UpdateOrderPipelineResolverV2",
    )

    # deleteOrder Pipeline
    builder.create_pipeline_resolver(
        field_name="deleteOrder",
        type_name="Mutation",
        functions=[
            functions["lookup_order_for_delete"],
            functions["verify_profile_write_access"],
            functions["check_share_permissions"],
            functions["delete_order"],
        ],
        code_file=RESOLVERS_DIR / "delete_order_pipeline_resolver_v2.js",
        id_suffix="DeleteOrderPipelineResolverV2",
    )

    # createOrder Pipeline
    # Conditionally include validate_payment_method if Lambda is available
    create_order_functions = [
        functions["verify_profile_write_access"],
        functions["check_share_permissions"],
    ]
    
    # Add payment method validation if Lambda is available
    if "validate_payment_method" in functions:
        create_order_functions.append(functions["validate_payment_method"])
    
    create_order_functions.extend([
        functions["get_campaign_for_order"],
        functions["ensure_catalog_for_order"],
        functions["get_catalog_try_raw"],
        functions["get_catalog_try_prefixed"],
        functions["ensure_catalog_final"],
        functions["get_catalog"],
        functions["create_order"],
        # NOTE: log_create_order_state removed to stay within 10-function AppSync limit
    ])
    
    builder.create_pipeline_resolver(
        field_name="createOrder",
        type_name="Mutation",
        functions=create_order_functions,
        code_file=RESOLVERS_DIR / "create_order_pipeline_resolver.js",
        id_suffix="CreateOrderPipelineResolver",
    )

    # === CATALOG MUTATIONS ===

    # createCatalog (VTL)
    builder.create_vtl_resolver(
        field_name="createCatalog",
        type_name="Mutation",
        datasource_name="catalogs",
        request_template=MAPPING_TEMPLATES_DIR / "create_catalog_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "create_catalog_response.vtl",
        id_suffix="CreateCatalogResolver",
    )

    # updateCatalog (VTL)
    builder.create_vtl_resolver(
        field_name="updateCatalog",
        type_name="Mutation",
        datasource_name="catalogs",
        request_template=MAPPING_TEMPLATES_DIR / "update_catalog_request.vtl",
        response_template=MAPPING_TEMPLATES_DIR / "update_catalog_response.vtl",
        id_suffix="UpdateCatalogResolver",
    )

    # deleteCatalog Pipeline
    # NOTE: Uses create_pipeline_resolver_on_scope to maintain backwards compatibility
    # with existing CloudFormation resource that doesn't have 'Api' prefix
    builder.create_pipeline_resolver_on_scope(
        field_name="deleteCatalog",
        type_name="Mutation",
        functions=[
            functions["get_catalog_for_delete"],
            profile_delete_functions["check_catalog_usage"],
            functions["delete_catalog"],
        ],
        code_file=RESOLVERS_DIR / "delete_catalog_pipeline_resolver.js",
        id_suffix="DeleteCatalogPipelineResolver",
    )

    # === SELLER PROFILE MUTATIONS ===

    # createSellerProfile (Lambda)
    builder.create_lambda_resolver(
        field_name="createSellerProfile",
        type_name="Mutation",
        lambda_datasource_name="create_profile_fn",
        id_suffix="CreateSellerProfileResolver",
    )

    # updateSellerProfile Pipeline
    builder.create_pipeline_resolver(
        field_name="updateSellerProfile",
        type_name="Mutation",
        functions=[
            profile_delete_functions["lookup_profile_for_update"],
            profile_delete_functions["update_profile"],
        ],
        code_file=RESOLVERS_DIR / "update_seller_profile_resolver.js",
        id_suffix="UpdateSellerProfileResolver",
    )

    # deleteSellerProfile Pipeline
    delete_profile_functions_list = [
        profile_delete_functions["verify_profile_owner_for_delete"],
        profile_delete_functions["query_profile_shares_for_delete"],
        profile_delete_functions["query_profile_invites_for_delete"],
        profile_delete_functions["delete_profile_shares"],
        profile_delete_functions["delete_profile_invites"],
        profile_delete_functions["query_profile_campaigns_for_delete"],
    ]
    # Add delete_profile_orders_cascade function if it exists (cascades order deletion)
    if "delete_profile_orders_cascade" in profile_delete_functions:
        delete_profile_functions_list.append(profile_delete_functions["delete_profile_orders_cascade"])
    
    delete_profile_functions_list.extend([
        profile_delete_functions["delete_profile_campaigns"],
        profile_delete_functions["delete_profile_ownership"],
        profile_delete_functions["delete_profile_metadata"],
    ])

    builder.create_pipeline_resolver(
        field_name="deleteSellerProfile",
        type_name="Mutation",
        functions=delete_profile_functions_list,
        code_file=RESOLVERS_DIR / "delete_seller_profile_resolver.js",
        id_suffix="DeleteSellerProfileResolver",
    )

    # === SHARED CAMPAIGN MUTATIONS ===

    # createSharedCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="createSharedCampaign",
        type_name="Mutation",
        functions=[
            functions["count_user_shared_campaigns"],
            functions["get_catalog_for_shared_campaign"],
            functions["get_account_for_shared_campaign"],
            functions["create_shared_campaign"],
        ],
        code_file=RESOLVERS_DIR / "create_shared_campaign_pipeline_resolver.js",
        id_suffix="CreateSharedCampaignPipelineResolver",
    )

    # updateSharedCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="updateSharedCampaign",
        type_name="Mutation",
        functions=[
            functions["get_shared_campaign_for_update"],
            functions["update_shared_campaign"],
        ],
        code_file=RESOLVERS_DIR / "update_shared_campaign_pipeline_resolver.js",
        id_suffix="UpdateSharedCampaignPipelineResolver",
    )

    # deleteSharedCampaign Pipeline
    builder.create_pipeline_resolver(
        field_name="deleteSharedCampaign",
        type_name="Mutation",
        functions=[
            profile_delete_functions["get_shared_campaign_for_delete"],
            functions["delete_shared_campaign"],
        ],
        code_file=RESOLVERS_DIR / "delete_shared_campaign_pipeline_resolver.js",
        id_suffix="DeleteSharedCampaignPipelineResolver",
    )

    # === ACCOUNT & PREFERENCES MUTATIONS ===

    # updateMyAccount (Lambda)
    builder.create_lambda_resolver(
        field_name="updateMyAccount",
        type_name="Mutation",
        lambda_datasource_name="update_my_account_fn",
        id_suffix="UpdateMyAccountResolver",
    )

    # transferProfileOwnership (Lambda)
    builder.create_lambda_resolver(
        field_name="transferProfileOwnership",
        type_name="Mutation",
        lambda_datasource_name="transfer_ownership_fn",
        id_suffix="TransferProfileOwnershipResolver",
    )

    # updateMyPreferences (JS)
    builder.create_js_resolver(
        field_name="updateMyPreferences",
        type_name="Mutation",
        datasource_name="accounts",
        code_file=RESOLVERS_DIR / "update_my_preferences_resolver.js",
        id_suffix="UpdateMyPreferencesResolver",
    )

    # requestCampaignReport (Lambda)
    builder.create_lambda_resolver(
        field_name="requestCampaignReport",
        type_name="Mutation",
        lambda_datasource_name="request_campaign_report_fn",
        id_suffix="RequestCampaignReportResolver",
    )

    # === PAYMENT METHODS MUTATIONS ===

    # createPaymentMethod Pipeline
    builder.create_pipeline_resolver(
        field_name="createPaymentMethod",
        type_name="Mutation",
        functions=[
            functions["validate_create_payment_method"],
            functions["create_payment_method"],
        ],
        code_file=RESOLVERS_DIR / "create_payment_method_pipeline_resolver.js",
        id_suffix="CreatePaymentMethodResolver",
    )

    # updatePaymentMethod Pipeline
    builder.create_pipeline_resolver(
        field_name="updatePaymentMethod",
        type_name="Mutation",
        functions=[
            functions["validate_update_payment_method"],
            functions["update_payment_method"],
        ],
        code_file=RESOLVERS_DIR / "update_payment_method_pipeline_resolver.js",
        id_suffix="UpdatePaymentMethodResolver",
    )

    # deletePaymentMethod Pipeline (simpler version without QR code deletion until Lambda is implemented)
    builder.create_pipeline_resolver(
        field_name="deletePaymentMethod",
        type_name="Mutation",
        functions=[
            functions["get_payment_method_for_delete"],
            functions["delete_payment_method_from_prefs"],
        ],
        code_file=RESOLVERS_DIR / "delete_payment_method_no_qr_pipeline_resolver.js",
        id_suffix="DeletePaymentMethodResolver",
    )

    # deletePaymentMethodQRCode (Lambda) - direct resolver, not pipeline
    if "delete_qr_code_fn" in lambda_datasources:
        builder.create_lambda_resolver(
            field_name="deletePaymentMethodQRCode",
            type_name="Mutation",
            lambda_datasource_name="delete_qr_code_fn",
            id_suffix="DeletePaymentMethodQRCodeResolver",
        )

    # requestPaymentMethodQRCodeUpload (Lambda) - conditional creation
    if "request_qr_upload_fn" in lambda_datasources:
        builder.create_lambda_resolver(
            field_name="requestPaymentMethodQRCodeUpload",
            type_name="Mutation",
            lambda_datasource_name="request_qr_upload_fn",
            id_suffix="RequestPaymentMethodQRCodeUploadResolver",
        )

    # confirmPaymentMethodQRCodeUpload (Lambda) - conditional creation
    if "confirm_qr_upload_fn" in lambda_datasources:
        builder.create_lambda_resolver(
            field_name="confirmPaymentMethodQRCodeUpload",
            type_name="Mutation",
            lambda_datasource_name="confirm_qr_upload_fn",
            id_suffix="ConfirmPaymentMethodQRCodeUploadResolver",
        )

