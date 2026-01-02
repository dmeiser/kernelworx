"""
AppSync functions for order operations.

This module contains all AppSync functions related to:
- Order CRUD operations
- Order queries by campaign/profile
- Catalog lookups for orders
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from ..api import RESOLVERS_DIR


def create_order_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for order operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

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

    # === QUERY FUNCTIONS (ORDER-RELATED) ===

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

    return functions
