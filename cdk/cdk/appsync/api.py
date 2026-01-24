"""AppSync API and custom domain creation."""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_route53 as route53
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_cognito as cognito


# Asset locations: keep JS resolver code and VTL templates under the appsync/ folder
RESOLVERS_DIR = Path(__file__).parent / "js-resolvers"
MAPPING_TEMPLATES_DIR = Path(__file__).parent / "mapping-templates"


def create_appsync_api(
    scope: Construct,
    env_name: str,
    resource_name: Any,  # Callable[[str], str]
    user_pool: "cognito.IUserPool",
    api_domain: str,
    api_certificate: Any,  # ICertificate
    hosted_zone: "route53.IHostedZone",
) -> appsync.GraphqlApi:
    """
    Create the AppSync GraphQL API with authorization.

    Args:
        scope: CDK construct scope
        env_name: Environment name (dev, prod, etc.)
        resource_name: Function to generate resource names
        user_pool: Cognito User Pool for authentication
        api_domain: Custom domain for the API
        api_certificate: ACM certificate for the custom domain
        hosted_zone: Route53 hosted zone for DNS records

    Returns:
        The created GraphQL API
    """
    # Read GraphQL schema from file
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema", "schema.graphql")

    # Determine if logging should be enabled
    enable_appsync_logging = os.getenv("ENABLE_APPSYNC_LOGGING", "false").lower() == "true"

    # Create AppSync GraphQL API
    api_name = resource_name("kernelworx-api")
    print(f"Creating AppSync API: {api_name}")

    api = appsync.GraphqlApi(
        scope,
        "Api",
        name=api_name,
        definition=appsync.Definition.from_file(schema_path),
        authorization_config=appsync.AuthorizationConfig(
            default_authorization=appsync.AuthorizationMode(
                authorization_type=appsync.AuthorizationType.USER_POOL,
                user_pool_config=appsync.UserPoolConfig(user_pool=user_pool),
            ),
        ),
        xray_enabled=True,
        log_config=(
            appsync.LogConfig(
                field_log_level=appsync.FieldLogLevel.ALL,
                exclude_verbose_content=False,
            )
            if enable_appsync_logging
            else None
        ),
    )
    api.apply_removal_policy(RemovalPolicy.RETAIN)

    CfnOutput(
        scope,
        "AppSyncApiKey",
        value="NOT_AVAILABLE",
        description="AppSync API Key for unauthenticated access to public catalogs",
    )

    return api


def create_appsync_custom_domain(
    scope: Construct,
    api: appsync.GraphqlApi,
    api_domain: str,
    api_certificate: Any,
    hosted_zone: "route53.IHostedZone",
) -> tuple[appsync.CfnDomainName | None, Any, Any]:
    """
    Create AppSync custom domain and DNS records.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        api_domain: Custom domain name
        api_certificate: ACM certificate
        hosted_zone: Route53 hosted zone

    Returns:
        Tuple of (domain_name, domain_association, dns_record)
    """
    print(f"Creating AppSync custom domain: {api_domain}")

    domain_name = appsync.CfnDomainName(
        scope,
        "ApiDomainNameV2",
        certificate_arn=api_certificate.certificate_arn,
        domain_name=api_domain,
    )
    domain_name.apply_removal_policy(RemovalPolicy.RETAIN)

    # Associate custom domain with API
    domain_association = appsync.CfnDomainNameApiAssociation(
        scope,
        "ApiDomainAssociation",
        api_id=api.api_id,
        domain_name=domain_name.attr_domain_name,
    )
    domain_association.add_dependency(domain_name)

    # Route53 record for AppSync custom domain
    dns_record = route53.CnameRecord(
        scope,
        "ApiDomainRecord",
        zone=hosted_zone,
        record_name=api_domain,
        domain_name=domain_name.attr_app_sync_domain_name,
    )
    dns_record.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

    return domain_name, domain_association, dns_record
