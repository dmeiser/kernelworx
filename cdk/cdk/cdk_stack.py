from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_iam as iam,
    aws_cognito as cognito,
    aws_appsync as appsync,
    aws_lambda as lambda_,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_certificatemanager as acm,
    CfnOutput,
)
from constructs import Construct
import os


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
        self.cognito_certificate = acm.Certificate(
            self,
            "CognitoCertificate",
            domain_name=self.cognito_domain,
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
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
                table_name=f"kernelworx-app-{env_name}",
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
                partition_key=dynamodb.Attribute(
                    name="email", type=dynamodb.AttributeType.STRING
                ),
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
            table_name=f"kernelworx-accounts-ue1-{env_name}",
            partition_key=dynamodb.Attribute(
                name="accountId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for email lookup (account by email)
        self.accounts_table.add_global_secondary_index(
            index_name="email-index",
            partition_key=dynamodb.Attribute(
                name="email", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Catalogs Table
        self.catalogs_table = dynamodb.Table(
            self,
            "CatalogsTable",
            table_name=f"kernelworx-catalogs-ue1-{env_name}",
            partition_key=dynamodb.Attribute(
                name="catalogId", type=dynamodb.AttributeType.STRING
            ),
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
            sort_key=dynamodb.Attribute(
                name="createdAt", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Profiles Table (includes shares, invites, ownership records)
        self.profiles_table = dynamodb.Table(
            self,
            "ProfilesTable",
            table_name=f"kernelworx-profiles-ue1-{env_name}",
            partition_key=dynamodb.Attribute(
                name="profileId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="recordType", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for profile owner lookup (list my profiles)
        self.profiles_table.add_global_secondary_index(
            index_name="ownerAccountId-index",
            partition_key=dynamodb.Attribute(
                name="ownerAccountId", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for shares by target account (list shared profiles)
        self.profiles_table.add_global_secondary_index(
            index_name="targetAccountId-index",
            partition_key=dynamodb.Attribute(
                name="targetAccountId", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for invite code lookup
        self.profiles_table.add_global_secondary_index(
            index_name="inviteCode-index",
            partition_key=dynamodb.Attribute(
                name="inviteCode", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # TTL for profile invites
        cfn_profiles_table = self.profiles_table.node.default_child
        cfn_profiles_table.time_to_live_specification = (
            dynamodb.CfnTable.TimeToLiveSpecificationProperty(
                attribute_name="TTL",
                enabled=True,
            )
        )

        # Seasons Table
        self.seasons_table = dynamodb.Table(
            self,
            "SeasonsTable",
            table_name=f"kernelworx-seasons-ue1-{env_name}",
            partition_key=dynamodb.Attribute(
                name="seasonId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for seasons by profile
        self.seasons_table.add_global_secondary_index(
            index_name="profileId-index",
            partition_key=dynamodb.Attribute(
                name="profileId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Orders Table
        self.orders_table = dynamodb.Table(
            self,
            "OrdersTable",
            table_name=f"kernelworx-orders-ue1-{env_name}",
            partition_key=dynamodb.Attribute(
                name="orderId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for orders by season
        self.orders_table.add_global_secondary_index(
            index_name="seasonId-index",
            partition_key=dynamodb.Attribute(
                name="seasonId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for orders by profile (cross-season order lookup)
        self.orders_table.add_global_secondary_index(
            index_name="profileId-index",
            partition_key=dynamodb.Attribute(
                name="profileId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt", type=dynamodb.AttributeType.STRING
            ),
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
                bucket_name=f"kernelworx-static-{env_name}",  # Deterministic name
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
                bucket_name=f"kernelworx-exports-{env_name}",  # Deterministic name
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
            role_name=f"kernelworx-lambda-execution-{env_name}",
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

        # Grant Lambda role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.seasons_table,
            self.orders_table,
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
            role_name=f"kernelworx-appsync-{env_name}",
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

        # Grant AppSync role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.seasons_table,
            self.orders_table,
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
            layer_version_name=f"kernelworx-shared-deps-{env_name}",
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
            function_name=f"kernelworx-create-profile-{env_name}",
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
            function_name=f"kernelworx-request-report-{env_name}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.report_generation.request_season_report",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # Reports may take longer
            memory_size=512,  # More memory for Excel generation
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Account Operations Lambda Functions
        self.update_my_account_fn = lambda_.Function(
            self,
            "UpdateMyAccountFnV2",
            function_name=f"kernelworx-update-account-{env_name}",
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
            function_name=f"kernelworx-post-auth-{env_name}",
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
                        ],
                        logout_urls=[
                            f"https://{self.site_domain}",
                            "http://localhost:5173",
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
                    ]
                )
        else:
            self.user_pool = cognito.UserPool(
                self,
                "UserPool",
                user_pool_name=f"kernelworx-users-{env_name}",
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
                        f"https://{self.site_domain}",
                        f"https://{self.site_domain}/callback",
                    ],
                    logout_urls=[
                        "http://localhost:5173",
                        f"https://{self.site_domain}",
                    ],
                ),
                supported_identity_providers=supported_providers,
                prevent_user_existence_errors=True,
            )

            # Custom domain configuration (login.{env}.kernelworx.app or login.kernelworx.app)
            self.user_pool_domain = self.user_pool.add_domain(
                "UserPoolDomain",
                custom_domain=cognito.CustomDomainOptions(
                    domain_name=self.cognito_domain,
                    certificate=self.cognito_certificate,
                ),
            )

            # Set domain to use Managed Login (version 2) instead of Hosted UI (classic)
            # This enables the branding deployed via deploy-cognito-branding.sh
            cfn_domain = self.user_pool_domain.node.default_child
            cfn_domain.add_property_override("ManagedLoginVersion", 2)

            # Cognito Hosted UI Customization
            # Note: CSS must be inline (no external files) and max 100KB
            # Read logo from assets
            logo_path = os.path.join(
                os.path.dirname(__file__), "..", "assets", "cognito-logo-base64.txt"
            )
            try:
                with open(logo_path, "r") as f:
                    logo_base64 = f.read().strip()
            except FileNotFoundError:
                logo_base64 = None  # Deploy without logo if file not found

            # AWS Cognito has a very restrictive whitelist of allowed CSS classes
            # Only submit button appears to be reliably supported
            # Other customization (logo, fonts, COPPA warning) must be done via:
            # 1. Logo: AWS Console or CLI after deployment
            # 2. Custom fonts: Not supported in basic tier
            # 3. COPPA warning: Implement in app UI, not in Cognito
            cognito_ui_css = """
                .submitButton-customizable {
                    background-color: #1976d2;
                }
            """

            # Apply UI customization
            ui_customization = cognito.CfnUserPoolUICustomizationAttachment(
                self,
                "UserPoolUICustomization",
                user_pool_id=self.user_pool.user_pool_id,
                client_id=self.user_pool_client.user_pool_client_id,
                css=cognito_ui_css,
            )

            # Note: Logo (ImageFile) must be added via AWS Console or AWS CLI after deployment
            # CDK L1 construct doesn't expose the ImageFile property correctly
            # To add logo: aws cognito-idp set-ui-customization --user-pool-id <pool-id> --client-id <client-id> --image-file fileb://cognito-logo.png
            if logo_base64:
                CfnOutput(
                    self,
                    "CognitoLogoBase64",
                    value=f"Logo file ready at cdk/assets/cognito-logo-base64.txt ({len(logo_base64)} chars)",
                    description="Use AWS CLI to upload: aws cognito-idp set-ui-customization",
                )

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
        # For new pools, create the record with RETAIN policy
        if not existing_user_pool_id:
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
        if hasattr(self, 'user_pool_domain') and hasattr(self, 'user_pool_client'):
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
                name=f"kernelworx-api-{env_name}",
                definition=appsync.Definition.from_file(schema_path),
                authorization_config=appsync.AuthorizationConfig(
                    default_authorization=appsync.AuthorizationMode(
                        authorization_type=appsync.AuthorizationType.USER_POOL,
                        user_pool_config=appsync.UserPoolConfig(user_pool=self.user_pool),
                    ),
                ),
                xray_enabled=True,
                log_config=appsync.LogConfig(
                    field_log_level=appsync.FieldLogLevel.ALL,
                    exclude_verbose_content=False,
                ) if enable_appsync_logging else None,
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
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || ctx.result.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can create invites', 'Unauthorized');
    }
    ctx.stash.profile = ctx.result;
    return ctx.result;
}
        """
                ),
            )

            create_invite_fn = appsync.AppsyncFunction(
                self,
                "CreateInviteFn",
                name=f"CreateInviteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const profileId = input.profileId;
    const permissions = input.permissions;
    const callerAccountId = ctx.identity.sub;
    
    // Generate invite code (first 10 chars of UUID, uppercase)
    const inviteCode = util.autoId().substring(0, 10).toUpperCase();
    
    // Calculate expiry (default 14 days, or custom expiresInDays if provided)
    const daysUntilExpiry = input.expiresInDays || 14;
    const expirySeconds = daysUntilExpiry * 24 * 60 * 60;
    const expiresAtEpoch = util.time.nowEpochSeconds() + expirySeconds;
    const now = util.time.nowISO8601();
    const expiresAtISO = util.time.epochMilliSecondsToISO8601(expiresAtEpoch * 1000);
    
    const key = {
        profileId: profileId,
        recordType: 'INVITE#' + inviteCode
    };
    
    const attributes = {
        inviteCode: inviteCode,
        profileId: profileId,
        permissions: permissions,
        createdBy: callerAccountId,
        createdAt: now,
        expiresAt: expiresAtISO,
        used: false,
        TTL: expiresAtEpoch
    };
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues(key),
        attributeValues: util.dynamodb.toMapValues(attributes),
        condition: {
            expression: 'attribute_not_exists(profileId)'
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
    
    return {
        inviteCode: ctx.result.inviteCode,
        profileId: ctx.result.profileId,
        permissions: ctx.result.permissions,
        expiresAt: ctx.result.expiresAt,
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
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || ctx.result.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can revoke shares', 'Unauthorized');
    }
    ctx.stash.profile = ctx.result;
    return ctx.result;
}
        """
                ),
            )

            delete_share_fn = appsync.AppsyncFunction(
                self,
                "DeleteShareFn",
                name=f"DeleteShareFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const targetAccountId = ctx.args.input.targetAccountId;
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + targetAccountId 
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
    const profileId = ctx.args.profileId;
    const inviteCode = ctx.args.inviteCode;
    
    // Verify caller is the profile owner
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result;
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

            # Second function to perform the actual deletion
            delete_invite_item_fn = appsync.AppsyncFunction(
                self,
                "DeleteInviteItemFn",
                name=f"DeleteInviteItemFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    const inviteCode = ctx.stash.inviteCode;
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'INVITE#' + inviteCode
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
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
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
    
    // Get profile metadata from profiles table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' }),
        consistentRead: true
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
    
    const profile = ctx.result;
    
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
            check_share_permissions_fn = appsync.AppsyncFunction(
                self,
                "CheckSharePermissionsFn",
                name=f"CheckSharePermissionsFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner or skipAuth), skip this check
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
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
    
    // Look up share in profiles table (recordType = SHARE#accountId)
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + ctx.identity.sub 
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
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    // If order not found, skip this function
    if (ctx.stash.orderNotFound) {
        // Return a no-op read
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
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
    
    // Get profile metadata from profiles table to check ownership
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' }),
        consistentRead: true
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
    
    const profile = ctx.result;
    
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
            check_share_read_permissions_fn = appsync.AppsyncFunction(
                self,
                "CheckShareReadPermissionsFn",
                name=f"CheckShareReadPermissionsFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
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
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Look up share in profiles table (recordType = SHARE#accountId)
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + ctx.identity.sub 
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
    // Direct GetItem on seasons table using seasonId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Season not found', 'NotFound');
    }
    // Store season in stash for next function
    ctx.stash.season = ctx.result;
    return ctx.result;
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
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ seasonId: season.seasonId }),
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
                pipeline_config=[lookup_season_fn, verify_profile_write_access_fn, check_share_permissions_fn, update_season_fn],
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
            # Now uses seasons_datasource with direct seasonId key
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
    // Direct GetItem on seasons table using seasonId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // For delete, if season not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!ctx.result) {
        ctx.stash.season = null;
        return null;
    }
    
    // Note: Authorization is simplified - relies on Cognito authentication
    // Full share-based authorization would require additional pipeline functions
    ctx.stash.season = ctx.result;
    return ctx.result;
}
                """
                ),
            )
            
            # Query orders for the season to delete (for cleanup)
            # Uses orders table with seasonId-index GSI
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
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ orderId: 'NOOP' })
        };
    }
    
    const seasonId = season.seasonId;
    
    // Query orders table using seasonId-index GSI
    return {
        operation: 'Query',
        index: 'seasonId-index',
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
    
    // Store orders to delete in stash (just need orderId for orders table)
    const orders = ctx.result.items || [];
    ctx.stash.ordersToDelete = orders;
    
    return orders;
}
                """
                ),
            )
            
            # Delete orders associated with the season
            # Uses orders_datasource with orderId key
            delete_season_orders_fn = appsync.AppsyncFunction(
                self,
                "DeleteSeasonOrdersFn",
                name=f"DeleteSeasonOrdersFn_{env_name}",
                api=self.api,
                data_source=self.orders_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const ordersToDelete = ctx.stash.ordersToDelete || [];
    
    if (ordersToDelete.length === 0) {
        return { payload: null };
    }
    
    // Delete first order only - simple approach for now
    const firstOrder = ordersToDelete[0];
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ orderId: firstOrder.orderId })
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
            key: util.dynamodb.toMapValues({ seasonId: 'NOOP' })
        };
    }
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ seasonId: season.seasonId })
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
                pipeline_config=[lookup_season_for_delete_fn, verify_profile_write_access_fn, check_share_permissions_fn, query_season_orders_for_delete_fn, delete_season_orders_fn, delete_season_fn],
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

            # updateOrder Pipeline: Direct GetItem → UpdateItem
            # Now uses orders_datasource with direct orderId key
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
    // Direct GetItem on orders table using orderId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ orderId: orderId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Order not found', 'NotFound');
    }
    // Store order in stash for next function
    ctx.stash.order = ctx.result;
    return ctx.result;
}
                """
                ),
            )

            # Bug #16 fix: Get catalog for updateOrder when lineItems are being updated
            # First looks up the season, then fetches the catalog
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
        // Return no-op request
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ seasonId: 'NOOP' })
        };
    }
    
    // Get the season's catalogId from the order
    const order = ctx.stash.order;
    const seasonId = order.seasonId;
    
    // Direct GetItem on seasons table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
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
        util.error('Season not found', 'NotFound');
    }
    
    const season = ctx.result;
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
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ orderId: order.orderId }),
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
                pipeline_config=[lookup_order_fn, verify_profile_write_access_fn, check_share_permissions_fn, get_catalog_for_update_order_fn, fetch_catalog_for_update_fn, update_order_fn],
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

            # deleteOrder Pipeline: Direct GetItem → DeleteItem
            # Separate lookup for delete - doesn't error on missing order (idempotent)
            # Now uses orders_datasource with direct orderId key
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
    // Direct GetItem on orders table using orderId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ orderId: orderId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // For delete, if order not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!ctx.result) {
        ctx.stash.order = null;
        return null;
    }
    
    ctx.stash.order = ctx.result;
    return ctx.result;
}
                """
                ),
            )
            
            # Delete order from orders table
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
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ orderId: 'NOOP' })
        };
    }
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ orderId: order.orderId })
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
                pipeline_config=[lookup_order_for_delete_fn, verify_profile_write_access_fn, check_share_permissions_fn, delete_order_fn],
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
            # Now uses seasons_datasource with direct seasonId key
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
    
    // Direct GetItem on seasons table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Season not found', 'NotFound');
    }
    
    const season = ctx.result;
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
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ orderId: orderId }),
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
                pipeline_config=[verify_profile_write_access_fn, check_share_permissions_fn, get_season_for_order_fn, get_catalog_fn, create_order_fn],
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
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'METADATA' 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Check ownership - ownerAccountId uses ACCOUNT# prefix now
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (!ctx.result || ctx.result.ownerAccountId !== expectedOwner) {
        util.error('Forbidden: Only profile owner can share profiles', 'Unauthorized');
    }
    ctx.stash.profile = ctx.result;
    return ctx.result;
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

            # Create share in profiles table
            create_share_fn = appsync.AppsyncFunction(
                self,
                "CreateShareFn",
                name=f"CreateShareFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const targetAccountId = ctx.stash.targetAccountId;
    const profileId = input.profileId || ctx.stash.invite.profileId;
    const permissions = input.permissions || ctx.stash.invite.permissions;
    const now = util.time.nowISO8601();
    
    // Share in profiles table: profileId + recordType: SHARE#targetAccountId
    const shareItem = {
        profileId: profileId,
        recordType: 'SHARE#' + targetAccountId,
        targetAccountId: targetAccountId,
        permissions: permissions,
        createdByAccountId: ctx.identity.sub,
        createdAt: now
    };
    
    // Use PutItem without condition to support both create and update (upsert)
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'SHARE#' + targetAccountId }),
        attributeValues: util.dynamodb.toMapValues(shareItem)
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

            # Create shareProfileDirect pipeline resolver (Bug #4 fix - added authorization)
            self.api.create_resolver(
                "ShareProfileDirectPipelineResolver",
                type_name="Mutation",
                field_name="shareProfileDirect",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[
                    verify_profile_owner_for_share_fn,
                    lookup_account_by_email_fn,
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
            # redeemProfileInvite Pipeline: Query inviteCode-index for invite → Create Share → Mark invite used
            # ================================================================
            # Uses profiles table inviteCode-index GSI
            lookup_invite_fn = appsync.AppsyncFunction(
                self,
                "LookupInviteFn",
                name=f"LookupInviteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.args.input.inviteCode;
    return {
        operation: 'Query',
        index: 'inviteCode-index',
        query: {
            expression: 'inviteCode = :inviteCode',
            expressionValues: util.dynamodb.toMapValues({ ':inviteCode': inviteCode })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('Invalid invite code', 'NotFound');
    }
    
    const invite = ctx.result.items[0];
    
    // Check if invite is already used
    if (invite.used) {
        util.error('Invite code has already been used', 'ConflictException');
    }
    
    // Check if invite is expired
    const now = util.time.nowEpochSeconds();
    if (invite.TTL && invite.TTL < now) {
        util.error('Invite code has expired', 'ConflictException');
    }
    
    ctx.stash.invite = invite;
    ctx.stash.targetAccountId = ctx.identity.sub;
    
    return invite;
}
        """
                ),
            )

            # Mark invite as used in profiles table
            mark_invite_used_fn = appsync.AppsyncFunction(
                self,
                "MarkInviteUsedFn",
                name=f"MarkInviteUsedFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invite = ctx.stash.invite;
    const now = util.time.nowISO8601();
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: invite.profileId, recordType: invite.recordType }),
        update: {
            expression: 'SET used = :used, usedBy = :usedBy, usedAt = :usedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':used': true,
                ':usedBy': ctx.identity.sub,
                ':usedAt': now,
                ':false': false
            })
        },
        condition: { expression: 'attribute_exists(profileId) AND used = :false' }
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
                pipeline_config=[lookup_invite_fn, create_share_fn, mark_invite_used_fn],
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
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "accountId": $util.dynamodb.toDynamoDBJson("ACCOUNT#" + $ctx.identity.sub)
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
    
    // Direct GetItem on profiles table using profileId and METADATA recordType
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // GetItem returns the profile directly (or null)
    const profile = ctx.result;
    
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
            check_profile_read_auth_fn = appsync.AppsyncFunction(
                self,
                "CheckProfileReadAuthFn",
                name=f"CheckProfileReadAuthFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
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
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    // Not owner - check for share
    ctx.stash.authorized = false;
    const profileId = ctx.stash.profileId;
    
    // Check for share in profiles table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + ctx.identity.sub 
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
            # Uses GSI1 (ownerAccountId-index) on profiles table to find METADATA records
            self.profiles_datasource.create_resolver(
                "ListMyProfilesResolver",
                type_name="Query",
                field_name="listMyProfiles",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "ownerAccountId = :ownerAccountId",
        "expressionValues": {
            ":ownerAccountId": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub")
        }
    },
    "index": "ownerAccountId-index"
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
## Filter to only return METADATA records (not OWNER# records)
#set($profiles = [])
#foreach($item in $ctx.result.items)
    #if($item.recordType == "METADATA")
        $util.qr($profiles.add($item))
    #end
#end
$util.toJson($profiles)
                """
                ),
            )

            # listSharedProfiles - Pipeline resolver to get profiles shared with current user
            # Step 1: Query GSI2 (targetAccountId-index) for shares where targetAccountId = current user
            list_shares_fn = appsync.AppsyncFunction(
                self,
                "ListSharesFn",
                name=f"ListSharesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = 'ACCOUNT#' + ctx.identity.sub;
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
        return util.error(ctx.error.message, ctx.error.type);
    }
    const shares = ctx.result.items || [];
    const profileIdSet = {};
    for (const share of shares) {
        profileIdSet[share.profileId] = true;
    }
    const profileIds = Object.keys(profileIdSet);
    ctx.stash.shares = shares;
    ctx.stash.profileIds = profileIds;
    return profileIds;
}
                    """
                ),
            )

            # Step 2: Batch get METADATA records for shared profiles
            profiles_table_name = self.profiles_table.table_name
            batch_get_profiles_fn = appsync.AppsyncFunction(
                self,
                "BatchGetSharedProfilesFn",
                name=f"BatchGetSharedProfilesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    f"""
import {{ util }} from '@aws-appsync/utils';

export function request(ctx) {{
    const profileIds = ctx.stash.profileIds || [];
    if (profileIds.length === 0) {{
        return {{ payload: [] }};
    }}
    
    const keys = [];
    for (const profileId of profileIds) {{
        keys.push(util.dynamodb.toMapValues({{ profileId: profileId, recordType: 'METADATA' }}));
    }}
    
    return {{
        operation: 'BatchGetItem',
        tables: {{
            '{profiles_table_name}': {{ keys: keys }}
        }}
    }};
}}

export function response(ctx) {{
    if (ctx.error) {{
        return util.error(ctx.error.message, ctx.error.type);
    }}
    
    if (!ctx.result || !ctx.result.data) {{
        return [];
    }}
    
    const profiles = ctx.result.data['{profiles_table_name}'] || [];
    const shares = ctx.stash.shares || [];
    
    const result = [];
    for (const profile of profiles) {{
        let permissions = [];
        for (const share of shares) {{
            if (share.profileId === profile.profileId) {{
                permissions = share.permissions || [];
                break;
            }}
        }}
        const enrichedProfile = {{}};
        for (const key in profile) {{
            enrichedProfile[key] = profile[key];
        }}
        enrichedProfile.permissions = permissions;
        result.push(enrichedProfile);
    }}
    return result;
}}
                    """
                ),
            )

            # Create pipeline resolver for listSharedProfiles
            appsync.Resolver(
                self,
                "ListSharedProfilesResolver",
                api=self.api,
                type_name="Query",
                field_name="listSharedProfiles",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
export function request(ctx) { return {}; }
export function response(ctx) { return ctx.prev.result; }
                    """
                ),
                pipeline_config=[list_shares_fn, batch_get_profiles_fn],
            )

            # getSeason - Get a specific season by ID with authorization
            # Pipeline: QuerySeasonFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → ReturnSeasonFn
            
            # Step 1: Get season directly from seasons table
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
    // Direct GetItem on seasons table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result) {
        // Season not found - return null (auth check will be skipped)
        ctx.stash.seasonNotFound = true;
        return null;
    }
    
    const season = ctx.result;
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
                    return_season_fn
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
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ seasonId: 'NOOP' })
        };
    }
    
    const profileId = ctx.args.profileId;
    // Query seasons table using profileId-index GSI
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
                    query_seasons_fn
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
            # Uses orders table with seasonId-index GSI
            self.orders_datasource.create_resolver(
                "SeasonTotalOrdersResolver",
                type_name="Season",
                field_name="totalOrders",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "seasonId-index",
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
            # Uses orders table with seasonId-index GSI
            self.orders_datasource.create_resolver(
                "SeasonTotalRevenueResolver",
                type_name="Season",
                field_name="totalRevenue",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "seasonId-index",
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
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    return callerAccountId === ownerAccountId;
}
                """
                ),
            )

            # SellerProfile.permissions - Return caller's permissions on this profile
            # If owner: ['READ', 'WRITE'], if shared: share.permissions, else: null
            # Uses profiles table to look up share
            self.profiles_datasource.create_resolver(
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
    
    // If caller is owner (ownerAccountId now uses ACCOUNT# prefix), no need to query
    const expectedOwner = 'ACCOUNT#' + callerAccountId;
    if (expectedOwner === ownerAccountId) {
        ctx.stash.isOwner = true;
        // Return a no-op query
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    // Query for share record in profiles table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + callerAccountId 
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
            
            # Step 1: Get order from orders table directly
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
    // Direct GetItem on orders table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ orderId: orderId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result) {
        // Order not found - return null (auth check will be skipped)
        ctx.stash.orderNotFound = true;
        return null;
    }
    
    const order = ctx.result;
    ctx.stash.order = order;
    
    // profileId is now stored directly on the order
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
                    return_order_fn
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
            
            # Step 1: Lookup season to get profileId (uses seasons table with direct GetItem)
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
    // Direct GetItem on seasons table using seasonId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result) {
        // Season not found - return empty, skip auth (will return empty array)
        ctx.stash.seasonNotFound = true;
        ctx.stash.authorized = false;
        return null;
    }
    
    const season = ctx.result;
    ctx.stash.season = season;
    ctx.stash.profileId = season.profileId;
    
    return season;
}
                """
                ),
            )
            
            # Step 4: Query orders (only if authorized) - uses orders table
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
            index: 'seasonId-index',
            query: {
                expression: 'seasonId = :seasonId',
                expressionValues: util.dynamodb.toMapValues({ 
                    ':seasonId': 'NONEXISTENT'
                })
            }
        };
    }
    
    const seasonId = ctx.args.seasonId;
    // Query orders table using seasonId-index GSI
    return {
        operation: 'Query',
        index: 'seasonId-index',
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
                    query_orders_by_season_fn
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
                    query_orders_by_profile_fn
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
            
            # Function to query shares (only if authorized) - uses profiles table
            query_shares_fn = appsync.AppsyncFunction(
                self,
                "QuerySharesFn",
                name=f"QuerySharesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
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
                expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
                expressionValues: util.dynamodb.toMapValues({ 
                    ':profileId': 'NONEXISTENT',
                    ':recordType': 'NONE'
                })
            }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Query profiles table for SHARE# records
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
            expressionValues: util.dynamodb.toMapValues({ 
                ':profileId': profileId,
                ':recordType': 'SHARE#'
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
        // Invalid format - set flags to deny and skip GetItem
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        ctx.stash.skipGetItem = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    // Get profile metadata to check ownership - uses profileId/recordType keys
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' }),
        consistentRead: true
    };
}

export function response(ctx) {
    // Check if we skipped GetItem due to validation
    if (ctx.stash.skipGetItem) {
        return { authorized: false };
    }
    
    if (ctx.error) {
        // If there's a DynamoDB error (e.g., invalid key format), treat as unauthorized
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    const profile = ctx.result;
    
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
            
            # Check WRITE permission function - uses profiles table
            check_write_permission_fn = appsync.AppsyncFunction(
                self,
                "CheckWritePermissionFn",
                name=f"CheckWritePermissionFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already owner or profile was invalid/not found, skip this check
    if (ctx.stash.isOwner || ctx.stash.skipGetItem) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Additional validation - if profileId is not set or invalid, skip
    if (!profileId || !profileId.startsWith('PROFILE#')) {
        ctx.stash.hasWritePermission = false;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
        };
    }
    
    // Get share using profileId/recordType keys
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'SHARE#' + ctx.identity.sub 
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
                    query_shares_fn
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
    
    // Get profile metadata using profileId/recordType keys
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, recordType: 'METADATA' })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result;
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

            query_invites_fn = appsync.AppsyncFunction(
                self,
                "QueryInvitesFn",
                name=f"QueryInvitesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
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
            query: {
                expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
                expressionValues: util.dynamodb.toMapValues({
                    ':profileId': 'NONEXISTENT',
                    ':recordType': 'NONEXISTENT'
                })
            }
        };
    }
    
    // Owner is authorized - query invites using profileId/recordType keys
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId,
                ':recordType': 'INVITE#'
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    // Get current time in ISO string format
    const nowEpochMillis = util.time.nowEpochMilliSeconds();
    const now = util.time.epochMilliSecondsToISO8601(nowEpochMillis);
    
    // Filter out expired and used invites
    const activeInvites = items.filter(invite => {
        // Skip if already used
        if (invite.used === true) {
            return false;
        }
        
        // Skip if expired (expiresAt is ISO string)
        if (invite.expiresAt && invite.expiresAt < now) {
            return false;
        }
        
        return true;
    });
    
    // Map DynamoDB field names to GraphQL schema names
    return activeInvites.map(invite => ({
        inviteCode: invite.inviteCode,
        profileId: invite.profileId,
        permissions: invite.permissions,
        expiresAt: invite.expiresAt,
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
            self.catalogs_datasource.create_resolver(
                "ListPublicCatalogsResolver",
                type_name="Query",
                field_name="listPublicCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "isPublic-createdAt-index",
    "query": {
        "expression": "isPublic = :isPublic",
        "expressionValues": {
            ":isPublic": $util.dynamodb.toDynamoDBJson("true")
        }
    },
    "scanIndexForward": false
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """
                ),
            )

            # listMyCatalogs - List catalogs owned by current user (uses catalogs table GSI)
            self.catalogs_datasource.create_resolver(
                "ListMyCatalogsResolver",
                type_name="Query",
                field_name="listMyCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "ownerAccountId-index",
    "query": {
        "expression": "ownerAccountId = :ownerAccountId",
        "expressionValues": {
            ":ownerAccountId": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub")
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
$util.toJson($ctx.result.items)
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

            # updateSellerProfile - Update an existing seller profile - uses profiles table
            self.profiles_datasource.create_resolver(
                "UpdateSellerProfileResolver",
                type_name="Mutation",
                field_name="updateSellerProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
#set($now = $util.time.nowISO8601())
{
    "version": "2017-02-28",
    "operation": "UpdateItem",
    "key": {
        "profileId": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "recordType": $util.dynamodb.toDynamoDBJson("METADATA")
    },
    "update": {
        "expression": "SET sellerName = :sellerName, updatedAt = :updatedAt",
        "expressionValues": {
            ":sellerName": $util.dynamodb.toDynamoDBJson($ctx.args.input.sellerName),
            ":updatedAt": $util.dynamodb.toDynamoDBJson($now)
        }
    },
    "condition": {
        "expression": "attribute_exists(profileId) AND ownerAccountId = :ownerId",
        "expressionValues": {
            ":ownerId": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub")
        }
    }
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Profile not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson($ctx.result)
                """
                ),
            )

            # deleteSellerProfile - Delete a seller profile (owner only)
            # 9-step Pipeline resolver:
            # 1. Verify ownership by looking up profile metadata
            # 2. Query all SHARE# records for this profile
            # 3. Query all INVITE# records for this profile
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
    // Get profile metadata using profileId/recordType keys
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Profile not found', 'NotFound');
    }
    // ownerAccountId now has 'ACCOUNT#' prefix
    if (ctx.result.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can delete profile', 'Unauthorized');
    }
    // Store for next steps
    ctx.stash.profileId = ctx.args.profileId;
    ctx.stash.ownerAccountId = ctx.result.ownerAccountId;
    return ctx.result;
}
        """
                ),
            )

            # Step 2: Query all SHARE# records for this profile - uses profiles table
            query_profile_shares_fn = appsync.AppsyncFunction(
                self,
                "QueryProfileSharesForDeleteFn",
                name=f"QueryProfileSharesForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // Query profiles table for SHARE# records using profileId/recordType keys
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId,
                ':recordType': 'SHARE#'
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

            # Step 3: Query all INVITE# records for this profile - uses profiles table
            query_profile_invites_fn = appsync.AppsyncFunction(
                self,
                "QueryProfileInvitesForDeleteFn",
                name=f"QueryProfileInvitesForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // Query profiles table for INVITE# records using profileId/recordType keys
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId AND begins_with(recordType, :recordType)',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': profileId,
                ':recordType': 'INVITE#'
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

            # Step 4: Delete all shares using BatchDeleteItem - uses profiles table
            delete_profile_shares_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileSharesFn",
                name=f"DeleteProfileSharesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const shares = ctx.stash.sharesToDelete || [];
    
    // If no shares to delete, skip with a no-op GetItem
    if (shares.length === 0) {
        return { operation: 'GetItem', key: util.dynamodb.toMapValues({ profileId: 'SKIP', recordType: 'SKIP' }) };
    }
    
    // Build delete keys for BatchDeleteItem (max 25 items per batch) using profileId/recordType keys
    const keys = shares.slice(0, 25).map(share => 
        util.dynamodb.toMapValues({ profileId: share.profileId, recordType: share.recordType })
    );
    
    return {
        operation: 'BatchDeleteItem',
        tables: {
            '""" + self.profiles_table.table_name + """': keys
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

            # Step 5: Delete all invites using BatchDeleteItem - uses profiles table
            delete_profile_invites_fn = appsync.AppsyncFunction(
                self,
                "DeleteProfileInvitesFn",
                name=f"DeleteProfileInvitesFn_{env_name}",
                api=self.api,
                data_source=self.profiles_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invites = ctx.stash.invitesToDelete || [];
    
    // If no invites to delete, skip with a no-op GetItem
    if (invites.length === 0) {
        return { operation: 'GetItem', key: util.dynamodb.toMapValues({ profileId: 'SKIP', recordType: 'SKIP' }) };
    }
    
    // Build delete keys for BatchDeleteItem (max 25 items per batch) using profileId/recordType keys
    const keys = invites.slice(0, 25).map(invite => 
        util.dynamodb.toMapValues({ profileId: invite.profileId, recordType: invite.recordType })
    );
    
    return {
        operation: 'BatchDeleteItem',
        tables: {
            '""" + self.profiles_table.table_name + """': keys
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
    // Query seasons table using profileId-index GSI
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
        return { operation: 'GetItem', key: util.dynamodb.toMapValues({ seasonId: 'SKIP' }) };
    }
    
    // Build delete requests (max 100 items per TransactWriteItems) using seasonId key
    const transactItems = seasons.slice(0, 100).map(season => ({
        table: '""" + self.seasons_table.table_name + """',
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ seasonId: season.seasonId })
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
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', recordType: 'NOOP' })
    };
}

export function response(ctx) {
    // No-op - ownership is implicit via ownerAccountId field
    return true;
}
        """
                ),
            )

            # Step 9: Delete the metadata record - uses profiles table with profileId/recordType keys
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
    
    // Delete profile metadata using profileId/recordType keys
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: profileId, 
            recordType: 'METADATA' 
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
                    delete_profile_metadata_fn
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
{
    "version": "2017-02-28",
    "operation": "UpdateItem",
    "key": {
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    },
    "update": {
        "expression": "SET catalogName = :catalogName, isPublic = :isPublic, products = :products, updatedAt = :updatedAt",
        "expressionValues": {
            ":catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
            ":isPublic": $util.dynamodb.toDynamoDBJson($isPublicStr),
            ":products": $util.dynamodb.toDynamoDBJson($productsWithIds),
            ":updatedAt": $util.dynamodb.toDynamoDBJson($now)
        }
    },
    "condition": {
        "expression": "attribute_exists(PK) AND ownerAccountId = :ownerId",
        "expressionValues": {
            ":ownerId": $util.dynamodb.toDynamoDBJson($ctx.identity.sub)
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
        return util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        return util.error('Catalog not found', 'NotFound');
    }
    
    const catalog = ctx.result;
    const callerId = ctx.stash.callerId;
    
    // Check admin status from JWT cognito:groups claim (source of truth)
    const groups = ctx.identity.claims['cognito:groups'] || [];
    const isAdmin = groups.includes('ADMIN');
    // ownerAccountId now has 'ACCOUNT#' prefix
    const isOwner = catalog.ownerAccountId === 'ACCOUNT#' + callerId;
    
    // Authorization logic:
    // - Owner can delete their own catalogs
    // - Admin can delete ANY catalog (both USER_CREATED and ADMIN_MANAGED)
    if (isOwner || isAdmin) {
        ctx.stash.authorized = true;
    } else {
        return util.error('Not authorized to delete this catalog', 'Forbidden');
    }
    
    ctx.stash.catalog = catalog;
    return catalog;
}
                    """
                ),
            )

            # Step 3: Check if catalog is in use by any seasons - uses seasons table
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
    console.log('CheckCatalogUsageFn request - catalogId:', catalogId);
    // Scan seasons table to find seasons using this catalog
    // Since catalogId is not indexed, we must use Scan with FilterExpression
    const scanRequest = {
        operation: 'Scan',
        consistentRead: true,  // CRITICAL: Ensure we see recently created seasons
        filter: {
            expression: 'catalogId = :catalogId',
            expressionValues: util.dynamodb.toMapValues({
                ':catalogId': catalogId
            })
        },
        limit: 5  // Only need a few examples
    };
    console.log('Scan request:', JSON.stringify(scanRequest));
    return scanRequest;
}

export function response(ctx) {
    if (ctx.error) {
        console.error('CheckCatalogUsageFn error:', JSON.stringify(ctx.error));
        return util.error(ctx.error.message, ctx.error.type);
    }
    
    console.log('CheckCatalogUsageFn response:', JSON.stringify(ctx.result));
    
    const seasons = ctx.result.items || [];
    console.log('Found seasons count:', seasons.length);
    
    if (seasons.length > 0) {
        // Catalog is in use - return error with details
        const seasonNames = seasons.map(s => s.seasonName || 'Unknown').slice(0, 3).join(', ');
        const message = `Cannot delete catalog: ${seasons.length} season(s) are using it (e.g., ${seasonNames}). Please update or delete those seasons first.`;
        console.error('Blocking deletion:', message);
        return util.error(message, 'CatalogInUse');
    }
    
    console.log('Catalog not in use, proceeding with deletion');
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
        return util.error('Not authorized', 'Forbidden');
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
        return util.error(ctx.error.message, ctx.error.type);
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
        return util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
                    """
                ),
            )

            # createSeason - Create a new season for a profile (Pipeline with authorization) - uses seasons table
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
    
    // Season record in new multi-table design uses seasonId as primary key
    const season = {
        seasonId: seasonId,
        profileId: input.profileId,
        seasonName: input.seasonName,
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
        key: util.dynamodb.toMapValues({ seasonId: seasonId }),
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
                pipeline_config=[verify_profile_write_access_fn, check_share_permissions_fn, create_season_fn],
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

            # updateMyAccount - Update user metadata in DynamoDB (Lambda resolver)
            self.update_my_account_ds.create_resolver(
                "UpdateMyAccountResolver",
                type_name="Mutation",
                field_name="updateMyAccount",
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
        route53.ARecord(
            self,
            "SiteDomainRecord",
            zone=self.hosted_zone,
            record_name=self.site_domain,
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(self.distribution)
            ),
        )
