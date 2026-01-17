"""
AppSync functions for payment methods operations.

This module contains all AppSync functions related to:
- Fetching and managing custom payment methods
- QR code operations
- Payment method authorization
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from ..api import RESOLVERS_DIR


def create_payment_methods_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for payment methods operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # === QUERY FUNCTIONS ===

    # GetPaymentMethodsFn - Fetch custom payment methods from DynamoDB
    functions["get_payment_methods"] = appsync.AppsyncFunction(
        scope,
        "GetPaymentMethodsFn",
        name=f"GetPaymentMethodsFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_payment_methods_fn.js")),
    )

    # InjectGlobalPaymentMethodsFn - Add Cash/Check and sort
    # Uses NONE data source since it only manipulates stash data
    none_ds = api.add_none_data_source("PaymentMethodsNoneDS", name="PaymentMethodsNoneDataSource")
    functions["inject_global_payment_methods"] = appsync.AppsyncFunction(
        scope,
        "InjectGlobalPaymentMethodsFn",
        name=f"InjectGlobalPaymentMethodsFn_{env_name}",
        api=api,
        data_source=none_ds,
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "inject_global_payment_methods_fn.js")),
    )

    # SetOwnerAccountIdInStashFn - Set ctx.stash.ownerAccountId for field resolvers
    # This enables the qrCodeUrl field resolver to generate presigned URLs
    functions["set_owner_account_id_in_stash"] = appsync.AppsyncFunction(
        scope,
        "SetOwnerAccountIdInStashFn",
        name=f"SetOwnerAccountIdInStashFn_{env_name}",
        api=api,
        data_source=none_ds,
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "set_owner_account_id_in_stash_fn.js")),
    )

    # === PAYMENT METHODS FOR PROFILE QUERY FUNCTIONS ===
    # These functions are needed for paymentMethodsForProfile query
    if "generate_qr_code_presigned_url_fn" in lambda_datasources:
        # CheckPaymentMethodsAccessFn - Verify profile access and determine QR visibility
        functions["check_payment_methods_access"] = appsync.AppsyncFunction(
            scope,
            "CheckPaymentMethodsAccessFn",
            name=f"CheckPaymentMethodsAccessFn_{env_name}",
            api=api,
            data_source=datasources["shares"],
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_payment_methods_access_fn.js")),
        )

        # GetOwnerPaymentMethodsFn - Fetch owner's payment methods
        functions["get_owner_payment_methods"] = appsync.AppsyncFunction(
            scope,
            "GetOwnerPaymentMethodsFn",
            name=f"GetOwnerPaymentMethodsFn_{env_name}",
            api=api,
            data_source=datasources["accounts"],
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_owner_payment_methods_fn.js")),
        )

        # FilterPaymentMethodsByAccessFn - Filter QR codes and inject globals
        filter_none_ds = api.add_none_data_source(
            "FilterPaymentMethodsNoneDS", name="FilterPaymentMethodsNoneDataSource"
        )
        functions["filter_payment_methods_by_access"] = appsync.AppsyncFunction(
            scope,
            "FilterPaymentMethodsByAccessFn",
            name=f"FilterPaymentMethodsByAccessFn_{env_name}",
            api=api,
            data_source=filter_none_ds,
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "filter_payment_methods_by_access_fn.js")),
        )

    # === MUTATION FUNCTIONS ===

    # ValidatePaymentMethodAppSyncFn - Lambda step to validate payment method exists for account
    if "validate_payment_method_fn" in lambda_datasources:
        functions["validate_payment_method"] = appsync.AppsyncFunction(
            scope,
            "ValidatePaymentMethodAppSyncFn",
            name=f"ValidatePaymentMethodFn_{env_name}",
            api=api,
            data_source=lambda_datasources["validate_payment_method_fn"],
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lambda_passthrough_resolver.js")),
        )

    # ValidateCreatePaymentMethodFn - Validate new payment method
    functions["validate_create_payment_method"] = appsync.AppsyncFunction(
        scope,
        "ValidateCreatePaymentMethodFn",
        name=f"ValidateCreatePaymentMethodFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "validate_create_payment_method_fn.js")),
    )

    # CreatePaymentMethodFn - Insert payment method into DynamoDB
    functions["create_payment_method"] = appsync.AppsyncFunction(
        scope,
        "CreatePaymentMethodFn",
        name=f"CreatePaymentMethodFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_payment_method_fn.js")),
    )

    # ValidateUpdatePaymentMethodFn
    functions["validate_update_payment_method"] = appsync.AppsyncFunction(
        scope,
        "ValidateUpdatePaymentMethodFn",
        name=f"ValidateUpdatePaymentMethodFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "validate_update_payment_method_fn.js")),
    )

    # UpdatePaymentMethodFn
    functions["update_payment_method"] = appsync.AppsyncFunction(
        scope,
        "UpdatePaymentMethodFn",
        name=f"UpdatePaymentMethodFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_payment_method_fn.js")),
    )

    # GetPaymentMethodForDeleteFn - Fetch and validate for deletion
    functions["get_payment_method_for_delete"] = appsync.AppsyncFunction(
        scope,
        "GetPaymentMethodForDeleteFn",
        name=f"GetPaymentMethodForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_payment_method_for_delete_fn.js")),
    )

    # DeletePaymentMethodFromPrefsFn - Remove from array
    functions["delete_payment_method_from_prefs"] = appsync.AppsyncFunction(
        scope,
        "DeletePaymentMethodFromPrefsFn",
        name=f"DeletePaymentMethodFromPrefsFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_payment_method_from_prefs_fn.js")),
    )

    # DeletePaymentMethodQRCodeFn (Lambda)
    if "delete_qr_code_fn" in lambda_datasources:
        functions["delete_payment_method_qr"] = appsync.AppsyncFunction(
            scope,
            "DeletePaymentMethodQRCodeFn",
            name=f"DeletePaymentMethodQRCodeFn_{env_name}",
            api=api,
            data_source=lambda_datasources["delete_qr_code_fn"],
            runtime=appsync.FunctionRuntime.JS_1_0_0,
            code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lambda_passthrough_resolver.js")),
        )

    return functions
