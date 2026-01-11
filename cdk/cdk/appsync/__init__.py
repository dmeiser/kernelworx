"""
AppSync GraphQL API module for kernelworx.

This module orchestrates the creation of the complete AppSync GraphQL API infrastructure.
The implementation is split across multiple modules for better organization:

- api.py: API and custom domain creation
- datasources.py: Data source creation (DynamoDB, Lambda, NONE)
- functions/: AppSync function definitions organized by domain
  - sharing.py: Profile sharing and authorization functions
  - campaigns.py: Campaign operation functions
  - orders.py: Order operation functions
  - catalogs.py: Catalog operation functions
  - profiles.py: Profile operation functions
- resolvers/: Python resolver wiring organized by type
  - mutations.py: Mutation resolvers
  - queries.py: Query resolvers
  - fields.py: Field resolvers
- js-resolvers/: AppSync JS/JS pipeline/function code assets
- mapping-templates/: VTL request/response templates
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from .api import create_appsync_api, create_appsync_custom_domain
from .datasources import (
    create_dynamodb_datasources,
    create_lambda_datasources,
    create_none_datasource,
)
from .functions import create_appsync_functions, create_profile_delete_functions
from .resolvers import create_resolvers

if TYPE_CHECKING:
    from aws_cdk import aws_cognito as cognito
    from aws_cdk import aws_dynamodb as dynamodb
    from aws_cdk import aws_lambda as lambda_


@dataclass
class AppSyncResources:
    """Container for all AppSync resources created by setup_appsync."""

    api: appsync.GraphqlApi
    dynamodb_datasources: dict[str, appsync.DynamoDbDataSource]
    lambda_datasources: dict[str, appsync.LambdaDataSource]
    none_datasource: appsync.NoneDataSource
    functions: dict[str, appsync.AppsyncFunction]
    profile_delete_functions: dict[str, appsync.AppsyncFunction]
    domain_name: appsync.CfnDomainName | None
    domain_association: Any | None
    dns_record: Any | None


def setup_appsync(
    scope: Construct,
    env_name: str,
    resource_name: Any,  # Callable[[str], str]
    user_pool: "cognito.IUserPool",
    api_domain: str,
    api_certificate: Any,
    hosted_zone: Any,
    tables: dict[str, "dynamodb.ITable"],
    lambda_functions: dict[str, "lambda_.IFunction"],
) -> AppSyncResources:
    """
    Set up the complete AppSync GraphQL API infrastructure.

    This is the main entry point for creating all AppSync resources.

    Args:
        scope: CDK construct scope
        env_name: Environment name (dev, prod, etc.)
        resource_name: Function to generate resource names
        user_pool: Cognito User Pool for authentication
        api_domain: Custom domain for the API
        api_certificate: ACM certificate for the custom domain
        hosted_zone: Route53 hosted zone for DNS records
        tables: Dictionary of DynamoDB tables
        lambda_functions: Dictionary of Lambda functions

    Returns:
        AppSyncResources containing all created resources
    """
    # Create the GraphQL API
    api = create_appsync_api(
        scope=scope,
        env_name=env_name,
        resource_name=resource_name,
        user_pool=user_pool,
        api_domain=api_domain,
        api_certificate=api_certificate,
        hosted_zone=hosted_zone,
    )

    # Create DynamoDB data sources
    dynamodb_datasources = create_dynamodb_datasources(scope, api, tables)

    # Create NONE data source for computed fields
    none_datasource = create_none_datasource(api)
    dynamodb_datasources["none"] = none_datasource

    # Create Lambda data sources
    lambda_datasources = create_lambda_datasources(api, lambda_functions)

    # Create AppSync functions
    functions = create_appsync_functions(scope, api, env_name, dynamodb_datasources, lambda_datasources)

    # Create profile delete functions
    profile_delete_functions = create_profile_delete_functions(scope, api, env_name, dynamodb_datasources)

    # Create all resolvers
    create_resolvers(
        scope=scope,
        api=api,
        env_name=env_name,
        datasources=dynamodb_datasources,
        lambda_datasources=lambda_datasources,
        functions=functions,
        profile_delete_functions=profile_delete_functions,
    )

    # Create custom domain (if certificate available)
    domain_name, domain_association, dns_record = create_appsync_custom_domain(
        scope=scope,
        api=api,
        api_domain=api_domain,
        api_certificate=api_certificate,
        hosted_zone=hosted_zone,
    )

    return AppSyncResources(
        api=api,
        dynamodb_datasources=dynamodb_datasources,
        lambda_datasources=lambda_datasources,
        none_datasource=none_datasource,
        functions=functions,
        profile_delete_functions=profile_delete_functions,
        domain_name=domain_name,
        domain_association=domain_association,
        dns_record=dns_record,
    )


__all__ = ["setup_appsync", "AppSyncResources"]
