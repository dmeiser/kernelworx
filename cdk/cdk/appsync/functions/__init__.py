"""
AppSync functions module.

This module combines all domain-specific AppSync function definitions.
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from .campaigns import create_campaign_functions
from .catalogs import create_catalog_functions
from .orders import create_order_functions
from .payment_methods import create_payment_methods_functions
from .profiles import create_profile_delete_functions, create_profile_functions
from .sharing import create_sharing_functions


def create_appsync_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create all AppSync functions for pipeline resolvers.

    This function combines functions from all domain-specific modules.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # Merge functions from all domain modules
    functions.update(create_sharing_functions(scope, api, env_name, datasources))
    functions.update(create_campaign_functions(scope, api, env_name, datasources))
    functions.update(create_order_functions(scope, api, env_name, datasources))
    functions.update(create_catalog_functions(scope, api, env_name, datasources))
    functions.update(create_profile_functions(scope, api, env_name, datasources))
    functions.update(create_payment_methods_functions(scope, api, env_name, datasources, lambda_datasources))

    return functions


__all__ = [
    "create_appsync_functions",
    "create_profile_delete_functions",
]
