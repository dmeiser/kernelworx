"""
IAM roles and policies for the CDK stack.

Creates:
- Lambda execution role with DynamoDB and S3 permissions
- AppSync service role for direct DynamoDB resolvers
"""

from typing import Callable, Dict, List, Optional

from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


def create_lambda_execution_role(
    stack: Construct,
    rn: Callable[[str], str],
    tables: Dict[str, dynamodb.ITable],
    exports_bucket: s3.IBucket,
) -> iam.Role:
    """Create the Lambda execution role with appropriate permissions.

    Args:
        stack: CDK Construct (usually the Stack instance)
        rn: helper function to create resource names
        tables: Dict of DynamoDB tables to grant access to
        exports_bucket: S3 bucket for exports

    Returns:
        The Lambda execution role
    """
    # Lambda execution role (base permissions)
    lambda_execution_role = iam.Role(
        stack,
        "LambdaExecutionRole",
        role_name=rn("kernelworx-lambda-exec"),
        assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")],
    )

    # Grant Lambda role access to all tables
    for table_name, table in tables.items():
        table.grant_read_write_data(lambda_execution_role)

        # Grant access to GSI indexes
        lambda_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query", "dynamodb:Scan"],
                resources=[f"{table.table_arn}/index/*"],
            )
        )

    # Grant Lambda role access to exports bucket
    exports_bucket.grant_read_write(lambda_execution_role)

    # Grant Lambda role permission to create CloudFront invalidations
    lambda_execution_role.add_to_policy(
        iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation"],
            resources=["*"],  # CloudFront invalidation requires wildcard resource
        )
    )

    return lambda_execution_role


def create_appsync_service_role(
    stack: Construct,
    rn: Callable[[str], str],
    tables: Dict[str, dynamodb.ITable],
    tables_without_gsi: Optional[List[str]] = None,
) -> iam.Role:
    """Create the AppSync service role for direct DynamoDB resolvers.

    Args:
        stack: CDK Construct (usually the Stack instance)
        rn: helper function to create resource names
        tables: Dict of DynamoDB tables to grant access to
        tables_without_gsi: List of table names that should NOT get GSI access

    Returns:
        The AppSync service role
    """
    if tables_without_gsi is None:
        tables_without_gsi = []

    # AppSync service role
    appsync_service_role = iam.Role(
        stack,
        "AppSyncServiceRole",
        role_name=rn("kernelworx-appsync"),
        assumed_by=iam.ServicePrincipal("appsync.amazonaws.com"),
    )

    # Grant AppSync role access to all tables
    for table_name, table in tables.items():
        table.grant_read_write_data(appsync_service_role)

        # Grant access to GSI indexes (unless excluded)
        if table_name not in tables_without_gsi:
            appsync_service_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{table.table_arn}/index/*"],
                )
            )

    return appsync_service_role


def create_user_pool_sms_role(
    stack: Construct,
    role_name: str,
) -> iam.Role:
    """Create the SMS role for Cognito User Pool MFA.

    Args:
        stack: CDK Construct (usually the Stack instance)
        role_name: Full name of the role

    Returns:
        The SMS role for Cognito
    """
    from aws_cdk import RemovalPolicy

    sms_role = iam.Role(
        stack,
        "UserPoolsmsRole",
        assumed_by=iam.ServicePrincipal("cognito-idp.amazonaws.com"),
        role_name=role_name,
        inline_policies={
            "UserPoolSmsPolicy": iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["sns:Publish"],
                        resources=["arn:aws:sns:*:*:*"],
                    )
                ]
            )
        },
    )
    sms_role.apply_removal_policy(RemovalPolicy.RETAIN)

    return sms_role
