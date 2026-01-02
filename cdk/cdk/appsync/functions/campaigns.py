"""
AppSync functions for campaign operations.

This module contains all AppSync functions related to:
- Campaign CRUD operations
- Shared campaigns
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from ..api import RESOLVERS_DIR


def create_campaign_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for campaign operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

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

    return functions
