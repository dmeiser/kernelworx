"""AppSync resolvers module for GraphQL API.

This module provides modular resolver creation for the AppSync GraphQL API,
organized into:
- mutations: Mutation resolvers (create, update, delete operations)
- queries: Query resolvers (read operations)
- fields: Field resolvers (nested type resolution)
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from .fields import create_field_resolvers
from .mutations import create_mutation_resolvers
from .queries import create_query_resolvers

__all__ = [
    "create_resolvers",
    "create_mutation_resolvers",
    "create_query_resolvers",
    "create_field_resolvers",
]


def create_resolvers(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
    lambda_datasources: dict[str, appsync.LambdaDataSource],
    functions: dict[str, appsync.AppsyncFunction],
    profile_delete_functions: dict[str, appsync.AppsyncFunction],
) -> None:
    """
    Create all AppSync resolvers for the GraphQL API.

    Orchestrates creation of mutation, query, and field resolvers.

    Args:
        scope: CDK construct scope
        api: AppSync GraphQL API
        env_name: Environment name (dev, prod, etc.)
        datasources: Dictionary of AppSync data sources
        lambda_datasources: Dictionary of Lambda data sources
        functions: Dictionary of reusable AppSync functions
        profile_delete_functions: Dictionary of profile-related AppSync functions
    """
    # Create all resolver types in order
    create_mutation_resolvers(scope, api, env_name, datasources, lambda_datasources, functions, profile_delete_functions)
    create_query_resolvers(scope, api, env_name, datasources, lambda_datasources, functions, profile_delete_functions)
    create_field_resolvers(scope, api, env_name, datasources, lambda_datasources, functions, profile_delete_functions)
