"""
AppSync functions for catalog operations.

This module contains all AppSync functions related to:
- Catalog CRUD operations
"""

from pathlib import Path
from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

# Path to resolvers directory
RESOLVERS_DIR = Path(__file__).parent.parent.parent / "resolvers"


def create_catalog_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for catalog operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

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
