import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct

# Region abbreviation mapping for resource naming
# Pattern: {name}-{region_abbrev}-{env} e.g. kernelworx-ue1-dev
REGION_ABBREVIATIONS = {
    "us-east-1": "ue1",
    "us-east-2": "ue2",
    "us-west-1": "uw1",
    "us-west-2": "uw2",
    "eu-west-1": "ew1",
    "eu-west-2": "ew2",
    "eu-west-3": "ew3",
    "eu-central-1": "ec1",
    "eu-north-1": "en1",
    "ap-northeast-1": "ane1",   # Tokyo
    "ap-northeast-2": "ane2",   # Seoul
    "ap-northeast-3": "ane3",   # Osaka
    "ap-southeast-1": "ase1",   # Singapore
    "ap-southeast-2": "ase2",   # Sydney
    "ap-south-1": "as1",        # Mumbai
    "sa-east-1": "se1",        # São Paulo
    "ca-central-1": "cc1",     # Canada
}


class CdkStack(Stack):
    """
    Popcorn Sales Manager - Core Infrastructure Stack

    Creates foundational resources:
    - DynamoDB table with single-table design
    - S3 buckets for static assets and exports
    - IAM roles for Lambda functions
    - Cognito User Pool for authentication
    - AppSync GraphQL API
    - CloudFront distribution for SPA
    """

    def __init__(
        self, scope: Construct, construct_id: str, env_name: str = "dev", **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name

        # Get region abbreviation for resource naming
        # Uses CDK_DEFAULT_REGION or falls back to us-east-1
        region = os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION", "us-east-1")
        self.region_abbrev = REGION_ABBREVIATIONS.get(region, region[:3])

        # Helper for consistent resource naming: {name}-{region}-{env}
        def rn(name: str) -> str:
            """Generate resource name with region and environment suffix."""
            return f"{name}-{self.region_abbrev}-{env_name}"

        self.resource_name = rn  # Make available to instance methods

        # Load configuration from environment variables
        base_domain = os.getenv("BASE_DOMAIN", "kernelworx.app")

        # ====================================================================
        # Route 53 & DNS Configuration
        # ====================================================================

        # Import existing hosted zone
        self.hosted_zone = route53.HostedZone.from_lookup(
            self,
            "HostedZone",
            domain_name=base_domain,
        )

        # Define domain names based on environment
        if env_name == "prod":
            self.site_domain = base_domain
            self.api_domain = f"api.{base_domain}"
            self.cognito_domain = f"login.{base_domain}"
        else:
            self.site_domain = f"{env_name}.{base_domain}"
            self.api_domain = f"api.{env_name}.{base_domain}"
            self.cognito_domain = f"login.{env_name}.{base_domain}"

        # ACM Certificate for AppSync API and CloudFront (must be in us-east-1 for CloudFront)
        # This certificate is used for api.{domain} and {site_domain}
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=self.api_domain,
            subject_alternative_names=[
                self.site_domain,  # CloudFront distribution
            ],
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )

        # Separate ACM Certificate for Cognito custom domain
        # Must be in us-east-1 for Cognito
        # Using DnsValidatedCertificate because it actually WAITS for the certificate
        # to be issued (ISSUED status) before allowing dependent resources to proceed.
        # The standard Certificate construct with from_dns() only creates DNS records
        # but doesn't wait for validation, which causes Cognito UserPoolDomain to fail
        # with "Invalid request provided" because it requires a fully validated certificate.
        self.cognito_certificate = acm.DnsValidatedCertificate(
            self,
            "CognitoCertificate",
            domain_name=self.cognito_domain,
            hosted_zone=self.hosted_zone,
            region="us-east-1",  # Cognito custom domains require us-east-1
        )

        # ====================================================================
        # DynamoDB Table - Single Table Design
        # ====================================================================

        # Check if we should import existing table
        existing_table_name = self.node.try_get_context("table_name")
        if existing_table_name:
            self.table = dynamodb.Table.from_table_name(self, "PsmApp", existing_table_name)
        else:
            self.table = dynamodb.Table(
                self,
                "PsmApp",
                table_name=rn("kernelworx-app"),
                partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                    point_in_time_recovery_enabled=True
                ),
                removal_policy=RemovalPolicy.RETAIN,  # Don't delete on stack destroy
                stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,  # For audit logging
            )

            # GSI1: Shares by target account (for "My Shared Profiles" view)
            self.table.add_global_secondary_index(
                index_name="GSI1",
                partition_key=dynamodb.Attribute(name="GSI1PK", type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name="GSI1SK", type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI2: Orders by profile (for cross-season order queries)
            self.table.add_global_secondary_index(
                index_name="GSI2",
                partition_key=dynamodb.Attribute(name="GSI2PK", type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name="GSI2SK", type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI3: Catalog ownership and sharing (for catalog management)
            self.table.add_global_secondary_index(
                index_name="GSI3",
                partition_key=dynamodb.Attribute(name="GSI3PK", type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name="GSI3SK", type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI4: Profile lookup by profileId (for direct getProfile queries)
            self.table.add_global_secondary_index(
                index_name="GSI4",
                partition_key=dynamodb.Attribute(
                    name="profileId", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI5: Season lookup by seasonId (for listing all items with seasonId - orders, etc)
            self.table.add_global_secondary_index(
                index_name="GSI5",
                partition_key=dynamodb.Attribute(
                    name="seasonId", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI6: Order lookup by orderId (for direct getOrder queries)
            self.table.add_global_secondary_index(
                index_name="GSI6",
                partition_key=dynamodb.Attribute(
                    name="orderId", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI7: Season lookup by seasonId + SK (for direct getSeason queries)
            self.table.add_global_secondary_index(
                index_name="GSI7",
                partition_key=dynamodb.Attribute(
                    name="seasonId", type=dynamodb.AttributeType.STRING
                ),
                sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI8: Account lookup by email (for share-direct pipeline resolver)
            self.table.add_global_secondary_index(
                index_name="GSI8",
                partition_key=dynamodb.Attribute(name="email", type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI9: Invite lookup by inviteCode (for redeem-invite pipeline resolver)
            self.table.add_global_secondary_index(
                index_name="GSI9",
                partition_key=dynamodb.Attribute(
                    name="inviteCode", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # TTL configuration for invite expiration
            # ProfileInvite and CatalogShareInvite items have expiresAt attribute
            cfn_table = self.table.node.default_child
            cfn_table.time_to_live_specification = (
                dynamodb.CfnTable.TimeToLiveSpecificationProperty(
                    attribute_name="expiresAt",
                    enabled=True,
                )
            )

        # ====================================================================
        # New Multi-Table Design (Migration from Single-Table)
        # ====================================================================

        # Accounts Table
        self.accounts_table = dynamodb.Table(
            self,
            "AccountsTable",
            table_name=rn("kernelworx-accounts"),
            partition_key=dynamodb.Attribute(name="accountId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for email lookup (account by email)
        self.accounts_table.add_global_secondary_index(
            index_name="email-index",
            partition_key=dynamodb.Attribute(name="email", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Catalogs Table
        self.catalogs_table = dynamodb.Table(
            self,
            "CatalogsTable",
            table_name=rn("kernelworx-catalogs"),
            partition_key=dynamodb.Attribute(name="catalogId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for catalog owner lookup
        self.catalogs_table.add_global_secondary_index(
            index_name="ownerAccountId-index",
            partition_key=dynamodb.Attribute(
                name="ownerAccountId", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for public catalog listing
        self.catalogs_table.add_global_secondary_index(
            index_name="isPublic-createdAt-index",
            partition_key=dynamodb.Attribute(
                name="isPublicStr", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="createdAt", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Profiles Table - stores profile METADATA only
        # NEW STRUCTURE (V2): PK=ownerAccountId, SK=profileId
        # This enables direct query for listMyProfiles (no GSI needed)
        # Shares and invites are in separate tables now
        self.profiles_table = dynamodb.Table(
            self,
            "ProfilesTableV2",
            table_name=rn("kernelworx-profiles"),
            partition_key=dynamodb.Attribute(
                name="ownerAccountId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for direct profile lookup by profileId (sparse index for getProfile)
        self.profiles_table.add_global_secondary_index(
            index_name="profileId-index",
            partition_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Shares Table (NEW - separated from profiles for cleaner design)
        # PK: profileId, SK: targetAccountId
        # Enables direct query for "all shares for this profile"
        self.shares_table = dynamodb.Table(
            self,
            "SharesTable",
            table_name=rn("kernelworx-shares"),
            partition_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="targetAccountId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for "profiles shared with me" query
        self.shares_table.add_global_secondary_index(
            index_name="targetAccountId-index",
            partition_key=dynamodb.Attribute(
                name="targetAccountId", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Invites Table (NEW - separated from profiles for cleaner design)
        # PK: inviteCode (enables direct lookup)
        # TTL: expiresAt (automatic cleanup of expired invites)
        self.invites_table = dynamodb.Table(
            self,
            "InvitesTable",
            table_name=rn("kernelworx-invites"),
            partition_key=dynamodb.Attribute(name="inviteCode", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for "invites for this profile" query
        self.invites_table.add_global_secondary_index(
            index_name="profileId-index",
            partition_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # TTL for invites (automatic expiration)
        cfn_invites_table = self.invites_table.node.default_child
        cfn_invites_table.time_to_live_specification = (
            dynamodb.CfnTable.TimeToLiveSpecificationProperty(
                attribute_name="expiresAt",
                enabled=True,
            )
        )

        # Seasons Table V2
        # NEW STRUCTURE: PK=profileId, SK=seasonId
        # This enables direct query for listSeasonsByProfile (no GSI needed)
        self.seasons_table = dynamodb.Table(
            self,
            "SeasonsTableV2",
            table_name=rn("kernelworx-seasons"),
            partition_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="seasonId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for direct getSeason by seasonId (sparse index)
        self.seasons_table.add_global_secondary_index(
            index_name="seasonId-index",
            partition_key=dynamodb.Attribute(name="seasonId", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for seasons by catalog (for checking catalog in-use before deletion)
        self.seasons_table.add_global_secondary_index(
            index_name="catalogId-index",
            partition_key=dynamodb.Attribute(name="catalogId", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.KEYS_ONLY,
        )

        # Orders Table
        # Orders Table V2: PK=seasonId, SK=orderId for efficient season-based queries
        # Direct order lookups use orderId-index GSI
        self.orders_table = dynamodb.Table(
            self,
            "OrdersTableV2",
            table_name=rn("kernelworx-orders"),
            partition_key=dynamodb.Attribute(name="seasonId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="orderId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for direct order lookup by orderId (for getOrder, updateOrder, deleteOrder)
        self.orders_table.add_global_secondary_index(
            index_name="orderId-index",
            partition_key=dynamodb.Attribute(name="orderId", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for orders by profile (cross-season order lookup)
        self.orders_table.add_global_secondary_index(
            index_name="profileId-index",
            partition_key=dynamodb.Attribute(name="profileId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="createdAt", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ====================================================================
        # S3 Buckets
        # ====================================================================

        # Static assets bucket (for SPA hosting)
        # Check if we should import existing bucket
        existing_static_bucket = self.node.try_get_context("static_bucket_name")
        if existing_static_bucket:
            self.static_assets_bucket = s3.Bucket.from_bucket_name(
                self, "StaticAssets", existing_static_bucket
            )
        else:
            self.static_assets_bucket = s3.Bucket(
                self,
                "StaticAssets",
                bucket_name=rn("kernelworx-static"),
                versioned=True,
                encryption=s3.BucketEncryption.S3_MANAGED,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                removal_policy=RemovalPolicy.RETAIN,
            )

        # Exports bucket (for generated reports)
        # Check if we should import existing bucket
        existing_exports_bucket = self.node.try_get_context("exports_bucket_name")
        if existing_exports_bucket:
            self.exports_bucket = s3.Bucket.from_bucket_name(
                self, "Exports", existing_exports_bucket
            )
        else:
            self.exports_bucket = s3.Bucket(
                self,
                "Exports",
                bucket_name=rn("kernelworx-exports"),
                versioned=False,
                encryption=s3.BucketEncryption.S3_MANAGED,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                removal_policy=RemovalPolicy.RETAIN,
            )

        # ====================================================================
        # IAM Roles
        # ====================================================================

        # Lambda execution role (base permissions)
        self.lambda_execution_role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name=rn("kernelworx-lambda-exec"),
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Grant Lambda role access to DynamoDB table
        self.table.grant_read_write_data(self.lambda_execution_role)

        # Grant Lambda role access to all GSI indexes (required for queries)
        self.lambda_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query", "dynamodb:Scan"],
                resources=[f"{self.table.table_arn}/index/*"],
            )
        )

        # Grant Lambda role access to new multi-table design tables
        self.accounts_table.grant_read_write_data(self.lambda_execution_role)
        self.catalogs_table.grant_read_write_data(self.lambda_execution_role)
        self.profiles_table.grant_read_write_data(self.lambda_execution_role)
        self.seasons_table.grant_read_write_data(self.lambda_execution_role)
        self.orders_table.grant_read_write_data(self.lambda_execution_role)
        self.shares_table.grant_read_write_data(self.lambda_execution_role)
        self.invites_table.grant_read_write_data(self.lambda_execution_role)

        # Grant Lambda role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.seasons_table,
            self.orders_table,
            self.shares_table,
            self.invites_table,
        ]:
            self.lambda_execution_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{table.table_arn}/index/*"],
                )
            )

        # Grant Lambda role access to exports bucket
        self.exports_bucket.grant_read_write(self.lambda_execution_role)

        # AppSync service role (for direct DynamoDB resolvers)
        self.appsync_service_role = iam.Role(
            self,
            "AppSyncServiceRole",
            role_name=rn("kernelworx-appsync"),
            assumed_by=iam.ServicePrincipal("appsync.amazonaws.com"),
        )

        # Grant AppSync role access to DynamoDB table
        self.table.grant_read_write_data(self.appsync_service_role)

        # Grant AppSync role access to all GSI indexes (required for imported tables)
        self.appsync_service_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query", "dynamodb:Scan"],
                resources=[f"{self.table.table_arn}/index/*"],
            )
        )

        # Grant AppSync role access to new multi-table design tables
        self.accounts_table.grant_read_write_data(self.appsync_service_role)
        self.catalogs_table.grant_read_write_data(self.appsync_service_role)
        self.profiles_table.grant_read_write_data(self.appsync_service_role)
        self.seasons_table.grant_read_write_data(self.appsync_service_role)
        self.orders_table.grant_read_write_data(self.appsync_service_role)
        self.shares_table.grant_read_write_data(self.appsync_service_role)
        self.invites_table.grant_read_write_data(self.appsync_service_role)

        # Grant AppSync role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.seasons_table,
            self.orders_table,
            self.shares_table,
            self.invites_table,
        ]:
            self.appsync_service_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{table.table_arn}/index/*"],
                )
            )

        # ====================================================================
        # Lambda Functions
        # ====================================================================

        # Path to Lambda source code (parent directory)
        lambda_src_path = os.path.join(os.path.dirname(__file__), "..", "..")

        # Common Lambda environment variables
        lambda_env = {
            "TABLE_NAME": self.table.table_name,
            "EXPORTS_BUCKET": self.exports_bucket.bucket_name,
            "POWERTOOLS_SERVICE_NAME": "kernelworx",
            "LOG_LEVEL": "INFO",
            # New multi-table design table names
            "ACCOUNTS_TABLE_NAME": self.accounts_table.table_name,
            "CATALOGS_TABLE_NAME": self.catalogs_table.table_name,
            "PROFILES_TABLE_NAME": self.profiles_table.table_name,
            "SEASONS_TABLE_NAME": self.seasons_table.table_name,
            "ORDERS_TABLE_NAME": self.orders_table.table_name,
            "SHARES_TABLE_NAME": self.shares_table.table_name,
            "INVITES_TABLE_NAME": self.invites_table.table_name,
        }

        # Create Lambda Layer for shared dependencies
        # This reduces function deployment size by sharing common packages
        lambda_layer_path = os.path.join(os.path.dirname(__file__), "..", "lambda-layer")

        # Check if layer exists, if not create it
        if not os.path.exists(lambda_layer_path):
            os.makedirs(lambda_layer_path, exist_ok=True)

        self.shared_layer = lambda_.LayerVersion(
            self,
            "SharedDependenciesLayer",
            layer_version_name=rn("kernelworx-deps"),
            code=lambda_.Code.from_asset(lambda_layer_path),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
            description="Shared Python dependencies for Lambda functions",
        )

        # Use only the src directory for Lambda code (not the entire repo)
        lambda_code_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")

        lambda_code = lambda_.Code.from_asset(
            lambda_code_path,
            exclude=[
                "__pycache__",
                "*.pyc",
                ".pytest_cache",
            ],
        )

        # Profile Sharing Lambda Functions
        # NOTE: create_profile_invite Lambda REMOVED - replaced with JS resolver
        # NOTE: redeem_profile_invite Lambda REMOVED - replaced with pipeline resolver
        # NOTE: share_profile_direct Lambda REMOVED - replaced with pipeline resolver
        # NOTE: revoke_share Lambda REMOVED - replaced with VTL DynamoDB resolver
        # NOTE: update_season, delete_season Lambdas REMOVED - replaced with JS pipeline resolvers

        # Order Operations Lambda Functions
        # NOTE: create_order Lambda REMOVED - replaced with pipeline resolver

        self.create_profile_fn = lambda_.Function(
            self,
            "CreateProfileFnV2",
            function_name=rn("kernelworx-create-profile"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.profile_operations.create_seller_profile",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.request_season_report_fn = lambda_.Function(
            self,
            "RequestSeasonReportFnV2",
            function_name=rn("kernelworx-request-report"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.report_generation.request_season_report",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # Reports may take longer
            memory_size=512,  # More memory for Excel generation
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.unit_reporting_fn = lambda_.Function(
            self,
            "UnitReportingFnV2",
            function_name=rn("kernelworx-unit-reporting"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.unit_reporting.get_unit_report",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # May need time for large units
            memory_size=512,  # More memory for aggregation
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Account Operations Lambda Functions
        self.update_my_account_fn = lambda_.Function(
            self,
            "UpdateMyAccountFnV2",
            function_name=rn("kernelworx-update-account"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.account_operations.update_my_account",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Post-Authentication Lambda (Cognito Trigger)
        self.post_auth_fn = lambda_.Function(
            self,
            "PostAuthenticationFnV2",
            function_name=rn("kernelworx-post-auth"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.post_authentication.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # ====================================================================
        # Cognito User Pool - Authentication (Essentials tier)
        # ====================================================================

        # Check if we should import existing user pool
        existing_user_pool_id = self.node.try_get_context("user_pool_id")
        if existing_user_pool_id:
            # Import existing User Pool
            # Note: WebAuthn Relying Party ID must be configured manually via AWS Console
            # at: Cognito > User Pools > [Pool] > App Integration > Passkey
            # Set "Third-party domain" to the application domain (e.g., dev.kernelworx.app)
            self.user_pool = cognito.UserPool.from_user_pool_id(
                self, "UserPool", existing_user_pool_id
            )

            # For imported pools, either import existing client or create new one
            existing_client_id = self.node.try_get_context("user_pool_client_id")
            if existing_client_id:
                self.user_pool_client = cognito.UserPoolClient.from_user_pool_client_id(
                    self, "AppClient", existing_client_id
                )
            else:
                # Create new client for imported user pool
                self.user_pool_client = self.user_pool.add_client(
                    "AppClient",
                    user_pool_client_name="KernelWorx-Web",
                    auth_flows=cognito.AuthFlow(
                        user_srp=True,
                        user_password=True,
                    ),
                    o_auth=cognito.OAuthSettings(
                        flows=cognito.OAuthFlows(
                            authorization_code_grant=True,
                            implicit_code_grant=True,
                        ),
                        scopes=[
                            cognito.OAuthScope.EMAIL,
                            cognito.OAuthScope.OPENID,
                            cognito.OAuthScope.PROFILE,
                        ],
                        callback_urls=[
                            f"https://{self.site_domain}",
                            "http://localhost:5173",
                            "https://local.dev.appworx.app:5173",
                        ],
                        logout_urls=[
                            f"https://{self.site_domain}",
                            "http://localhost:5173",
                            "https://local.dev.appworx.app:5173",
                        ],
                    ),
                    supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
                    prevent_user_existence_errors=True,
                )
                # Enable ALLOW_USER_AUTH for WebAuthn/passkey support
                cfn_client = self.user_pool_client.node.default_child
                cfn_client.add_property_override(
                    "ExplicitAuthFlows",
                    [
                        "ALLOW_REFRESH_TOKEN_AUTH",
                        "ALLOW_USER_PASSWORD_AUTH",
                        "ALLOW_USER_SRP_AUTH",
                        "ALLOW_USER_AUTH",  # Required for WebAuthn/passkeys
                    ],
                )
        else:
            self.user_pool = cognito.UserPool(
                self,
                "UserPool",
                user_pool_name=rn("kernelworx-users"),
                sign_in_aliases=cognito.SignInAliases(email=True, username=False),
                self_sign_up_enabled=True,
                auto_verify=cognito.AutoVerifiedAttrs(email=True),
                standard_attributes=cognito.StandardAttributes(
                    email=cognito.StandardAttribute(required=True, mutable=True),
                    given_name=cognito.StandardAttribute(required=False, mutable=True),
                    family_name=cognito.StandardAttribute(required=False, mutable=True),
                ),
                password_policy=cognito.PasswordPolicy(
                    min_length=8,
                    require_lowercase=True,
                    require_uppercase=True,
                    require_digits=True,
                    require_symbols=True,
                ),
                account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
                # Enable MFA with TOTP (software tokens) and SMS as options
                mfa=cognito.Mfa.OPTIONAL,
                mfa_second_factor=cognito.MfaSecondFactor(
                    sms=True,  # Allow SMS MFA
                    otp=True,  # Allow TOTP (software tokens like Google Authenticator)
                ),
                # Enable choice-based authentication with password and passkeys
                sign_in_policy=cognito.SignInPolicy(
                    allowed_first_auth_factors=cognito.AllowedFirstAuthFactors(
                        password=True,
                        passkey=True,
                    )
                ),
                # Set WebAuthn Relying Party ID to app domain (not auth domain)
                passkey_relying_party_id=self.site_domain,  # e.g., dev.kernelworx.app
                # User verification preferred (default) - allows authenticators without UV capability
                passkey_user_verification=cognito.PasskeyUserVerification.PREFERRED,
                removal_policy=RemovalPolicy.RETAIN,
                # Lambda triggers
                lambda_triggers=cognito.UserPoolTriggers(
                    post_authentication=self.post_auth_fn,
                ),
                # Note: Advanced security mode not compatible with Essentials tier
                # UI customization (logo, CSS) is available without advanced_security_mode
            )

            # Configure user attribute update settings to require verification for email changes
            cfn_user_pool = self.user_pool.node.default_child
            cfn_user_pool.user_attribute_update_settings = (
                cognito.CfnUserPool.UserAttributeUpdateSettingsProperty(
                    attributes_require_verification_before_update=["email"]
                )
            )

            # Note: COPPA compliance warning (13+ age requirement) must be displayed
            # in application UI. Lambda trigger for age verification deferred to later phase.

            # Create ADMIN user group
            # Note: Only ADMIN group is needed. Everyone else is a regular user by default.
            # The Lambda checks for ADMIN group membership; all other users have isAdmin=False.
            cognito.CfnUserPoolGroup(
                self,
                "AdminGroup",
                user_pool_id=self.user_pool.user_pool_id,
                group_name="ADMIN",
                description="Administrator users with elevated privileges",
            )

            # Configure social identity providers (optional - only create if credentials provided)
            supported_providers = [cognito.UserPoolClientIdentityProvider.COGNITO]

            # Google OAuth (only if credentials provided)
            if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
                google_provider = cognito.UserPoolIdentityProviderGoogle(
                    self,
                    "GoogleProvider",
                    user_pool=self.user_pool,
                    client_id=os.environ["GOOGLE_CLIENT_ID"],
                    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                    scopes=["email", "profile", "openid"],
                    attribute_mapping=cognito.AttributeMapping(
                        email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                        given_name=cognito.ProviderAttribute.GOOGLE_GIVEN_NAME,
                        family_name=cognito.ProviderAttribute.GOOGLE_FAMILY_NAME,
                    ),
                )
                supported_providers.append(cognito.UserPoolClientIdentityProvider.GOOGLE)

            # Facebook OAuth (only if credentials provided)
            if os.environ.get("FACEBOOK_APP_ID") and os.environ.get("FACEBOOK_APP_SECRET"):
                facebook_provider = cognito.UserPoolIdentityProviderFacebook(
                    self,
                    "FacebookProvider",
                    user_pool=self.user_pool,
                    client_id=os.environ["FACEBOOK_APP_ID"],
                    client_secret=os.environ["FACEBOOK_APP_SECRET"],
                    scopes=["email", "public_profile"],
                    attribute_mapping=cognito.AttributeMapping(
                        email=cognito.ProviderAttribute.FACEBOOK_EMAIL,
                        given_name=cognito.ProviderAttribute.FACEBOOK_FIRST_NAME,
                        family_name=cognito.ProviderAttribute.FACEBOOK_LAST_NAME,
                    ),
                )
                supported_providers.append(cognito.UserPoolClientIdentityProvider.FACEBOOK)

            # Apple Sign In (only if credentials provided)
            if (
                os.environ.get("APPLE_SERVICES_ID")
                and os.environ.get("APPLE_TEAM_ID")
                and os.environ.get("APPLE_KEY_ID")
                and os.environ.get("APPLE_PRIVATE_KEY")
            ):
                apple_provider = cognito.UserPoolIdentityProviderApple(
                    self,
                    "AppleProvider",
                    user_pool=self.user_pool,
                    client_id=os.environ["APPLE_SERVICES_ID"],
                    team_id=os.environ["APPLE_TEAM_ID"],
                    key_id=os.environ["APPLE_KEY_ID"],
                    private_key=os.environ["APPLE_PRIVATE_KEY"],
                    scopes=["email", "name"],
                    attribute_mapping=cognito.AttributeMapping(
                        email=cognito.ProviderAttribute.APPLE_EMAIL,
                        given_name=cognito.ProviderAttribute.APPLE_FIRST_NAME,
                        family_name=cognito.ProviderAttribute.APPLE_LAST_NAME,
                    ),
                )
                supported_providers.append(cognito.UserPoolClientIdentityProvider.APPLE)

            # App client for SPA
            self.user_pool_client = self.user_pool.add_client(
                "AppClient",
                user_pool_client_name="KernelWorx-Web",
                auth_flows=cognito.AuthFlow(
                    user_srp=True,
                    user_password=True,
                    user=True,  # Required for WebAuthn/passkeys (ALLOW_USER_AUTH)
                ),
                o_auth=cognito.OAuthSettings(
                    flows=cognito.OAuthFlows(
                        authorization_code_grant=True,
                        implicit_code_grant=True,
                    ),
                    scopes=[
                        cognito.OAuthScope.EMAIL,
                        cognito.OAuthScope.OPENID,
                        cognito.OAuthScope.PROFILE,
                    ],
                    callback_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                        f"https://{self.site_domain}/callback",
                    ],
                    logout_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                    ],
                ),
                supported_identity_providers=supported_providers,
                prevent_user_existence_errors=True,
            )

            # Support two-stage deploys: some environments prefer creating the
            # site distribution and DNS first, then creating the Cognito
            # custom domain after DNS has propagated. Control this behaviour
            # with the context key `create_cognito_domain` (default: True).
            create_cognito_domain_ctx = self.node.try_get_context(
                "create_cognito_domain"
            )
            # Handle string values from CLI (e.g., -c create_cognito_domain=false)
            if create_cognito_domain_ctx is None:
                create_cognito_domain = True
            elif isinstance(create_cognito_domain_ctx, bool):
                create_cognito_domain = create_cognito_domain_ctx
            else:
                create_cognito_domain = str(create_cognito_domain_ctx).lower() != "false"

            # Custom domain configuration (login.{env}.kernelworx.app or login.kernelworx.app)
            if create_cognito_domain:
                self.user_pool_domain = self.user_pool.add_domain(
                    "UserPoolDomain",
                    custom_domain=cognito.CustomDomainOptions(
                        domain_name=self.cognito_domain,
                        certificate=self.cognito_certificate,
                    ),
                )

                # Ensure the certificate is fully validated before creating the domain
                self.user_pool_domain.node.add_dependency(self.cognito_certificate)

            # NOTE: ManagedLoginVersion property removed temporarily - can be added back
            # after initial deployment if needed for Managed Login v2 branding

        # ====================================================================
        # Cognito Custom Domain Configuration (for imported pools only)
        # ====================================================================

        if existing_user_pool_id:
            # For imported pools, import the existing custom domain
            # (new pools already created their domain in the else block above)
            self.user_pool_domain = cognito.UserPoolDomain.from_domain_name(
                self, "UserPoolDomain", self.cognito_domain
            )

        # Route53 record for Cognito custom domain
        # For imported pools, assume the record already exists
        # For new pools, create the record with RETAIN policy. Only create
        # the record in deploys where we're also creating the Cognito domain
        # (controlled by `create_cognito_domain` context flag).
        if not existing_user_pool_id and create_cognito_domain:
            # Create new Route53 record for new pools
            self.cognito_domain_record = route53.ARecord(
                self,
                "CognitoDomainRecord",
                zone=self.hosted_zone,
                record_name=self.cognito_domain,
                target=route53.RecordTarget.from_alias(
                    targets.UserPoolDomainTarget(self.user_pool_domain)
                ),
            )
            self.cognito_domain_record.apply_removal_policy(RemovalPolicy.RETAIN)

        # Output Cognito Hosted UI URL for easy access (only if user pool was created, not imported)
        if hasattr(self, "user_pool_domain") and hasattr(self, "user_pool_client"):
            CfnOutput(
                self,
                "CognitoHostedUIUrl",
                value=f"https://{self.user_pool_domain.domain_name}.auth.{self.region}.amazoncognito.com/login?client_id={self.user_pool_client.user_pool_client_id}&response_type=code&redirect_uri=http://localhost:5173",
                description="Cognito Hosted UI URL for testing",
            )

        # ====================================================================
        # AppSync GraphQL API
        # ====================================================================

        # Read GraphQL schema from file
        schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "schema.graphql")

        # Check if we should import existing API
        existing_api_id = self.node.try_get_context("appsync_api_id")
        if existing_api_id:
            self.api = appsync.GraphqlApi.from_graphql_api_attributes(
                self,
                "Api",
                graphql_api_id=existing_api_id,
            )
        else:
            # Determine if logging should be enabled (configurable via ENABLE_APPSYNC_LOGGING env var)
            # Defaults to True if not specified
            enable_appsync_logging = os.getenv("ENABLE_APPSYNC_LOGGING", "true").lower() == "true"

            self.api = appsync.GraphqlApi(
                self,
                "Api",
                name=rn("kernelworx-api"),
                definition=appsync.Definition.from_file(schema_path),
                authorization_config=appsync.AuthorizationConfig(
                    default_authorization=appsync.AuthorizationMode(
                        authorization_type=appsync.AuthorizationType.USER_POOL,
                        user_pool_config=appsync.UserPoolConfig(user_pool=self.user_pool),
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

            CfnOutput(
                self,
                "AppSyncApiKey",
                value="NOT_AVAILABLE",
                description="AppSync API Key for unauthenticated access to public catalogs",
            )

            # DynamoDB data source
            self.dynamodb_datasource = self.api.add_dynamo_db_data_source(
                "DynamoDBDataSource",
                table=self.table,
            )

            # Grant GSI permissions to the DynamoDB data source role
            self.dynamodb_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.table.table_arn}/index/*"],
                )
            )

            # ================================================================
            # Multi-table data sources (new architecture)
            # ================================================================

            # Accounts table data source
            self.accounts_datasource = self.api.add_dynamo_db_data_source(
                "AccountsDataSource",
                table=self.accounts_table,
            )
            self.accounts_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.accounts_table.table_arn}/index/*"],
                )
            )

            # Catalogs table data source
            self.catalogs_datasource = self.api.add_dynamo_db_data_source(
                "CatalogsDataSource",
                table=self.catalogs_table,
            )
            self.catalogs_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.catalogs_table.table_arn}/index/*"],
                )
            )

            # Profiles table data source
            self.profiles_datasource = self.api.add_dynamo_db_data_source(
                "ProfilesDataSource",
                table=self.profiles_table,
            )
            self.profiles_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.profiles_table.table_arn}/index/*"],
                )
            )

            # Seasons table data source
            self.seasons_datasource = self.api.add_dynamo_db_data_source(
                "SeasonsDataSource",
                table=self.seasons_table,
            )
            self.seasons_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.seasons_table.table_arn}/index/*"],
                )
            )

            # Orders table data source
            self.orders_datasource = self.api.add_dynamo_db_data_source(
                "OrdersDataSource",
                table=self.orders_table,
            )
            self.orders_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.orders_table.table_arn}/index/*"],
                )
            )

            # Shares table data source
            self.shares_datasource = self.api.add_dynamo_db_data_source(
                "SharesDataSource",
                table=self.shares_table,
            )
            self.shares_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.shares_table.table_arn}/index/*"],
                )
            )

            # Invites table data source
            self.invites_datasource = self.api.add_dynamo_db_data_source(
                "InvitesDataSource",
                table=self.invites_table,
            )
            self.invites_datasource.grant_principal.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{self.invites_table.table_arn}/index/*"],
                )
            )

            # NONE data source for computed fields
            self.none_datasource = self.api.add_none_data_source(
                "NoneDataSource",
                name="NoneDataSource",
            )

            # Lambda data sources for profile sharing
            # NOTE: create_profile_invite data source REMOVED - replaced with JS resolver
            # NOTE: redeem_profile_invite data source REMOVED - replaced with pipeline resolver
            # NOTE: share_profile_direct data source REMOVED - replaced with pipeline resolver
            # NOTE: revoke_share Lambda data source REMOVED - replaced with VTL resolver
            # NOTE: update_season, delete_season Lambda data sources REMOVED - replaced with pipeline resolvers

            # Lambda data sources for profile operations
            self.create_profile_ds = self.api.add_lambda_data_source(
                "CreateProfileDS",
                lambda_function=self.create_profile_fn,
            )

            # Lambda data sources for order operations
            # NOTE: create_order data source REMOVED - replaced with pipeline resolver
            # NOTE: list_orders_by_season Lambda data source REMOVED - replaced with VTL resolver
            # NOTE: update_order, delete_order Lambda data sources REMOVED - replaced with pipeline resolvers

            self.request_season_report_ds = self.api.add_lambda_data_source(
                "RequestSeasonReportDS",
                lambda_function=self.request_season_report_fn,
            )

            self.unit_reporting_ds = self.api.add_lambda_data_source(
                "UnitReportingDS",
                lambda_function=self.unit_reporting_fn,
            )

            # Lambda data sources for account operations
            self.update_my_account_ds = self.api.add_lambda_data_source(
                "UpdateMyAccountDS",
                lambda_function=self.update_my_account_fn,
            )

            # Resolvers for profile sharing mutations
            # createProfileInvite - Pipeline resolver with authorization (Bug #2 fix)
            verify_profile_owner_for_invite_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForInviteFn",
                name=f"VerifyProfileOwnerForInviteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile || profile.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can create invites', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
        """
                ),
            )

            # Create invite in invites table - NOW USES INVITES TABLE
            create_invite_fn = appsync.AppsyncFunction(
                self,
                "CreateInviteFn",
                name=f"CreateInviteFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const profileId = input.profileId;
    const permissions = input.permissions;
    const callerAccountId = ctx.identity.sub;
    
    // Get ownerAccountId from profile in stash (for BatchGetItem on profiles table)
    const ownerAccountId = ctx.stash.profile ? ctx.stash.profile.ownerAccountId : null;
    
    // Generate invite code (first 10 chars of UUID, uppercase)
    const inviteCode = util.autoId().substring(0, 10).toUpperCase();
    
    // Calculate expiry (default 14 days, or custom expiresInDays if provided)
    const daysUntilExpiry = input.expiresInDays || 14;
    const expirySeconds = daysUntilExpiry * 24 * 60 * 60;
    const expiresAtEpoch = util.time.nowEpochSeconds() + expirySeconds;
    const now = util.time.nowISO8601();
    const expiresAtISO = util.time.epochMilliSecondsToISO8601(expiresAtEpoch * 1000);
    
    // Invites table uses inviteCode as PK
    const key = {
        inviteCode: inviteCode
    };
    
    const attributes = {
        inviteCode: inviteCode,
        profileId: profileId,
        ownerAccountId: ownerAccountId,  // Store for BatchGetItem on profiles table
        permissions: permissions,
        createdBy: callerAccountId,
        createdAt: now,
        expiresAt: expiresAtEpoch,
        used: false
    };
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues(key),
        attributeValues: util.dynamodb.toMapValues(attributes),
        condition: {
            expression: 'attribute_not_exists(inviteCode)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Invite code collision, please retry', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Convert expiresAt epoch back to ISO string for API response
    const expiresAtISO = util.time.epochMilliSecondsToISO8601(ctx.result.expiresAt * 1000);
    
    return {
        inviteCode: ctx.result.inviteCode,
        profileId: ctx.result.profileId,
        permissions: ctx.result.permissions,
        expiresAt: expiresAtISO,
        createdByAccountId: ctx.result.createdBy,
        createdAt: ctx.result.createdAt
    };
}
        """
                ),
            )

            self.api.create_resolver(
                "CreateProfileInvitePipelineResolver",
                type_name="Mutation",
                field_name="createProfileInvite",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[verify_profile_owner_for_invite_fn, create_invite_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
        """
                ),
            )

            # NOTE: redeemProfileInvite Lambda resolver REMOVED - replaced with pipeline resolver
            # NOTE: shareProfileDirect Lambda resolver REMOVED - replaced with pipeline resolver

            # revokeShare - Pipeline resolver with authorization (Bug #5 fix)
            verify_profile_owner_for_revoke_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForRevokeFn",
                name=f"VerifyProfileOwnerForRevokeFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile || profile.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can revoke shares', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
        """
                ),
            )

            delete_share_fn = appsync.AppsyncFunction(
                self,
                "DeleteShareFn",
                name=f"DeleteShareFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    var targetAccountId = ctx.args.input.targetAccountId;
    
    // Strip ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(8);
    }
    // Also strip old SHARE#ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('SHARE#ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(14);
    }
    // Also strip old SHARE# prefix if present
    if (targetAccountId && targetAccountId.startsWith('SHARE#')) {
        targetAccountId = targetAccountId.substring(6);
    }
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: targetAccountId 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
        """
                ),
            )

            self.api.create_resolver(
                "RevokeSharePipelineResolver",
                type_name="Mutation",
                field_name="revokeShare",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[verify_profile_owner_for_revoke_fn, delete_share_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
        """
                ),
            )

            # deleteProfileInvite - Simple resolver (delete invite code)
            delete_profile_invite_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileInviteFn",
                name=f"DeleteProfileInviteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.profileId;
    
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    
    // Check if caller is the owner
    if (!profile || profile.ownerAccountId !== callerAccountId) {
        util.error('Forbidden: Only profile owner can delete invites', 'Unauthorized');
    }
    
    // Store profile info for next function
    ctx.stash.profileId = ctx.args.profileId;
    ctx.stash.inviteCode = ctx.args.inviteCode;
    ctx.stash.authorized = true;
    
    return true;
}
                """
                ),
            )

            # Second function to perform the actual deletion - NOW USES INVITES TABLE
            delete_invite_item_fn = appsync.AppsyncFunction(
                self,
                "DeleteInviteItemFn",
                name=f"DeleteInviteItemFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.stash.inviteCode;
    
    // Delete from invites table using inviteCode as PK
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            inviteCode: inviteCode
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
                """
                ),
            )

            self.api.create_resolver(
                "DeleteProfileInvitePipelineResolver",
                type_name="Mutation",
                field_name="deleteProfileInvite",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[delete_profile_invite_fn, delete_invite_item_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
        """
                ),
            )

            # ================================================================
            # SHARED AUTHORIZATION FUNCTION
            # ================================================================

            # VerifyProfileWriteAccessFn: Checks if caller is owner OR has WRITE permission
            # Used by: createOrder, updateOrder, deleteOrder, updateSeason, deleteSeason
            verify_profile_write_access_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileWriteAccessFn",
                name=f"VerifyProfileWriteAccessFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // For idempotent delete operations ONLY, if item explicitly set to null by lookup function, skip auth
    // This preserves idempotent delete behavior (item already gone = success)
    // Check the correct field based on which operation
    const isDeleteOperation = ctx.info.fieldName === 'deleteOrder' || ctx.info.fieldName === 'deleteSeason';
    const isDeletingOrder = ctx.info.fieldName === 'deleteOrder';
    const isDeletingSeason = ctx.info.fieldName === 'deleteSeason';
    
    const itemNotFound = (isDeletingOrder && ctx.stash.order === null) || 
                         (isDeletingSeason && ctx.stash.season === null);
    
    if (isDeleteOperation && itemNotFound) {
        ctx.stash.skipAuth = true;
        // Return no-op request (won't be used)
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // Extract profileId from various sources
    // For createOrder/updateOrder/deleteOrder: use order.profileId from stash or input
    // For updateSeason/deleteSeason: use season.profileId from stash  
    let profileId = null;
    
    if (ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.stash && ctx.stash.order) {
        // Orders have profileId attribute - use it directly (not PK which is the season key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.season && ctx.stash.season.profileId) {
        // Seasons have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.season.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found in request or stash - debugging: ' + JSON.stringify({
            hasInput: !!ctx.args.input,
            hasOrder: !!(ctx.stash && ctx.stash.order),
            hasSeason: !!(ctx.stash && ctx.stash.season),
            orderKeys: ctx.stash && ctx.stash.order ? Object.keys(ctx.stash.order) : []
        }), 'BadRequest');
    }
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    // If we skipped auth for idempotent delete, return success
    if (ctx.stash.skipAuth) {
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    
    // Store profile in stash for later use
    ctx.stash.profile = profile;
    ctx.stash.profileOwner = profile.ownerAccountId;
    
    // Check if caller is owner (ownerAccountId is now ACCOUNT#sub format)
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    const isMatch = (profileOwner === callerAccountId);
    
    if (isMatch) {
        ctx.stash.isOwner = true;
        return profile;
    }
    
    // Not owner - need to check share permissions in next function
    ctx.stash.isOwner = false;
    return profile;
}
                """
                ),
            )

            # CheckSharePermissionsFn: Checks if non-owner has WRITE permission via share
            # Used in conjunction with VerifyProfileWriteAccessFn above
            # NOW USES SHARES TABLE
            check_share_permissions_fn = appsync.AppsyncFunction(
                self,
                "CheckSharePermissionsFn",
                name=f"CheckSharePermissionsFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner or skipAuth), skip this check
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Non-owner: check for WRITE share
    // Extract profileId using same logic as VerifyProfileWriteAccessFn
    let profileId = null;
    
    if (ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.stash && ctx.stash.order) {
        // Orders have profileId attribute - use it directly (not PK which is the season key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.season && ctx.stash.season.profileId) {
        // Seasons have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.season.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found for share check', 'BadRequest');
    }
    
    // Look up share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: ctx.identity.sub 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized, return success
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        util.error('Forbidden: Only profile owner or users with WRITE permission can perform this action (no share found)', 'Unauthorized');
    }
    
    // Share exists but doesn't have permissions field - deny
    if (!share.permissions || !Array.isArray(share.permissions)) {
        util.error('Forbidden: Share exists but permissions are invalid', 'Unauthorized');
    }
    
    // Check if caller has WRITE permission via share
    if (share.permissions.includes('WRITE')) {
        ctx.stash.share = share;
        return { authorized: true };
    }
    
    // Share exists but only has READ permission - access denied
    util.error('Forbidden: Only profile owner or users with WRITE permission can perform this action (share has READ only, permissions: ' + JSON.stringify(share.permissions) + ')', 'Unauthorized');
}
                """
                ),
            )

            # VerifyProfileReadAccessFn: Checks if caller can READ profile data (owner OR has any share)
            # Used by: getSeason, listSeasonsByProfile, getOrder
            # Less restrictive than VerifyProfileWriteAccessFn - allows READ or WRITE shares
            verify_profile_read_access_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileReadAccessFn",
                name=f"VerifyProfileReadAccessFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If season not found, skip this function
    if (ctx.stash.seasonNotFound) {
        // Return a no-op read
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // If order not found, skip this function
    if (ctx.stash.orderNotFound) {
        // Return a no-op read
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // Extract profileId from args or stash
    let profileId = null;
    
    if (ctx.args.profileId) {
        profileId = ctx.args.profileId;
    } else if (ctx.stash && ctx.stash.season && ctx.stash.season.profileId) {
        profileId = ctx.stash.season.profileId;
    } else if (ctx.stash && ctx.stash.profileId) {
        // For orders, profileId is set directly in stash
        profileId = ctx.stash.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found in request', 'BadRequest');
    }
    
    // Store profileId in stash for next function
    ctx.stash.profileId = profileId;
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    // If season not found, pass through (will return null at end)
    if (ctx.stash.seasonNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // If order not found, pass through (will return null at end)
    if (ctx.stash.orderNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        // Profile doesn't exist - for getSeason, we'll return null later
        // For listSeasonsByProfile, we'll return empty array
        ctx.stash.profileNotFound = true;
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Check if caller is owner (ownerAccountId is now ACCOUNT#sub format)
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    
    if (profileOwner === callerAccountId) {
        ctx.stash.isOwner = true;
        ctx.stash.authorized = true;
        return { authorized: true };
    }
    
    // Not owner - need to check for share (READ or WRITE)
    ctx.stash.isOwner = false;
    return profile;
}
                """
                ),
            )

            # CheckShareReadPermissionsFn: Checks if non-owner has READ or WRITE permission
            # Used in conjunction with VerifyProfileReadAccessFn
            # NOW USES SHARES TABLE
            check_share_read_permissions_fn = appsync.AppsyncFunction(
                self,
                "CheckShareReadPermissionsFn",
                name=f"CheckShareReadPermissionsFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner), profile not found, season not found, or order not found, skip
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.seasonNotFound || ctx.stash.orderNotFound) {
        // Use a no-op read
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Look up share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: ctx.identity.sub 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized, profile not found, season not found, or order not found, pass through
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.seasonNotFound || ctx.stash.orderNotFound) {
        return { authorized: ctx.stash.authorized };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Share exists - check for READ or WRITE permission
    if (!share.permissions || !Array.isArray(share.permissions)) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Has READ or WRITE permission - authorized
    if (share.permissions.includes('READ') || share.permissions.includes('WRITE')) {
        ctx.stash.authorized = true;
        ctx.stash.share = share;
        return { authorized: true };
    }
    
    // Share exists but no valid permissions
    ctx.stash.authorized = false;
    return { authorized: false };
}
                """
                ),
            )

            # ================================================================
            # Pipeline Resolvers for Season and Order Operations
            # ================================================================
            # These replace Lambda functions with JS pipeline resolvers
            # Note: Simplified auth - relies on Cognito authentication only
            # Full share-based authorization would require additional pipeline functions

            # updateSeason Pipeline: Direct GetItem → UpdateItem
            # Now uses seasons_datasource with direct seasonId key
            lookup_season_fn = appsync.AppsyncFunction(
                self,
                "LookupSeasonFn",
                name=f"LookupSeasonFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId || ctx.args.input.seasonId;
    // Query seasonId-index GSI to find the season (V2: PK=profileId, SK=seasonId)
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('Season not found', 'NotFound');
    }
    // Store season in stash for next function
    ctx.stash.season = ctx.result.items[0];
    return ctx.result.items[0];
}
                """
                ),
            )

            update_season_fn = appsync.AppsyncFunction(
                self,
                "UpdateSeasonFn",
                name=f"UpdateSeasonFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const season = ctx.stash.season;
    const input = ctx.args.input || ctx.args;
    
    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};
    
    if (input.seasonName !== undefined) {
        updates.push('seasonName = :seasonName');
        exprValues[':seasonName'] = input.seasonName;
    }
    if (input.startDate !== undefined) {
        updates.push('startDate = :startDate');
        exprValues[':startDate'] = input.startDate;
    }
    if (input.endDate !== undefined) {
        updates.push('endDate = :endDate');
        exprValues[':endDate'] = input.endDate;
    }
    if (input.catalogId !== undefined) {
        updates.push('catalogId = :catalogId');
        exprValues[':catalogId'] = input.catalogId;
    }
    
    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();
    
    if (updates.length === 0) {
        return season; // No updates, return original
    }
    
    const updateExpression = 'SET ' + updates.join(', ');
    
    // V2: Use composite key (profileId, seasonId)
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: season.profileId, seasonId: season.seasonId }),
        update: {
            expression: updateExpression,
            expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined,
            expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const season = ctx.stash.season;
    const input = ctx.args.input || ctx.args;
    
    // Build response object with updated values
    const result = {
        seasonId: season.seasonId,
        profileId: season.profileId,
        seasonName: input.seasonName !== undefined ? input.seasonName : season.seasonName,
        startDate: input.startDate !== undefined ? input.startDate : season.startDate,
        endDate: input.endDate !== undefined ? input.endDate : season.endDate,
        catalogId: input.catalogId !== undefined ? input.catalogId : season.catalogId,
        createdAt: season.createdAt,
        updatedAt: util.time.nowISO8601()
    };
    
    return result;
}
                """
                ),
            )

            # Create updateSeason pipeline resolver (Bug #14 fix - added authorization)
            self.api.create_resolver(
                "UpdateSeasonPipelineResolverV2",
                type_name="Mutation",
                field_name="updateSeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_season_fn,
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    update_season_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # deleteSeason Pipeline: Direct GetItem → DeleteItem
            # Separate lookup for delete - doesn't error on missing season (idempotent)
            # V2: Query seasonId-index GSI since PK=profileId, SK=seasonId
            lookup_season_for_delete_fn = appsync.AppsyncFunction(
                self,
                "LookupSeasonForDeleteFn",
                name=f"LookupSeasonForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId;
    // Query seasonId-index GSI to find the season (V2: PK=profileId, SK=seasonId)
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // For delete, if season not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!ctx.result.items || ctx.result.items.length === 0) {
        ctx.stash.season = null;
        return null;
    }
    
    // Note: Authorization is simplified - relies on Cognito authentication
    // Full share-based authorization would require additional pipeline functions
    ctx.stash.season = ctx.result.items[0];
    return ctx.result.items[0];
}
                """
                ),
            )

            # Query orders for the season to delete (for cleanup)
            # V2 schema: Direct PK query since PK=seasonId
            query_season_orders_for_delete_fn = appsync.AppsyncFunction(
                self,
                "QuerySeasonOrdersForDeleteFn",
                name=f"QuerySeasonOrdersForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const season = ctx.stash.season;
    
    // If season doesn't exist, skip order query
    if (!season) {
        ctx.stash.ordersToDelete = [];
        ctx.stash.skipOrderQuery = true;
        return {
            operation: 'Query',
            query: {
                expression: 'seasonId = :seasonId',
                expressionValues: util.dynamodb.toMapValues({ ':seasonId': 'NOOP' })
            }
        };
    }
    
    const seasonId = season.seasonId;
    
    // V2 schema: Direct PK query since PK=seasonId
    return {
        operation: 'Query',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        }
    };
}

export function response(ctx) {
    // If we skipped the query, just return empty
    if (ctx.stash.skipOrderQuery) {
        return [];
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store orders to delete in stash (need seasonId and orderId for V2 schema)
    const orders = ctx.result.items || [];
    ctx.stash.ordersToDelete = orders;
    
    return orders;
}
                """
                ),
            )

            # Delete orders associated with the season
            # V2 schema: Uses composite key (seasonId, orderId)
            delete_season_orders_fn = appsync.AppsyncFunction(
                self,
                "DeleteSeasonOrdersFn",
                name=f"DeleteSeasonOrdersFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const ordersToDelete = ctx.stash.ordersToDelete || [];
    
    if (ordersToDelete.length === 0) {
        // No orders to delete - use early return to skip this step
        return runtime.earlyReturn(true);
    }
    
    // Delete first order only - simple approach for now
    const firstOrder = ordersToDelete[0];
    
    // V2 schema: composite key (seasonId, orderId)
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ seasonId: firstOrder.seasonId, orderId: firstOrder.orderId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
                """
                ),
            )

            # Delete season from seasons table
            delete_season_fn = appsync.AppsyncFunction(
                self,
                "DeleteSeasonFn",
                name=f"DeleteSeasonFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const season = ctx.stash.season;
    
    // If season doesn't exist (lookup failed), skip the delete operation
    // This makes deleteSeason idempotent - deleting a non-existent season returns true
    if (!season) {
        // Return a no-op - the response will return true anyway
        ctx.stash.skipDelete = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', seasonId: 'NOOP' })
        };
    }
    
    // V2: Use composite key (profileId, seasonId)
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ profileId: season.profileId, seasonId: season.seasonId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
                """
                ),
            )

            # Create deleteSeason pipeline resolver (uses lookup_season_for_delete_fn) (Bug #14 fix - added authorization)
            # Pipeline: lookup → verify access → check permissions → query orders → delete orders → delete season
            self.api.create_resolver(
                "DeleteSeasonPipelineResolverV2",
                type_name="Mutation",
                field_name="deleteSeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_season_for_delete_fn,
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    query_season_orders_for_delete_fn,
                    delete_season_orders_fn,
                    delete_season_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # updateOrder Pipeline: Query GSI → UpdateItem (V2 schema)
            # Uses orderId-index GSI since V2 schema has PK=seasonId, SK=orderId
            lookup_order_fn = appsync.AppsyncFunction(
                self,
                "LookupOrderFn",
                name=f"LookupOrderFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId || ctx.args.input.orderId;
    // Query orderId-index GSI (V2 schema: PK=seasonId, SK=orderId)
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
            expression: 'orderId = :orderId',
            expressionValues: util.dynamodb.toMapValues({ ':orderId': orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const items = ctx.result.items || [];
    if (items.length === 0) {
        util.error('Order not found', 'NotFound');
    }
    // Store order in stash for next function
    ctx.stash.order = items[0];
    return items[0];
}
                """
                ),
            )

            # Bug #16 fix: Get catalog for updateOrder when lineItems are being updated
            # First looks up the season via GSI, then fetches the catalog
            get_catalog_for_update_order_fn = appsync.AppsyncFunction(
                self,
                "GetCatalogForUpdateOrderFn",
                name=f"GetCatalogForUpdateOrderFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Only fetch catalog if lineItems are being updated
    if (!ctx.args.input.lineItems) {
        ctx.stash.skipCatalog = true;
        // Return no-op query (will return empty)
        return {
            operation: 'Query',
            index: 'seasonId-index',
            query: {
                expression: 'seasonId = :seasonId',
                expressionValues: util.dynamodb.toMapValues({ ':seasonId': 'NOOP' })
            },
            limit: 1
        };
    }
    
    // Get the season's catalogId from the order
    const order = ctx.stash.order;
    const seasonId = order.seasonId;
    
    // Query seasonId-index GSI to find season (V2 schema)
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.stash.skipCatalog) {
        return null;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        util.error('Season not found', 'NotFound');
    }
    
    const season = items[0];
    const catalogId = season.catalogId;
    
    if (!catalogId) {
        util.error('Season does not have a catalog assigned', 'BadRequest');
    }
    
    // Store catalogId in stash for next request
    ctx.stash.catalogId = catalogId;
    return season;
}
                """
                ),
            )

            fetch_catalog_for_update_fn = appsync.AppsyncFunction(
                self,
                "FetchCatalogForUpdateFn",
                name=f"FetchCatalogForUpdateFn_{env_name}",
                api=self.api,
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (ctx.stash.skipCatalog) {
        // Return no-op request
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ catalogId: 'NOOP' })
        };
    }
    
    const catalogId = ctx.stash.catalogId;
    // Direct GetItem on catalogs table using catalogId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.stash.skipCatalog) {
        return null;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result) {
        util.error('Catalog not found', 'NotFound');
    }
    
    // Store catalog in stash for UpdateOrderFn
    ctx.stash.catalog = ctx.result;
    return ctx.result;
}
                """
                ),
            )

            update_order_fn = appsync.AppsyncFunction(
                self,
                "UpdateOrderFn",
                name=f"UpdateOrderFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const order = ctx.stash.order;
    const input = ctx.args.input || ctx.args;
    const catalog = ctx.stash.catalog;  // May be null if lineItems not being updated
    
    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};
    
    if (input.customerName !== undefined) {
        updates.push('customerName = :customerName');
        exprValues[':customerName'] = input.customerName;
    }
    if (input.customerPhone !== undefined) {
        updates.push('customerPhone = :customerPhone');
        exprValues[':customerPhone'] = input.customerPhone;
    }
    if (input.customerAddress !== undefined) {
        updates.push('customerAddress = :customerAddress');
        exprValues[':customerAddress'] = input.customerAddress;
    }
    if (input.paymentMethod !== undefined) {
        updates.push('paymentMethod = :paymentMethod');
        exprValues[':paymentMethod'] = input.paymentMethod;
    }
    if (input.totalAmount !== undefined) {
        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = input.totalAmount;
    }
    
    // Bug #16 fix: Enrich lineItems with product details from catalog
    if (input.lineItems !== undefined) {
        if (!catalog) {
            util.error('Catalog not loaded for lineItems update', 'InternalError');
        }
        
        // Build products lookup map
        const productsMap = {};
        for (const product of catalog.products || []) {
            productsMap[product.productId] = product;
        }
        
        // Enrich line items with product details
        const enrichedLineItems = [];
        let totalAmount = 0.0;
        
        for (const lineItem of input.lineItems) {
            const productId = lineItem.productId;
            const quantity = lineItem.quantity;
            
            // Validate quantity
            if (quantity < 1) {
                util.error('Quantity must be at least 1 (got ' + quantity + ')', 'BadRequest');
            }
            
            if (!productsMap[productId]) {
                util.error('Product ' + productId + ' not found in catalog', 'BadRequest');
            }
            
            const product = productsMap[productId];
            const pricePerUnit = product.price;
            const subtotal = pricePerUnit * quantity;
            totalAmount += subtotal;
            
            enrichedLineItems.push({
                productId: productId,
                productName: product.productName,
                quantity: quantity,
                pricePerUnit: pricePerUnit,
                subtotal: subtotal
            });
        }
        
        updates.push('lineItems = :lineItems');
        exprValues[':lineItems'] = enrichedLineItems;
        
        // Also update totalAmount
        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = totalAmount;
    }
    
    if (input.notes !== undefined) {
        updates.push('notes = :notes');
        exprValues[':notes'] = input.notes;
    }
    if (input.orderDate !== undefined) {
        updates.push('orderDate = :orderDate');
        exprValues[':orderDate'] = input.orderDate;
    }
    
    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();
    
    if (updates.length === 0) {
        return order; // No updates, return original
    }
    
    const updateExpression = 'SET ' + updates.join(', ');
    
    // V2 schema: composite key (seasonId, orderId)
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ seasonId: order.seasonId, orderId: order.orderId }),
        update: {
            expression: updateExpression,
            expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined,
            expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                """
                ),
            )

            # Create updateOrder pipeline resolver (Bug #13 fix - added authorization, Bug #16 fix - added catalog lookup)
            self.api.create_resolver(
                "UpdateOrderPipelineResolverV2",
                type_name="Mutation",
                field_name="updateOrder",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_order_fn,
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    get_catalog_for_update_order_fn,
                    fetch_catalog_for_update_fn,
                    update_order_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # deleteOrder Pipeline: Query GSI → DeleteItem (V2 schema)
            # Separate lookup for delete - doesn't error on missing order (idempotent)
            # Uses orderId-index GSI since V2 schema has PK=seasonId, SK=orderId
            lookup_order_for_delete_fn = appsync.AppsyncFunction(
                self,
                "LookupOrderForDeleteFn",
                name=f"LookupOrderForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId;
    // Query orderId-index GSI (V2 schema: PK=seasonId, SK=orderId)
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
            expression: 'orderId = :orderId',
            expressionValues: util.dynamodb.toMapValues({ ':orderId': orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    // For delete, if order not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (items.length === 0) {
        ctx.stash.order = null;
        return null;
    }
    
    ctx.stash.order = items[0];
    return items[0];
}
                """
                ),
            )

            # Delete order from orders table (V2 schema: composite key)
            delete_order_fn = appsync.AppsyncFunction(
                self,
                "DeleteOrderFn",
                name=f"DeleteOrderFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const order = ctx.stash.order;
    
    // If order doesn't exist (lookup failed), skip the delete operation
    // This makes deleteOrder idempotent - deleting a non-existent order returns true
    if (!order) {
        // Return a no-op - just set a flag in stash
        ctx.stash.skipDelete = true;
        return {
            operation: 'Query',
            index: 'orderId-index',
            query: {
                expression: 'orderId = :orderId',
                expressionValues: util.dynamodb.toMapValues({ ':orderId': 'NOOP' })
            },
            limit: 1
        };
    }
    
    // V2 schema: composite key (seasonId, orderId)
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ seasonId: order.seasonId, orderId: order.orderId })
    };
}

export function response(ctx) {
    if (ctx.error && !ctx.stash.skipDelete) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Always return true (idempotent)
    return true;
}
                """
                ),
            )

            # Create deleteOrder pipeline resolver (uses idempotent lookup) (Bug #13 fix - added authorization)
            self.api.create_resolver(
                "DeleteOrderPipelineResolverV2",
                type_name="Mutation",
                field_name="deleteOrder",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_order_for_delete_fn,
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    delete_order_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # ================================================================
            # PHASE 3 PIPELINE RESOLVERS - Complex business logic
            # ================================================================

            # createOrder Pipeline: Verify access → Query season → GetItem catalog → PutItem order
            # Step 1: Get season to find catalogId
            # Uses seasonId-index GSI to look up season (V2 schema: PK=profileId, SK=seasonId)
            get_season_for_order_fn = appsync.AppsyncFunction(
                self,
                "GetSeasonForOrderFn",
                name=f"GetSeasonForOrderFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.input.seasonId;
    
    // Query seasonId-index GSI to find season (V2 schema)
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        util.error('Season not found', 'NotFound');
    }
    
    const season = items[0];
    if (!season.catalogId) {
        util.error('Season has no catalog assigned', 'BadRequest');
    }
    
    // Store season and catalogId in stash for next function
    ctx.stash.season = season;
    ctx.stash.catalogId = season.catalogId;
    
    return season;
}
                """
                ),
            )

            # Step 2: Get catalog using catalogId from stash
            # Now uses catalogs_datasource with direct catalogId key
            get_catalog_fn = appsync.AppsyncFunction(
                self,
                "GetCatalogFn",
                name=f"GetCatalogFn_{env_name}",
                api=self.api,
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.stash.catalogId;
    // Direct GetItem on catalogs table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found', 'NotFound');
    }
    
    // Store catalog in stash for CreateOrderFn
    ctx.stash.catalog = ctx.result;
    
    return ctx.result;
}
                """
                ),
            )

            # Step 3: Create the order in orders table
            create_order_fn = appsync.AppsyncFunction(
                self,
                "CreateOrderFn",
                name=f"CreateOrderFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const season = ctx.stash.season;
    const catalog = ctx.stash.catalog;
    
    if (!catalog) {
        util.error('Catalog not found', 'NotFound');
    }
    
    // Bug #15 fix: Validate line items
    if (!input.lineItems || input.lineItems.length === 0) {
        util.error('Order must have at least one line item', 'BadRequest');
    }
    
    // Build products lookup map
    const productsMap = {};
    for (const product of catalog.products || []) {
        productsMap[product.productId] = product;
    }
    
    // Enrich line items with product details
    const enrichedLineItems = [];
    let totalAmount = 0.0;
    
    for (const lineItem of input.lineItems) {
        const productId = lineItem.productId;
        const quantity = lineItem.quantity;
        
        // Bug #15 fix: Validate quantity
        if (quantity < 1) {
            util.error('Quantity must be at least 1 (got ' + quantity + ')', 'BadRequest');
        }
        
        if (!productsMap[productId]) {
            util.error('Product ' + productId + ' not found in catalog', 'BadRequest');
        }
        
        const product = productsMap[productId];
        const pricePerUnit = product.price;
        const subtotal = pricePerUnit * quantity;
        totalAmount += subtotal;
        
        enrichedLineItems.push({
            productId: productId,
            productName: product.productName,
            quantity: quantity,
            pricePerUnit: pricePerUnit,
            subtotal: subtotal
        });
    }
    
    // Generate order ID (without prefix since orderId is now the primary key)
    const orderId = util.autoId();
    const now = util.time.nowISO8601();
    
    // Build order item for orders table
    const orderItem = {
        orderId: orderId,
        profileId: input.profileId,
        seasonId: input.seasonId,
        customerName: input.customerName,
        orderDate: input.orderDate,
        paymentMethod: input.paymentMethod,
        lineItems: enrichedLineItems,
        totalAmount: totalAmount,
        createdAt: now,
        updatedAt: now
    };
    
    // Add optional fields
    if (input.customerPhone) {
        orderItem.customerPhone = input.customerPhone;
    }
    if (input.customerAddress) {
        orderItem.customerAddress = input.customerAddress;
    }
    if (input.notes) {
        orderItem.notes = input.notes;
    }
    
    // V2 schema: composite key (seasonId, orderId)
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ seasonId: input.seasonId, orderId: orderId }),
        attributeValues: util.dynamodb.toMapValues(orderItem)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                """
                ),
            )

            # Create createOrder pipeline resolver (Bug #13 fix - added authorization)
            self.api.create_resolver(
                "CreateOrderPipelineResolver",
                type_name="Mutation",
                field_name="createOrder",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    get_season_for_order_fn,
                    get_catalog_fn,
                    create_order_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # shareProfileDirect Pipeline: Verify owner → Query email-index for account by email → Create Share
            verify_profile_owner_for_share_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForShareFn",
                name=f"VerifyProfileOwnerForShareFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Check ownership - ownerAccountId uses ACCOUNT# prefix now
    const profile = ctx.result.items && ctx.result.items[0];
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (!profile || profile.ownerAccountId !== expectedOwner) {
        util.error('Forbidden: Only profile owner can share profiles', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
        """
                ),
            )

            # Look up account by email using accounts table email-index
            lookup_account_by_email_fn = appsync.AppsyncFunction(
                self,
                "LookupAccountByEmailFn",
                name=f"LookupAccountByEmailFn_{env_name}",
                api=self.api,
                data_source=self.accounts_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const email = ctx.args.input.targetAccountEmail;
    return {
        operation: 'Query',
        index: 'email-index',
        query: {
            expression: 'email = :email',
            expressionValues: util.dynamodb.toMapValues({ ':email': email })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('No account found with email ' + ctx.args.input.targetAccountEmail, 'NotFound');
    }
    
    const account = ctx.result.items[0];
    // accountId is now the primary key directly
    ctx.stash.targetAccountId = account.accountId;
    
    return account;
}
                """
                ),
            )

            # Check if share already exists (to prevent duplicates and support idempotent upsert)
            # NOW USES SHARES TABLE
            check_existing_share_fn = appsync.AppsyncFunction(
                self,
                "CheckExistingShareFn",
                name=f"CheckExistingShareFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId || ctx.stash.invite?.profileId;
    var targetAccountId = ctx.stash.targetAccountId;
    
    // Strip ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(8);
    }
    
    // Store clean ID for later use by CreateShareFn
    ctx.stash.cleanTargetAccountId = targetAccountId;
    
    // Query shares table directly by PK+SK
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store existing share info (if any) for CreateShareFn to reference
    if (ctx.result && ctx.result.profileId) {
        ctx.stash.existingShare = ctx.result;
    }
    
    return ctx.result;
}
                """
                ),
            )

            # Create share in shares table
            # NOW USES SHARES TABLE
            create_share_fn = appsync.AppsyncFunction(
                self,
                "CreateShareFn",
                name=f"CreateShareFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    var targetAccountId = ctx.stash.targetAccountId;
    const profileId = input.profileId || ctx.stash.invite.profileId;
    const permissions = input.permissions || ctx.stash.invite.permissions;
    const now = util.time.nowISO8601();
    
    // Get ownerAccountId from stash - check profile (shareProfileDirect) or invite (redeemProfileInvite)
    var ownerAccountId = null;
    if (ctx.stash.profile && ctx.stash.profile.ownerAccountId) {
        ownerAccountId = ctx.stash.profile.ownerAccountId;
    } else if (ctx.stash.invite && ctx.stash.invite.ownerAccountId) {
        ownerAccountId = ctx.stash.invite.ownerAccountId;
    }
    
    // Validate that ownerAccountId was found
    if (!ownerAccountId) {
        util.error('Failed to determine profile owner', 'InternalServerError');
    }
    
    // Strip ACCOUNT# prefix if present - store clean ID
    if (targetAccountId && targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(8);
    }
    
    // Generate shareId for backward compatibility with tests
    // Format: SHARE#ACCOUNT#{targetAccountId} to match old expectations
    const shareId = 'SHARE#ACCOUNT#' + targetAccountId;
    
    const shareItem = {
        profileId: profileId,
        targetAccountId: targetAccountId,
        shareId: shareId,
        permissions: permissions,
        ownerAccountId: ownerAccountId,  // Store for BatchGetItem lookup
        createdByAccountId: ctx.identity.sub,
        createdAt: now
    };
    
    // Store full share item in stash for response
    ctx.stash.shareItem = shareItem;
    
    // Use PutItem without condition to support both create and update (upsert)
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, targetAccountId: targetAccountId }),
        attributeValues: util.dynamodb.toMapValues(shareItem)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Return the full share item from stash since PutItem doesn't return attributes by default
    return ctx.stash.shareItem;
}
                """
                ),
            )

            # Create shareProfileDirect pipeline resolver (Bug #4 fix - added authorization)
            self.api.create_resolver(
                "ShareProfileDirectPipelineResolver",
                type_name="Mutation",
                field_name="shareProfileDirect",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_owner_for_share_fn,
                    lookup_account_by_email_fn,
                    check_existing_share_fn,
                    create_share_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # ================================================================
            # redeemProfileInvite Pipeline: Lookup invite → Create Share → Mark invite used
            # ================================================================
            # NOW USES INVITES TABLE (direct GetItem by inviteCode)
            lookup_invite_fn = appsync.AppsyncFunction(
                self,
                "LookupInviteFn",
                name=f"LookupInviteFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.args.input.inviteCode;
    // Direct GetItem on invites table using inviteCode as PK
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ inviteCode: inviteCode }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || !ctx.result.inviteCode) {
        util.error('Invalid invite code', 'NotFound');
    }
    
    const invite = ctx.result;
    
    // Check if invite is already used
    if (invite.used) {
        util.error('Invite code has already been used', 'ConflictException');
    }
    
    // Check if invite is expired (expiresAt is epoch seconds)
    const now = util.time.nowEpochSeconds();
    if (invite.expiresAt && invite.expiresAt < now) {
        util.error('Invite code has expired', 'ConflictException');
    }
    
    ctx.stash.invite = invite;
    ctx.stash.targetAccountId = ctx.identity.sub;
    
    return invite;
}
        """
                ),
            )

            # Mark invite as used in invites table
            mark_invite_used_fn = appsync.AppsyncFunction(
                self,
                "MarkInviteUsedFn",
                name=f"MarkInviteUsedFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invite = ctx.stash.invite;
    const now = util.time.nowISO8601();
    
    // Update invite in invites table using inviteCode as key
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ inviteCode: invite.inviteCode }),
        update: {
            expression: 'SET used = :used, usedBy = :usedBy, usedAt = :usedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':used': true,
                ':usedBy': ctx.identity.sub,
                ':usedAt': now,
                ':false': false
            })
        },
        condition: { expression: 'attribute_exists(inviteCode) AND used = :false' }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Invite has already been used', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result;
}
        """
                ),
            )

            # Create redeemProfileInvite pipeline resolver (reuses create_share_fn)
            self.api.create_resolver(
                "RedeemProfileInvitePipelineResolver",
                type_name="Mutation",
                field_name="redeemProfileInvite",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_invite_fn,
                    check_existing_share_fn,
                    create_share_fn,
                    mark_invite_used_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    // Pass through - stash will be populated by lookup_invite_fn
    return {};
}

export function response(ctx) {
    // Return the share that was created
    return ctx.prev.result;
}
        """
                ),
            )

            # DynamoDB resolvers for queries
            # getMyAccount - Get current user's account (uses accounts table)
            self.accounts_datasource.create_resolver(
                "GetMyAccountResolver",
                type_name="Query",
                field_name="getMyAccount",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
#set($accountId = "ACCOUNT#$ctx.identity.sub")
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "accountId": $util.dynamodb.toDynamoDBJson($accountId)
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.isEmpty())
    $util.error("Account not found", "NotFound")
#end
$util.toJson($ctx.result)
                """
                ),
            )

            # getProfile - Get a specific profile by ID with authorization
            # Pipeline: FetchProfileFn -> CheckProfileReadAuthFn

            # FetchProfileFn: Get the profile from profiles table directly
            fetch_profile_fn = appsync.AppsyncFunction(
                self,
                "FetchProfileFn",
                name=f"FetchProfileFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    if (!profileId) {
        util.error('Profile ID is required', 'BadRequest');
    }
    
    // Store profileId for authorization check
    ctx.stash.profileId = profileId;
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Query returns items array
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    
    // Store profile in stash for authorization and return
    ctx.stash.profile = profile;
    return profile;
}
                    """
                ),
            )

            # CheckProfileReadAuthFn: Check if caller is owner or has share
            # NOW USES SHARES TABLE
            check_profile_read_auth_fn = appsync.AppsyncFunction(
                self,
                "CheckProfileReadAuthFn",
                name=f"CheckProfileReadAuthFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = ctx.stash.profile;
    
    // Check if caller is owner first (ownerAccountId uses ACCOUNT# prefix)
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (profile.ownerAccountId === expectedOwner) {
        ctx.stash.authorized = true;
        // No DB operation needed, return no-op
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Not owner - check for share
    ctx.stash.authorized = false;
    const profileId = ctx.stash.profileId;
    
    // Check for share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: ctx.identity.sub 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized (owner), return the profile
    if (ctx.stash.authorized) {
        return ctx.stash.profile;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        util.error('Not authorized to access this profile', 'Unauthorized');
    }
    
    // Share exists - check for READ or WRITE permission
    if (!share.permissions || !Array.isArray(share.permissions)) {
        util.error('Not authorized to access this profile', 'Unauthorized');
    }
    
    // Has READ or WRITE permission - authorized
    if (share.permissions.includes('READ') || share.permissions.includes('WRITE')) {
        return ctx.stash.profile;
    }
    
    // Share exists but no valid permissions
    util.error('Not authorized to access this profile', 'Unauthorized');
}
                    """
                ),
            )

            # getProfile Pipeline Resolver
            appsync.Resolver(
                self,
                "GetProfileResolver",
                api=self.api,
                type_name="Query",
                field_name="getProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result;
}
                    """
                ),
                pipeline_config=[fetch_profile_fn, check_profile_read_auth_fn],
            )

            # listMyProfiles - List profiles owned by current user
            # NEW STRUCTURE: Query by PK (ownerAccountId) - no GSI needed
            self.api.create_resolver(
                "ListMyProfilesResolver",
                type_name="Query",
                field_name="listMyProfiles",
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query by PK (ownerAccountId)
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'Query',
        query: {
            expression: 'ownerAccountId = :ownerAccountId',
            expressionValues: util.dynamodb.toMapValues({ ':ownerAccountId': ownerAccountId })
        },
        limit: 500
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result.items || [];
}
                """
                ),
            )
            
            # listMyShares - Pipeline resolver to get full profile data for shares
            # Step 1: Query shares table GSI to get shares with ownerAccountId
            # Step 2: BatchGetItem on profiles table to get full profiles, merge permissions
            
            # Step 1: Query shares for current user
            list_my_shares_query_fn = appsync.AppsyncFunction(
                self,
                "ListMySharesQueryFn",
                name=f"ListMySharesQueryFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Query shares table GSI with caller's accountId
    const accountId = ctx.identity.sub;
    return {
        operation: 'Query',
        index: 'targetAccountId-index',
        query: {
            expression: 'targetAccountId = :targetAccountId',
            expressionValues: util.dynamodb.toMapValues({ ':targetAccountId': accountId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const shares = ctx.result.items || [];
    
    // Deduplicate by profileId and store shares in stash for later merging
    const sharesByProfileId = {};
    for (const share of shares) {
        if (share.profileId && share.ownerAccountId && !sharesByProfileId[share.profileId]) {
            sharesByProfileId[share.profileId] = {
                profileId: share.profileId,
                ownerAccountId: share.ownerAccountId,
                permissions: share.permissions || []
            };
        }
    }
    
    ctx.stash.sharesByProfileId = sharesByProfileId;
    ctx.stash.profileKeys = Object.values(sharesByProfileId).map(s => ({
        ownerAccountId: s.ownerAccountId,
        profileId: s.profileId
    }));
    
    return Object.values(sharesByProfileId);
}
                    """
                ),
            )
            
            # Step 2: BatchGetItem on profiles table
            list_my_shares_batch_get_fn = appsync.AppsyncFunction(
                self,
                "ListMySharesBatchGetFn",
                name=f"ListMySharesBatchGetFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const keys = ctx.stash.profileKeys || [];
    
    // If no shares, skip the request entirely - use runtime.earlyReturn
    if (keys.length === 0) {
        return runtime.earlyReturn([]);
    }
    
    // BatchGetItem supports up to 100 keys
    // For now, take first 100 (pagination can be added later if needed)
    const batchKeys = keys.slice(0, 100).map(k => util.dynamodb.toMapValues({
        ownerAccountId: k.ownerAccountId,
        profileId: k.profileId
    }));
    
    return {
        operation: 'BatchGetItem',
        tables: {
            '${PROFILES_TABLE}': {
                keys: batchKeys,
                consistentRead: false
            }
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const sharesByProfileId = ctx.stash.sharesByProfileId || {};
    // Add ACCOUNT# prefix to match ownerAccountId format in profiles table
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    
    // Handle empty shares case
    if (Object.keys(sharesByProfileId).length === 0) {
        return [];
    }
    
    // Get profiles from BatchGetItem response
    const profiles = ctx.result.data && ctx.result.data['${PROFILES_TABLE}'] || [];
    
    // Helper to strip ACCOUNT# prefix for API response format
    // Note: profileId keeps PROFILE# prefix, only ownerAccountId is stripped
    function stripAccountPrefix(s) {
        if (!s) return s;
        if (s.startsWith('ACCOUNT#')) return s.substring(8);
        return s;
    }
    
    // Merge profile data with permissions
    const result = [];
    for (const profile of profiles) {
        const share = sharesByProfileId[profile.profileId];
        if (share) {
            result.push({
                profileId: profile.profileId,  // Keep PROFILE# prefix
                ownerAccountId: stripAccountPrefix(profile.ownerAccountId),  // Strip ACCOUNT# prefix
                sellerName: profile.sellerName,
                unitType: profile.unitType || null,
                unitNumber: profile.unitNumber || null,
                createdAt: profile.createdAt,
                updatedAt: profile.updatedAt,
                isOwner: profile.ownerAccountId === callerAccountId,
                permissions: share.permissions
            });
        }
    }
    
    return result;
}
                    """.replace(
                        "${PROFILES_TABLE}", self.profiles_table.table_name
                    )
                ),
            )
            
            # Create listMyShares pipeline resolver
            self.api.create_resolver(
                "ListMySharesPipelineResolver",
                type_name="Query",
                field_name="listMyShares",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[list_my_shares_query_fn, list_my_shares_batch_get_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                    """
                ),
            )

            # getSeason - Get a specific season by ID with authorization
            # Pipeline: QuerySeasonFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → ReturnSeasonFn

            # Step 1: Get season from seasons table using seasonId-index GSI
            # V2 STRUCTURE: PK=profileId, SK=seasonId, GSI=seasonId-index
            query_season_fn = appsync.AppsyncFunction(
                self,
                "QuerySeasonFn",
                name=f"QuerySeasonFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId;
    // V2: Query seasonId-index GSI since PK is now profileId
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result || !ctx.result.items || ctx.result.items.length === 0) {
        // Season not found - return null (auth check will be skipped)
        ctx.stash.seasonNotFound = true;
        return null;
    }
    
    const season = ctx.result.items[0];
    ctx.stash.season = season;
    
    return season;
}
                """
                ),
            )

            # Step 4: Return season if authorized, null otherwise
            return_season_fn = appsync.AppsyncFunction(
                self,
                "ReturnSeasonFn",
                name=f"ReturnSeasonFn_{env_name}",
                api=self.api,
                data_source=self.none_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // No-op request (using None data source)
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If season not found, return null
    if (ctx.stash.seasonNotFound) {
        return null;
    }
    
    // If not authorized, return null (query permissions model - don't error)
    if (!ctx.stash.authorized) {
        return null;
    }
    
    // Authorized - return the season
    return ctx.stash.season;
}
                """
                ),
            )

            # getSeason Pipeline Resolver
            self.api.create_resolver(
                "GetSeasonResolver",
                type_name="Query",
                field_name="getSeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    query_season_fn,
                    verify_profile_read_access_fn,
                    check_share_read_permissions_fn,
                    return_season_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # listSeasonsByProfile - List all seasons for a profile with authorization
            # Pipeline: VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → QuerySeasonsFn

            # Step 3: Query seasons from seasons table (only if authorized)
            # V2 STRUCTURE: PK=profileId, SK=seasonId - direct query, no GSI needed
            query_seasons_fn = appsync.AppsyncFunction(
                self,
                "QuerySeasonsFn",
                name=f"QuerySeasonsFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized or profile not found, return no-op
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return {
            operation: 'Query',
            query: {
                expression: 'profileId = :profileId AND seasonId = :seasonId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP', ':seasonId': 'NOOP' })
            },
            limit: 1
        };
    }
    
    const profileId = ctx.args.profileId;
    // V2: Direct PK query on profileId (no GSI needed)
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If not authorized or profile not found, return empty array
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return [];
    }
    
    return ctx.result.items || [];
}
                """
                ),
            )

            # listSeasonsByProfile Pipeline Resolver
            self.api.create_resolver(
                "ListSeasonsByProfileResolver",
                type_name="Query",
                field_name="listSeasonsByProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_read_access_fn,
                    check_share_read_permissions_fn,
                    query_seasons_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # Season.catalog - Resolve catalog field for Season
            # Uses catalogs table directly
            self.catalogs_datasource.create_resolver(
                "SeasonCatalogResolver",
                type_name="Season",
                field_name="catalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.source.catalogId)
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """
                ),
            )

            # Season.totalOrders - Count orders for this season
            # V2 schema: Direct PK query since PK=seasonId
            self.orders_datasource.create_resolver(
                "SeasonTotalOrdersResolver",
                type_name="Season",
                field_name="totalOrders",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "seasonId = :seasonId",
        "expressionValues": {
            ":seasonId": $util.dynamodb.toDynamoDBJson($ctx.source.seasonId)
        }
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$ctx.result.items.size()
                """
                ),
            )

            # Season.totalRevenue - Sum order totals for this season
            # V2 schema: Direct PK query since PK=seasonId
            self.orders_datasource.create_resolver(
                "SeasonTotalRevenueResolver",
                type_name="Season",
                field_name="totalRevenue",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "seasonId = :seasonId",
        "expressionValues": {
            ":seasonId": $util.dynamodb.toDynamoDBJson($ctx.source.seasonId)
        }
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#set($total = 0.0)
#foreach($order in $ctx.result.items)
    #set($total = $total + $order.totalAmount)
#end
$total
                """
                ),
            )

            # SellerProfile.ownerAccountId - Strip ACCOUNT# prefix from stored value
            # Returns clean account ID for API consumers
            self.none_datasource.create_resolver(
                "SellerProfileOwnerAccountIdResolver",
                type_name="SellerProfile",
                field_name="ownerAccountId",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    const ownerAccountId = ctx.source.ownerAccountId;
    if (!ownerAccountId) return null;
    // Strip ACCOUNT# prefix if present
    if (ownerAccountId.startsWith('ACCOUNT#')) {
        return ownerAccountId.substring(8);
    }
    return ownerAccountId;
}
                """
                ),
            )

            # SellerProfile.isOwner - Compute if caller is the owner
            # Now accounts for ACCOUNT# prefix in ownerAccountId
            self.none_datasource.create_resolver(
                "SellerProfileIsOwnerResolver",
                type_name="SellerProfile",
                field_name="isOwner",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    const callerAccountId = ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    // Handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = 'ACCOUNT#' + callerAccountId;
    return expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId;
}
                """
                ),
            )

            # SellerProfile.permissions - Return caller's permissions on this profile
            # If owner: ['READ', 'WRITE'], if shared: share.permissions, else: null
            # NOW USES SHARES TABLE
            self.shares_datasource.create_resolver(
                "SellerProfilePermissionsResolver",
                type_name="SellerProfile",
                field_name="permissions",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const callerAccountId = ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    const profileId = ctx.source.profileId;
    
    // Check ownership - handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = 'ACCOUNT#' + callerAccountId;
    if (expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId) {
        ctx.stash.isOwner = true;
        // Return a no-op query
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Query shares table for share record: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: callerAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, return full permissions
    if (ctx.stash.isOwner) {
        return ['READ', 'WRITE'];
    }
    
    if (ctx.error) {
        // Don't error out - just return null for permissions
        return null;
    }
    
    const share = ctx.result;
    
    // No share found - return null
    if (!share || !share.profileId) {
        return null;
    }
    
    // Return the permissions from the share
    if (share.permissions && Array.isArray(share.permissions)) {
        return share.permissions;
    }
    
    // Share exists but no valid permissions - return null
    return null;
}
                """
                ),
            )

            # getOrder - Get a specific order by ID with authorization (Pipeline Resolver)
            # Pipeline: QueryOrderFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → ReturnOrderFn

            # Step 1: Get order from orders table via orderId-index GSI (V2 schema)
            query_order_fn = appsync.AppsyncFunction(
                self,
                "QueryOrderFn",
                name=f"QueryOrderFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId;
    // Query orderId-index GSI (V2 schema: PK=seasonId, SK=orderId)
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
            expression: 'orderId = :orderId',
            expressionValues: util.dynamodb.toMapValues({ ':orderId': orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        // Order not found - return null (auth check will be skipped)
        ctx.stash.orderNotFound = true;
        return null;
    }
    
    const order = items[0];
    ctx.stash.order = order;
    
    // profileId is stored directly on the order
    ctx.stash.profileId = order.profileId;
    
    return order;
}
                """
                ),
            )

            # Step 4: Return order if authorized, null otherwise
            return_order_fn = appsync.AppsyncFunction(
                self,
                "ReturnOrderFn",
                name=f"ReturnOrderFn_{env_name}",
                api=self.api,
                data_source=self.none_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // No-op request (using None data source)
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If order not found, return null
    if (ctx.stash.orderNotFound) {
        return null;
    }
    
    // If not authorized, return null (query permissions model - don't error)
    if (!ctx.stash.authorized) {
        return null;
    }
    
    // Return the order
    return ctx.stash.order;
}
                """
                ),
            )

            # getOrder Pipeline Resolver
            self.api.create_resolver(
                "GetOrderResolver",
                type_name="Query",
                field_name="getOrder",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    query_order_fn,
                    verify_profile_read_access_fn,
                    check_share_read_permissions_fn,
                    return_order_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # listOrdersBySeason - List all orders for a season with authorization (Pipeline Resolver)
            # NOTE: Replaced Lambda with direct DynamoDB query for better performance
            # FIXED Bug #25: Now uses GSI5 with filter for ORDER# items
            # FIXED Bug #23: Added authorization check
            # Pipeline: LookupSeasonForOrdersFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → QueryOrdersBySeasonFn

            # Step 1: Lookup season to get profileId (uses seasonId-index GSI, V2 schema)
            lookup_season_for_orders_fn = appsync.AppsyncFunction(
                self,
                "LookupSeasonForOrdersFn",
                name=f"LookupSeasonForOrdersFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId;
    // Query seasonId-index GSI to find season (V2 schema: PK=profileId, SK=seasonId)
    return {
        operation: 'Query',
        index: 'seasonId-index',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ ':seasonId': seasonId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        // Season not found - return empty, skip auth (will return empty array)
        ctx.stash.seasonNotFound = true;
        ctx.stash.authorized = false;
        return null;
    }
    
    const season = items[0];
    ctx.stash.season = season;
    ctx.stash.profileId = season.profileId;
    
    return season;
}
                """
                ),
            )

            # Step 4: Query orders (only if authorized) - direct PK query (V2 schema)
            query_orders_by_season_fn = appsync.AppsyncFunction(
                self,
                "QueryOrdersBySeasonFn",
                name=f"QueryOrdersBySeasonFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If season not found or not authorized, return empty query (will return empty array)
    if (ctx.stash.seasonNotFound || !ctx.stash.authorized) {
        return {
            operation: 'Query',
            query: {
                expression: 'seasonId = :seasonId',
                expressionValues: util.dynamodb.toMapValues({ 
                    ':seasonId': 'NONEXISTENT'
                })
            }
        };
    }
    
    const seasonId = ctx.args.seasonId;
    // Direct PK query on orders table (V2 schema: PK=seasonId)
    return {
        operation: 'Query',
        query: {
            expression: 'seasonId = :seasonId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':seasonId': seasonId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    return ctx.result.items || [];
}
                """
                ),
            )

            # listOrdersBySeason Pipeline Resolver
            self.api.create_resolver(
                "ListOrdersBySeasonResolver",
                type_name="Query",
                field_name="listOrdersBySeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    lookup_season_for_orders_fn,
                    verify_profile_read_access_fn,
                    check_share_read_permissions_fn,
                    query_orders_by_season_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # listOrdersByProfile - List all orders for a profile with authorization (Pipeline Resolver)
            # FIXED Bug #26: Now queries main table (PK=profileId) instead of GSI2
            # FIXED Bug #24: Added authorization check
            # Pipeline: VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → QueryOrdersByProfileFn

            # Query orders function - uses orders table with profileId-index GSI
            query_orders_by_profile_fn = appsync.AppsyncFunction(
                self,
                "QueryOrdersByProfileFn",
                name=f"QueryOrdersByProfileFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized, return empty query (will return empty array)
    if (!ctx.stash.authorized) {
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ 
                    ':profileId': 'NONEXISTENT'
                })
            }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Query orders table using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    return ctx.result.items || [];
}
                """
                ),
            )

            # listOrdersByProfile Pipeline Resolver
            self.api.create_resolver(
                "ListOrdersByProfileResolver",
                type_name="Query",
                field_name="listOrdersByProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_read_access_fn,
                    check_share_read_permissions_fn,
                    query_orders_by_profile_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # listSharesByProfile - List all shares for a profile with authorization (Pipeline Resolver)
            # FIXED Bug #27/#28: Added authorization check (owner or WRITE permission required)
            # Pipeline: VerifyProfileWriteAccessOrOwnerFn → QuerySharesFn

            # Function to query shares (only if authorized) - NOW USES SHARES TABLE
            query_shares_fn = appsync.AppsyncFunction(
                self,
                "QuerySharesFn",
                name=f"QuerySharesFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized, return empty query
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return {
            operation: 'Query',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ 
                    ':profileId': 'NONEXISTENT'
                })
            }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Query shares table directly by PK (profileId)
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    return ctx.result.items || [];
}
                """
                ),
            )

            # Verification function for shares (owner or WRITE permission) - uses profiles table
            verify_profile_write_or_owner_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileWriteAccessOrOwnerFn",
                name=f"VerifyProfileWriteAccessOrOwnerFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    
    // Validate profileId format - must start with 'PROFILE#' and have a UUID
    if (!profileId || !profileId.startsWith('PROFILE#')) {
        // Invalid format - set flags to deny and skip Query
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        ctx.stash.skipGetItem = true;
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP' })
            }
        };
    }
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    // Check if we skipped Query due to validation
    if (ctx.stash.skipGetItem) {
        return { authorized: false };
    }
    
    if (ctx.error) {
        // If there's a DynamoDB error (e.g., invalid key format), treat as unauthorized
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        // Profile not found - return empty list
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    // Check if caller is owner - ownerAccountId now has 'ACCOUNT#' prefix
    const callerSub = ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    
    if (profileOwner === 'ACCOUNT#' + callerSub) {
        ctx.stash.isOwner = true;
        ctx.stash.hasWritePermission = false; // Not needed when owner
        return { authorized: true };
    }
    
    // Not owner - check for WRITE permission via share
    ctx.stash.isOwner = false;
    
    // Only set profileId if it's valid, otherwise skip second function
    const profileIdArg = ctx.args.profileId;
    if (profileIdArg && profileIdArg.startsWith('PROFILE#')) {
        ctx.stash.profileId = profileIdArg;
    } else {
        ctx.stash.hasWritePermission = false;
        ctx.stash.skipGetItem = true; // Signal to skip next function
    }
    
    // Get share to check permissions
    return profile;
}
                """
                ),
            )

            # Check WRITE permission function - NOW USES SHARES TABLE
            check_write_permission_fn = appsync.AppsyncFunction(
                self,
                "CheckWritePermissionFn",
                name=f"CheckWritePermissionFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already owner or profile was invalid/not found, skip this check
    if (ctx.stash.isOwner || ctx.stash.skipGetItem) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Additional validation - if profileId is not set or invalid, skip
    if (!profileId || !profileId.startsWith('PROFILE#')) {
        ctx.stash.hasWritePermission = false;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Get share from shares table using profileId + targetAccountId (caller's sub)
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            targetAccountId: ctx.identity.sub 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, pass through
    if (ctx.stash.isOwner) {
        ctx.stash.hasWritePermission = false; // Not needed
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - not authorized (check profileId instead of PK)
    if (!share || !share.profileId) {
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    // Check for WRITE permission
    if (share.permissions && Array.isArray(share.permissions) && share.permissions.includes('WRITE')) {
        ctx.stash.hasWritePermission = true;
        return { authorized: true };
    }
    
    // Share exists but no WRITE permission
    ctx.stash.hasWritePermission = false;
    return { authorized: false };
}
                """
                ),
            )

            # listSharesByProfile Pipeline Resolver
            self.api.create_resolver(
                "ListSharesByProfileResolver",
                type_name="Query",
                field_name="listSharesByProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_write_or_owner_fn,
                    check_write_permission_fn,
                    query_shares_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # Share.targetAccount field resolver - Fetch Account details for targetAccountId
            self.api.create_resolver(
                "ShareTargetAccountResolver",
                type_name="Share",
                field_name="targetAccount",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                data_source=self.accounts_datasource,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const targetAccountId = ctx.source.targetAccountId;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            accountId: 'ACCOUNT#' + targetAccountId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        return null;  // Return null if account not found
    }
    
    return ctx.result;
}
                    """
                ),
            )

            # listInvitesByProfile - FIXED Bug #29: Added owner-only authorization
            # Pipeline: VerifyProfileOwnerFn -> QueryInvitesFn - uses profiles table
            verify_profile_owner_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerFn",
                name=f"VerifyProfileOwnerFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    const callerAccountId = ctx.identity.sub;
    
    // Profile not found
    if (!profile) {
        ctx.stash.authorized = false;
        ctx.stash.isOwner = false;
        return profile;
    }
    
    // Check if caller is the owner - ownerAccountId now has 'ACCOUNT#' prefix
    const isOwner = profile.ownerAccountId === 'ACCOUNT#' + callerAccountId;
    
    ctx.stash.authorized = isOwner;
    ctx.stash.isOwner = isOwner;
    ctx.stash.profileId = ctx.args.profileId;
    
    return profile;
}
                    """
                ),
            )

            # NOW USES INVITES TABLE
            query_invites_fn = appsync.AppsyncFunction(
                self,
                "QueryInvitesFn",
                name=f"QueryInvitesFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const authorized = ctx.stash.authorized;
    const profileId = ctx.stash.profileId || ctx.args.profileId;
    
    if (!authorized) {
        // Return empty query that yields no results
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({
                    ':profileId': 'NONEXISTENT'
                })
            }
        };
    }
    
    // Owner is authorized - query invites table using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    // Get current time as epoch seconds for comparison
    const nowEpochSeconds = util.time.nowEpochSeconds();
    
    // Filter out expired and used invites
    // expiresAt is now stored as epoch seconds (number)
    const activeInvites = items.filter(invite => {
        // Skip if already used
        if (invite.used === true) {
            return false;
        }
        
        // Skip if expired (expiresAt is epoch seconds)
        if (invite.expiresAt && invite.expiresAt < nowEpochSeconds) {
            return false;
        }
        
        return true;
    });
    
    // Map DynamoDB field names to GraphQL schema names
    // Convert expiresAt from epoch to ISO string for API response
    return activeInvites.map(invite => ({
        inviteCode: invite.inviteCode,
        profileId: invite.profileId,
        permissions: invite.permissions,
        expiresAt: util.time.epochMilliSecondsToISO8601(invite.expiresAt * 1000),
        createdAt: invite.createdAt,
        createdByAccountId: invite.createdBy
    }));
}
                    """
                ),
            )

            appsync.Resolver(
                self,
                "ListInvitesByProfilePipelineResolver",
                api=self.api,
                type_name="Query",
                field_name="listInvitesByProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[verify_profile_owner_fn, query_invites_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                    """
                ),
            )

            # getCatalog - Get a specific catalog by ID (uses catalogs table)
            # FIXED Bug #20: Added authorization check (owner or public catalog)
            self.catalogs_datasource.create_resolver(
                "GetCatalogResolver",
                type_name="Query",
                field_name="getCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
## If catalog not found, return null
#if(!$ctx.result || $ctx.result.isEmpty())
    $util.toJson(null)
#else
    ## Check authorization: Allow if catalog is public OR caller is owner
    #set($catalog = $ctx.result)
    #set($callerAccountId = $util.defaultIfNull($ctx.identity.sub, ""))
    #set($isPublic = $catalog.isPublic == "true")
    #set($isOwner = $catalog.ownerAccountId == "ACCOUNT#${callerAccountId}")
    
    #if($isPublic || $isOwner)
        $util.toJson($catalog)
    #else
        ## Non-owner accessing private catalog: return null
        $util.toJson(null)
    #end
#end
                """
                ),
            )

            # listPublicCatalogs - List all public catalogs (uses catalogs table GSI)
            self.api.create_resolver(
                "ListPublicCatalogsResolver",
                type_name="Query",
                field_name="listPublicCatalogs",
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'Query',
        index: 'isPublic-createdAt-index',
        query: {
            expression: 'isPublicStr = :isPublicStr',
            expressionValues: util.dynamodb.toMapValues({ ':isPublicStr': 'true' })
        },
        scanIndexForward: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result.items || [];
}
                """
                ),
            )

            # listMyCatalogs - List catalogs owned by current user (uses catalogs table GSI)
            self.api.create_resolver(
                "ListMyCatalogsResolver",
                type_name="Query",
                field_name="listMyCatalogs",
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'Query',
        index: 'ownerAccountId-index',
        query: {
            expression: 'ownerAccountId = :ownerAccountId',
            expressionValues: util.dynamodb.toMapValues({ ':ownerAccountId': ownerAccountId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result.items || [];
}
                """
                ),
            )

            # ================================================================
            # CRUD Mutation Resolvers
            # ================================================================

            # createSellerProfile - Create a new seller profile (Lambda resolver)
            self.create_profile_ds.create_resolver(
                "CreateSellerProfileResolver",
                type_name="Mutation",
                field_name="createSellerProfile",
            )

            # updateSellerProfile - Pipeline resolver: Lookup profile → Update profile
            # Step 1: Query profile by profileId using GSI
            lookup_profile_for_update_fn = appsync.AppsyncFunction(
                self,
                "LookupProfileForUpdateFn",
                name=f"LookupProfileForUpdateFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile) {
        util.error('Profile not found or access denied', 'Forbidden');
    }
    // Check ownership
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (profile.ownerAccountId !== expectedOwner) {
        util.error('Profile not found or access denied', 'Forbidden');
    }
    ctx.stash.profile = profile;
    return profile;
}
                    """
                ),
            )

            # Step 2: Update the profile
            update_profile_fn = appsync.AppsyncFunction(
                self,
                "UpdateProfileFn",
                name=f"UpdateProfileFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = ctx.stash.profile;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    
    // Build update expression dynamically to include optional unit fields
    const expressionParts = ['sellerName = :sellerName', 'updatedAt = :updatedAt'];
    const expressionValues = {
        ':sellerName': input.sellerName,
        ':updatedAt': now
    };
    
    // Add unitType if provided
    if (input.unitType !== undefined && input.unitType !== null) {
        expressionParts.push('unitType = :unitType');
        expressionValues[':unitType'] = input.unitType;
    }
    
    // Add unitNumber if provided
    if (input.unitNumber !== undefined && input.unitNumber !== null) {
        expressionParts.push('unitNumber = :unitNumber');
        expressionValues[':unitNumber'] = input.unitNumber;
    }
    
    // NEW STRUCTURE: Update using ownerAccountId + profileId keys
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ 
            ownerAccountId: profile.ownerAccountId, 
            profileId: input.profileId 
        }),
        update: {
            expression: 'SET ' + expressionParts.join(', '),
            expressionValues: util.dynamodb.toMapValues(expressionValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                    """
                ),
            )

            # Create updateSellerProfile pipeline resolver
            self.api.create_resolver(
                "UpdateSellerProfileResolver",
                type_name="Mutation",
                field_name="updateSellerProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[lookup_profile_for_update_fn, update_profile_fn],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                    """
                ),
            )

            # deleteSellerProfile - Delete a seller profile (owner only)
            # 9-step Pipeline resolver:
            # 1. Verify ownership by looking up profile metadata
            # 2. Query all shares for this profile from shares table
            # 3. Query all invites for this profile from invites table
            # 4. Delete all shares (TransactWriteItems)
            # 5. Delete all invites (TransactWriteItems)
            # 6. Query all SEASON# records for this profile
            # 7. Delete all seasons (TransactWriteItems)
            # 8. Delete the ownership record (ACCOUNT#{userId}|{profileId})
            # 9. Delete the metadata record (PROFILE#{profileId}|METADATA)

            # Step 1: Verify ownership - uses profiles table
            verify_profile_owner_for_delete_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForDeleteFn",
                name=f"VerifyProfileOwnerForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    // ownerAccountId now has 'ACCOUNT#' prefix
    if (profile.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can delete profile', 'Unauthorized');
    }
    // Store for next steps
    ctx.stash.profileId = ctx.args.profileId;
    ctx.stash.ownerAccountId = profile.ownerAccountId;
    return profile;
}
        """
                ),
            )

            # Step 2: Query all shares for this profile - NOW USES SHARES TABLE
            query_profile_shares_fn = appsync.AppsyncFunction(
                self,
                "QueryProfileSharesForDeleteFn",
                name=f"QueryProfileSharesForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // Query shares table directly by PK (profileId)
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    ctx.stash.sharesToDelete = ctx.result.items || [];
    return ctx.result.items;
}
        """
                ),
            )

            # Step 3: Query all invites for this profile - NOW USES INVITES TABLE
            query_profile_invites_fn = appsync.AppsyncFunction(
                self,
                "QueryProfileInvitesForDeleteFn",
                name=f"QueryProfileInvitesForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // Query invites table using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    ctx.stash.invitesToDelete = ctx.result.items || [];
    return ctx.result.items;
}
        """
                ),
            )

            # Step 4: Delete all shares using BatchDeleteItem - NOW USES SHARES TABLE
            delete_profile_shares_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileSharesFn",
                name=f"DeleteProfileSharesFn_{env_name}",
                api=self.api,
                data_source=self.shares_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const shares = ctx.stash.sharesToDelete || [];
    
    // If no shares to delete, skip with a no-op GetItem
    if (shares.length === 0) {
        return { operation: 'GetItem', key: util.dynamodb.toMapValues({ profileId: 'SKIP', targetAccountId: 'SKIP' }) };
    }
    
    // Build delete keys for BatchDeleteItem (max 25 items per batch) using shares table keys
    const keys = shares.slice(0, 25).map(share => 
        util.dynamodb.toMapValues({ profileId: share.profileId, targetAccountId: share.targetAccountId })
    );
    
    return {
        operation: 'BatchDeleteItem',
        tables: {
            '"""
                    + self.shares_table.table_name
                    + """': keys
        }
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
        """
                ),
            )

            # Step 5: Delete all invites using BatchDeleteItem - NOW USES INVITES TABLE
            delete_profile_invites_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileInvitesFn",
                name=f"DeleteProfileInvitesFn_{env_name}",
                api=self.api,
                data_source=self.invites_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invites = ctx.stash.invitesToDelete || [];
    
    // If no invites to delete, skip with a no-op GetItem
    if (invites.length === 0) {
        return { operation: 'GetItem', key: util.dynamodb.toMapValues({ inviteCode: 'SKIP' }) };
    }
    
    // Build delete keys for BatchDeleteItem (max 25 items per batch) using invites table key
    const keys = invites.slice(0, 25).map(invite => 
        util.dynamodb.toMapValues({ inviteCode: invite.inviteCode })
    );
    
    return {
        operation: 'BatchDeleteItem',
        tables: {
            '"""
                    + self.invites_table.table_name
                    + """': keys
        }
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
        """
                ),
            )

            # Step 6: Query all seasons for this profile - uses seasons table with profileId-index GSI
            query_profile_seasons_fn = appsync.AppsyncFunction(
                self,
                "QueryProfileSeasonsForDeleteFn",
                name=f"QueryProfileSeasonsForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // V2: Direct PK query on profileId (no GSI needed)
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    ctx.stash.seasonsToDelete = ctx.result.items || [];
    return ctx.result.items;
}
        """
                ),
            )

            # Step 7: Delete all seasons using TransactWriteItems - uses seasons table
            delete_profile_seasons_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileSeasonsFn",
                name=f"DeleteProfileSeasonsFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasons = ctx.stash.seasonsToDelete || [];
    
    // If no seasons to delete, skip
    if (seasons.length === 0) {
        return { operation: 'Query', query: { expression: 'profileId = :pk AND seasonId = :sk', expressionValues: util.dynamodb.toMapValues({ ':pk': 'SKIP', ':sk': 'SKIP' }) }, limit: 1 };
    }
    
    // V2: Build delete requests (max 100 items per TransactWriteItems) using composite key (profileId, seasonId)
    const transactItems = seasons.slice(0, 100).map(season => ({
        table: '"""
                    + self.seasons_table.table_name
                    + """',
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ profileId: season.profileId, seasonId: season.seasonId })
    }));
    
    return {
        operation: 'TransactWriteItems',
        transactItems: transactItems
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
        """
                ),
            )

            # Step 8: Delete the ownership record - in new design, ownership is tracked via ownerAccountId-index GSI on profiles table
            # No separate ownership record exists anymore - profiles are linked via ownerAccountId field
            # This step is now a no-op but kept for pipeline compatibility
            delete_profile_ownership_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileOwnershipFn",
                name=f"DeleteProfileOwnershipFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // In the new multi-table design, there is no separate ownership record
    // Ownership is tracked via the ownerAccountId field on the profile METADATA record
    // This is now a no-op - just return success
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
    };
}

export function response(ctx) {
    // No-op - ownership is implicit via ownerAccountId field
    return true;
}
        """
                ),
            )

            # Step 9: Delete the profile record - uses profiles table with new key structure
            delete_profile_metadata_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileMetadataFn",
                name=f"DeleteProfileMetadataFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    const ownerAccountId = ctx.stash.ownerAccountId;
    
    // NEW STRUCTURE: Delete profile using ownerAccountId as PK and profileId as SK
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            ownerAccountId: ownerAccountId, 
            profileId: profileId 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        // Log but don't fail - shares/invites were already deleted
        console.log('Warning: Failed to delete profile metadata', ctx.error);
    }
    return true;
}
        """
                ),
            )

            self.api.create_resolver(
                "DeleteSellerProfileResolver",
                type_name="Mutation",
                field_name="deleteSellerProfile",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_owner_for_delete_fn,
                    query_profile_shares_fn,
                    query_profile_invites_fn,
                    delete_profile_shares_fn,
                    delete_profile_invites_fn,
                    query_profile_seasons_fn,
                    delete_profile_seasons_fn,
                    delete_profile_ownership_fn,
                    delete_profile_metadata_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
        """
                ),
            )

            # Catalog.ownerAccountId - Strip ACCOUNT# prefix from stored value
            # Returns clean account ID for API consumers
            self.none_datasource.create_resolver(
                "CatalogOwnerAccountIdResolver",
                type_name="Catalog",
                field_name="ownerAccountId",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    const ownerAccountId = ctx.source.ownerAccountId;
    if (!ownerAccountId) return null;
    // Strip ACCOUNT# prefix if present
    if (ownerAccountId.startsWith('ACCOUNT#')) {
        return ownerAccountId.substring(8);
    }
    return ownerAccountId;
}
                """
                ),
            )

            # createCatalog - Create a new catalog (uses catalogs table)
            self.catalogs_datasource.create_resolver(
                "CreateCatalogResolver",
                type_name="Mutation",
                field_name="createCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
## Validate products array is not empty
#if($ctx.args.input.products.size() == 0)
    $util.error("Products array cannot be empty", "ValidationException")
#end
#set($catalogId = "CATALOG#$util.autoId()")
#set($now = $util.time.nowISO8601())
## Add productId to each product
#set($productsWithIds = [])
#foreach($product in $ctx.args.input.products)
    #set($productId = "PRODUCT#$util.autoId()")
    #set($productWithId = {
        "productId": $productId,
        "productName": $product.productName,
        "price": $product.price,
        "sortOrder": $product.sortOrder
    })
    #if($product.description)
        $util.qr($productWithId.put("description", $product.description))
    #end
    $util.qr($productsWithIds.add($productWithId))
#end
## Convert isPublic boolean to string for GSI
#if($ctx.args.input.isPublic)
    #set($isPublicStr = "true")
#else
    #set($isPublicStr = "false")
#end
{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($catalogId)
    },
    "attributeValues": {
        "catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
        "catalogType": $util.dynamodb.toDynamoDBJson("USER_CREATED"),
        "ownerAccountId": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "isPublic": $util.dynamodb.toDynamoDBJson($isPublicStr),
        "isPublicStr": $util.dynamodb.toDynamoDBJson($isPublicStr),
        "products": $util.dynamodb.toDynamoDBJson($productsWithIds),
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now)
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """
                ),
            )

            # updateCatalog - Update an existing catalog (uses catalogs table)
            self.catalogs_datasource.create_resolver(
                "UpdateCatalogResolver",
                type_name="Mutation",
                field_name="updateCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
#set($now = $util.time.nowISO8601())
## Add productId to each product if not present
#set($productsWithIds = [])
#foreach($product in $ctx.args.input.products)
    #set($productWithId = {
        "productName": $product.productName,
        "price": $product.price,
        "sortOrder": $product.sortOrder
    })
    ## Preserve existing productId or generate new one
    #if($product.productId)
        $util.qr($productWithId.put("productId", $product.productId))
    #else
        #set($newProductId = "PRODUCT#$util.autoId()")
        $util.qr($productWithId.put("productId", $newProductId))
    #end
    #if($product.description)
        $util.qr($productWithId.put("description", $product.description))
    #end
    $util.qr($productsWithIds.add($productWithId))
#end
## Convert isPublic boolean to string for GSI
#if($ctx.args.input.isPublic)
    #set($isPublicStr = "true")
#else
    #set($isPublicStr = "false")
#end
#set($ownerWithPrefix = "ACCOUNT#$ctx.identity.sub")
{
    "version": "2017-02-28",
    "operation": "UpdateItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    },
    "update": {
        "expression": "SET catalogName = :catalogName, isPublic = :isPublic, isPublicStr = :isPublicStr, products = :products, updatedAt = :updatedAt",
        "expressionValues": {
            ":catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
            ":isPublic": $util.dynamodb.toDynamoDBJson($isPublicStr),
            ":isPublicStr": $util.dynamodb.toDynamoDBJson($isPublicStr),
            ":products": $util.dynamodb.toDynamoDBJson($productsWithIds),
            ":updatedAt": $util.dynamodb.toDynamoDBJson($now)
        }
    },
    "condition": {
        "expression": "attribute_exists(catalogId) AND ownerAccountId = :ownerId",
        "expressionValues": {
            ":ownerId": $util.dynamodb.toDynamoDBJson($ownerWithPrefix)
        }
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Catalog not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson($ctx.result)
                """
                ),
            )

            # deleteCatalog - Delete a catalog (owner or admin for ADMIN_MANAGED)
            # Pipeline resolver with 3 steps:
            # 1. Get Catalog to check catalogType and ownerAccountId
            # 2. Check if catalog is in use by any seasons
            # 3. Delete if authorized
            # Note: Admin check uses JWT cognito:groups claim, not DynamoDB

            # Step 1: Get catalog to check catalogType and ownerAccountId - uses catalogs table
            get_catalog_for_delete_fn = appsync.AppsyncFunction(
                self,
                "GetCatalogForDeleteFn",
                name=f"GetCatalogForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Store caller ID for authorization check
    ctx.stash.callerId = ctx.identity.sub;
    // Get catalog using catalogId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            catalogId: catalogId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found', 'NotFound');
    }
    
    const catalog = ctx.result;
    const callerId = ctx.stash.callerId;
    
    // Check admin status from JWT cognito:groups claim (source of truth)
    // Handle both array and string format for groups
    const groupsClaim = ctx.identity.claims['cognito:groups'];
    let groups = [];
    if (Array.isArray(groupsClaim)) {
        groups = groupsClaim;
    } else if (typeof groupsClaim === 'string') {
        groups = [groupsClaim];
    }
    // Check for 'admin' (lowercase) - standard Cognito group name
    const isAdmin = groups.includes('admin') || groups.includes('ADMIN');
    // ownerAccountId now has 'ACCOUNT#' prefix
    const isOwner = catalog.ownerAccountId === 'ACCOUNT#' + callerId;
    
    // Authorization logic:
    // - Owner can delete their own catalogs
    // - Admin can delete ANY catalog (both USER_CREATED and ADMIN_MANAGED)
    if (isOwner || isAdmin) {
        ctx.stash.authorized = true;
    } else {
        util.error('Not authorized to delete this catalog', 'Forbidden');
    }
    
    ctx.stash.catalog = catalog;
    return catalog;
}
                    """
                ),
            )

            # Step 3: Check if catalog is in use by any seasons - uses seasons table GSI
            check_catalog_usage_fn = appsync.AppsyncFunction(
                self,
                "CheckCatalogUsageFn",
                name=f"CheckCatalogUsageFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Use GSI query instead of Scan for efficiency and consistency
    return {
        operation: 'Query',
        index: 'catalogId-index',
        query: {
            expression: 'catalogId = :catalogId',
            expressionValues: util.dynamodb.toMapValues({
                ':catalogId': catalogId
            })
        },
        limit: 5  // Only need a few to confirm usage
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const seasons = ctx.result.items || [];
    
    if (seasons.length > 0) {
        // Catalog is in use - return error
        const message = 'Cannot delete catalog: ' + seasons.length + ' season(s) are using it. Please update or delete those seasons first.';
        util.error(message, 'CatalogInUse');
    }
    
    return ctx.prev.result;  // Pass through catalog from previous step
}
                    """
                ),
            )

            # Step 4: Delete the catalog - uses catalogs table
            delete_catalog_fn = appsync.AppsyncFunction(
                self,
                "DeleteCatalogFn",
                name=f"DeleteCatalogFn_{env_name}",
                api=self.api,
                data_source=self.catalogs_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (!ctx.stash.authorized) {
        util.error('Not authorized', 'Forbidden');
    }
    
    const catalogId = ctx.args.catalogId;
    // Delete catalog using catalogId as primary key
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({
            catalogId: catalogId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
                    """
                ),
            )

            # Pipeline resolver for deleteCatalog
            appsync.Resolver(
                self,
                "DeleteCatalogPipelineResolver",
                api=self.api,
                type_name="Mutation",
                field_name="deleteCatalog",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    get_catalog_for_delete_fn,
                    check_catalog_usage_fn,
                    delete_catalog_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                    """
                ),
            )

            # createSeason - Create a new season for a profile (Pipeline with authorization) - uses seasons table
            # V2 STRUCTURE: PK=profileId, SK=seasonId
            create_season_fn = appsync.AppsyncFunction(
                self,
                "CreateSeasonFn",
                name=f"CreateSeasonFn_{env_name}",
                api=self.api,
                data_source=self.seasons_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = 'SEASON#' + util.autoId();
    const now = util.time.nowISO8601();
    const input = ctx.args.input;
    
    // V2 Season table structure: PK=profileId, SK=seasonId
    const season = {
        profileId: input.profileId,
        seasonId: seasonId,
        seasonName: input.seasonName,
        seasonYear: input.seasonYear,
        startDate: input.startDate,
        catalogId: input.catalogId,
        createdAt: now,
        updatedAt: now
    };
    
    if (input.endDate) {
        season.endDate = input.endDate;
    }
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ profileId: input.profileId, seasonId: seasonId }),
        attributeValues: util.dynamodb.toMapValues(season)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                """
                ),
            )

            self.api.create_resolver(
                "CreateSeasonResolver",  # Keep same logical ID to replace old resolver
                type_name="Mutation",
                field_name="createSeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_write_access_fn,
                    check_share_permissions_fn,
                    create_season_fn,
                ],
                code=appsync.Code.from_inline(
                    """
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
                """
                ),
            )

            # NOTE: updateSeason Lambda resolver REMOVED - replaced with pipeline resolver above
            # NOTE: createOrder Lambda resolver REMOVED - replaced with pipeline resolver above
            # NOTE: updateOrder, deleteOrder Lambda resolvers REMOVED - replaced with pipeline resolvers above

            # requestSeasonReport - Generate and download season report (Lambda resolver)
            self.request_season_report_ds.create_resolver(
                "RequestSeasonReportResolver",
                type_name="Mutation",
                field_name="requestSeasonReport",
            )

            # getUnitReport - Generate unit-level sales report (Lambda resolver)
            self.unit_reporting_ds.create_resolver(
                "GetUnitReportResolver",
                type_name="Query",
                field_name="getUnitReport",
            )

            # updateMyAccount - Update user metadata in DynamoDB (Lambda resolver)
            self.update_my_account_ds.create_resolver(
                "UpdateMyAccountResolver",
                type_name="Mutation",
                field_name="updateMyAccount",
            )

            # updateMyPreferences - Update user preferences in DynamoDB
            self.accounts_datasource.create_resolver(
                "UpdateMyPreferencesResolver",
                type_name="Mutation",
                field_name="updateMyPreferences",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = 'ACCOUNT#' + ctx.identity.sub;
    const preferences = ctx.args.preferences;
    const now = util.time.nowISO8601();
    
    // Use UpdateItem with attribute_exists condition to ensure account exists
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId: accountId }),
        update: {
            expression: 'SET preferences = :preferences, updatedAt = :updatedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':preferences': preferences,
                ':updatedAt': now
            })
        },
        condition: {
            expression: 'attribute_exists(accountId)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Account not found. Please sign out and sign in again.', 'NotFound');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                    """
                ),
            )

            # Custom domain for AppSync API
            self.api_domain_name = appsync.CfnDomainName(
                self,
                "ApiDomainName",
                certificate_arn=self.certificate.certificate_arn,
                domain_name=self.api_domain,
            )

            # Associate custom domain with API
            self.api_domain_association = appsync.CfnDomainNameApiAssociation(
                self,
                "ApiDomainAssociation",
                api_id=self.api.api_id,
                domain_name=self.api_domain_name.attr_domain_name,
            )
            # Ensure domain exists before association
            self.api_domain_association.add_dependency(self.api_domain_name)

            # Route53 record for AppSync custom domain
            route53.CnameRecord(
                self,
                "ApiDomainRecord",
                zone=self.hosted_zone,
                record_name=self.api_domain,
                domain_name=self.api_domain_name.attr_app_sync_domain_name,
            )

        # ====================================================================
        # CloudFront Distribution for SPA
        # ====================================================================

        # Origin Access Identity for S3
        self.origin_access_identity = cloudfront.OriginAccessIdentity(
            self, "OAI", comment="OAI for Popcorn Sales Manager SPA"
        )

        # Grant CloudFront read access to static assets bucket
        self.static_assets_bucket.grant_read(self.origin_access_identity)

        # CloudFront distribution with custom domain
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            domain_names=[self.site_domain],
            certificate=self.certificate,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.static_assets_bucket,
                    origin_access_identity=self.origin_access_identity,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # US, Canada, Europe only
            enabled=True,
        )

        # Route53 record for CloudFront distribution
        # This creates the A record for dev.kernelworx.app (or kernelworx.app in prod)
        # which is required by Cognito as the parent domain for login.dev.kernelworx.app
        self.site_domain_record = route53.ARecord(
            self,
            "SiteDomainRecord",
            zone=self.hosted_zone,
            record_name=self.site_domain,
            target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(self.distribution)),
        )

        # Add dependency: UserPoolDomain requires the parent domain A record to exist
        # Cognito custom domain login.dev.kernelworx.app needs dev.kernelworx.app to resolve
        if hasattr(self, "user_pool_domain") and hasattr(self.user_pool_domain, "node"):
            self.user_pool_domain.node.add_dependency(self.site_domain_record)
