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

        # ACM Certificate for custom domains (must be in us-east-1 for CloudFront/Cognito)
        # Note: Cognito custom domain temporarily disabled due to account verification requirement
        # Certificate includes AppSync API domain and CloudFront site domain
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=self.api_domain,
            subject_alternative_names=[
                # self.cognito_domain,  # Uncomment when Cognito custom domain is re-enabled
                self.site_domain,  # CloudFront distribution enabled
            ],
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
                removal_policy=RemovalPolicy.RETAIN,
                # Lambda triggers
                lambda_triggers=cognito.UserPoolTriggers(
                    post_authentication=self.post_auth_fn,
                ),
                # Note: Advanced security mode not compatible with Essentials tier
                # UI customization (logo, CSS) is available without advanced_security_mode
            )

            # Note: COPPA compliance warning (13+ age requirement) must be displayed
            # in application UI. Lambda trigger for age verification deferred to later phase.

            # Create user groups
            cognito.CfnUserPoolGroup(
                self,
                "AdminGroup",
                user_pool_id=self.user_pool.user_pool_id,
                group_name="ADMIN",
                description="Administrator users with elevated privileges",
            )

            cognito.CfnUserPoolGroup(
                self,
                "UserGroup",
                user_pool_id=self.user_pool.user_pool_id,
                group_name="USER",
                description="Standard application users",
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

            # Standard Cognito domain (using default AWS domain)
            # This provides Hosted UI at: https://kernelworx-{env}.auth.{region}.amazoncognito.com
            # Custom domain (login.{env}.kernelworx.app) will be enabled after AWS account verification
            self.user_pool_domain = self.user_pool.add_domain(
                "UserPoolDomain",
                cognito_domain=cognito.CognitoDomainOptions(
                    domain_prefix=f"kernelworx-{env_name}",
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

            # TODO: Re-enable custom domain after AWS account verification
            # self.user_pool_domain = self.user_pool.add_domain(
            #     "UserPoolDomain",
            #     custom_domain=cognito.CustomDomainOptions(
            #         domain_name=self.cognito_domain,
            #         certificate=self.certificate,
            #     ),
            # )
            #
            # # Route53 record for Cognito custom domain
            # route53.ARecord(
            #     self,
            #     "CognitoDomainRecord",
            #     zone=self.hosted_zone,
            #     record_name=self.cognito_domain,
            #     target=route53.RecordTarget.from_alias(
            #         targets.UserPoolDomainTarget(self.user_pool_domain)
            #     ),
            # )

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
                ),
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

            # Resolvers for profile sharing mutations
            # createProfileInvite - Pipeline resolver with authorization (Bug #2 fix)
            verify_profile_owner_for_invite_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForInviteFn",
                name=f"VerifyProfileOwnerForInviteFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId, 
            SK: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || ctx.result.ownerAccountId !== ctx.identity.sub) {
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
                data_source=self.dynamodb_datasource,
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
    
    // Calculate expiry (14 days = 1209600 seconds)
    const expirySeconds = 14 * 24 * 60 * 60;
    const expiresAtEpoch = util.time.nowEpochSeconds() + expirySeconds;
    const now = util.time.nowISO8601();
    const expiresAtISO = util.time.epochMilliSecondsToISO8601(expiresAtEpoch * 1000);
    
    const key = {
        PK: profileId,
        SK: 'INVITE#' + inviteCode
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
            expression: 'attribute_not_exists(PK)'
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
        createdBy: ctx.result.createdBy,
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
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId, 
            SK: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || ctx.result.ownerAccountId !== ctx.identity.sub) {
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
                data_source=self.dynamodb_datasource,
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
            PK: profileId, 
            SK: 'SHARE#' + targetAccountId 
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
                data_source=self.dynamodb_datasource,
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
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
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
    
    // Batch get: profile metadata and share record
    // Note: We can't use variables in AppSync JS for table names in BatchGetItem
    // So we use GetItem twice instead (still 2 operations but simpler)
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ PK: profileId, SK: 'METADATA' }),
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
    
    // Check if caller is owner
    // Debug: log the comparison
    const callerSub = ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    const isMatch = (profileOwner === callerSub);
    
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
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner or skipAuth), skip this check
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
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
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId, 
            SK: 'SHARE#' + ctx.identity.sub 
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
    if (!share || !share.PK) {
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
            # Used by: getSeason, listSeasonsByProfile
            # Less restrictive than VerifyProfileWriteAccessFn - allows READ or WRITE shares
            verify_profile_read_access_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileReadAccessFn",
                name=f"VerifyProfileReadAccessFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If season not found, skip this function
    if (ctx.stash.seasonNotFound) {
        // Return a no-op read that won't affect anything
        // We use the first valid key pattern we know exists: any METADATA item
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ 
                PK: 'ACCOUNT#' + ctx.identity.sub, 
                SK: 'METADATA' 
            })
        };
    }
    
    // Extract profileId from args or stash
    let profileId = null;
    
    if (ctx.args.profileId) {
        profileId = ctx.args.profileId;
    } else if (ctx.stash && ctx.stash.season && ctx.stash.season.profileId) {
        profileId = ctx.stash.season.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found in request', 'BadRequest');
    }
    
    // Store profileId in stash for next function
    ctx.stash.profileId = profileId;
    
    // Get profile metadata to check ownership
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ PK: profileId, SK: 'METADATA' }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If season not found, pass through (will return null at end)
    if (ctx.stash.seasonNotFound) {
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
    
    // Check if caller is owner
    const callerSub = ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    
    if (profileOwner === callerSub) {
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
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner), profile not found, or season not found, skip
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.seasonNotFound) {
        // Use a no-op read
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ 
                PK: 'ACCOUNT#' + ctx.identity.sub, 
                SK: 'METADATA' 
            })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId, 
            SK: 'SHARE#' + ctx.identity.sub 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized, profile not found, or season not found, pass through
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.seasonNotFound) {
        return { authorized: ctx.stash.authorized };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.PK) {
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

            # updateSeason Pipeline: GSI7 lookup → UpdateItem
            lookup_season_fn = appsync.AppsyncFunction(
                self,
                "LookupSeasonFn",
                name=f"LookupSeasonFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId || ctx.args.input.seasonId;
    return {
        operation: 'Query',
        index: 'GSI7',
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
                data_source=self.dynamodb_datasource,
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
        updates.push('#name = :name');
        exprNames['#name'] = 'name';
        exprValues[':name'] = input.seasonName;
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
        key: util.dynamodb.toMapValues({ PK: season.PK, SK: season.SK }),
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
    
    // DynamoDB UpdateItem returns old attributes by default
    // Manually construct response with updated values from input
    const season = ctx.stash.season;
    const input = ctx.arguments.input || ctx.arguments;
    
    return {
        ...season,
        seasonName: input.seasonName !== undefined ? input.seasonName : season.name,
        name: input.seasonName !== undefined ? input.seasonName : season.name,
        startDate: input.startDate !== undefined ? input.startDate : season.startDate,
        endDate: input.endDate !== undefined ? input.endDate : season.endDate,
        catalogId: input.catalogId !== undefined ? input.catalogId : season.catalogId,
        updatedAt: util.time.nowISO8601()
    };
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

            # deleteSeason Pipeline: GSI7 lookup → DeleteItem
            # Separate lookup for delete - doesn't error on missing season (idempotent)
            lookup_season_for_delete_fn = appsync.AppsyncFunction(
                self,
                "LookupSeasonForDeleteFn",
                name=f"LookupSeasonForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId;
    return {
        operation: 'Query',
        index: 'GSI7',
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
            
            delete_season_fn = appsync.AppsyncFunction(
                self,
                "DeleteSeasonFn",
                name=f"DeleteSeasonFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
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
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
        };
    }
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ PK: season.PK, SK: season.SK })
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
            self.api.create_resolver(
                "DeleteSeasonPipelineResolverV2",
                type_name="Mutation",
                field_name="deleteSeason",
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                pipeline_config=[lookup_season_for_delete_fn, verify_profile_write_access_fn, check_share_permissions_fn, delete_season_fn],
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

            # updateOrder Pipeline: GSI6 lookup → UpdateItem
            lookup_order_fn = appsync.AppsyncFunction(
                self,
                "LookupOrderFn",
                name=f"LookupOrderFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId || ctx.args.input.orderId;
    return {
        operation: 'Query',
        index: 'GSI6',
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
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('Order not found', 'NotFound');
    }
    // Store order in stash for next function
    ctx.stash.order = ctx.result.items[0];
    return ctx.result.items[0];
}
                """
                ),
            )

            # Bug #16 fix: Get catalog for updateOrder when lineItems are being updated
            get_catalog_for_update_order_fn = appsync.AppsyncFunction(
                self,
                "GetCatalogForUpdateOrderFn",
                name=f"GetCatalogForUpdateOrderFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
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
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
        };
    }
    
    // Get the season's catalogId from the order
    const order = ctx.stash.order;
    const seasonId = order.seasonId;  // Already has SEASON# prefix
    const profileId = order.profileId;  // Already has PROFILE# prefix
    
    // Use GetItem to fetch season (we know the exact PK and SK)
    // Season stored as: PK=profileId, SK=seasonId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId,
            SK: seasonId
        })
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
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (ctx.stash.skipCatalog) {
        // Return no-op request
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
        };
    }
    
    const catalogId = ctx.stash.catalogId;
    // Catalogs are stored with PK="CATALOG", SK=catalogId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ PK: 'CATALOG', SK: catalogId })
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
                data_source=self.dynamodb_datasource,
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
                util.error(`Quantity must be at least 1 (got ${quantity})`, 'BadRequest');
            }
            
            if (!productsMap[productId]) {
                util.error(`Product ${productId} not found in catalog`, 'BadRequest');
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
        key: util.dynamodb.toMapValues({ PK: order.PK, SK: order.SK }),
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

            # deleteOrder Pipeline: GSI6 lookup → DeleteItem
            # Separate lookup for delete - doesn't error on missing order (idempotent)
            lookup_order_for_delete_fn = appsync.AppsyncFunction(
                self,
                "LookupOrderForDeleteFn",
                name=f"LookupOrderForDeleteFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId;
    return {
        operation: 'Query',
        index: 'GSI6',
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
    
    // For delete, if order not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!ctx.result.items || ctx.result.items.length === 0) {
        ctx.stash.order = null;
        return null;
    }
    
    ctx.stash.order = ctx.result.items[0];
    return ctx.result.items[0];
}
                """
                ),
            )
            
            delete_order_fn = appsync.AppsyncFunction(
                self,
                "DeleteOrderFn",
                name=f"DeleteOrderFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
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
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
        };
    }
    
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ PK: order.PK, SK: order.SK })
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
            get_season_for_order_fn = appsync.AppsyncFunction(
                self,
                "GetSeasonForOrderFn",
                name=f"GetSeasonForOrderFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const seasonId = ctx.args.input.seasonId;
    
    // GetItem is strongly consistent - no GSI propagation delay
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ PK: profileId, SK: seasonId })
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
            get_catalog_fn = appsync.AppsyncFunction(
                self,
                "GetCatalogFn",
                name=f"GetCatalogFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.stash.catalogId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ PK: 'CATALOG', SK: catalogId })
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

            create_order_fn = appsync.AppsyncFunction(
                self,
                "CreateOrderFn",
                name=f"CreateOrderFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
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
            util.error(`Quantity must be at least 1 (got ${quantity})`, 'BadRequest');
        }
        
        if (!productsMap[productId]) {
            util.error(`Product ${productId} not found in catalog`, 'BadRequest');
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
    
    // Generate order ID
    const orderId = 'ORDER#' + util.autoId();
    const now = util.time.nowISO8601();
    
    // Build order item
    const orderItem = {
        PK: season.PK,
        SK: orderId,
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
        key: util.dynamodb.toMapValues({ PK: season.PK, SK: orderId }),
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

            # shareProfileDirect Pipeline: Verify owner → Query GSI8 for account by email → Create Share
            verify_profile_owner_for_share_fn = appsync.AppsyncFunction(
                self,
                "VerifyProfileOwnerForShareFn",
                name=f"VerifyProfileOwnerForShareFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            PK: profileId, 
            SK: 'METADATA' 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || ctx.result.ownerAccountId !== ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can share profiles', 'Unauthorized');
    }
    ctx.stash.profile = ctx.result;
    return ctx.result;
}
        """
                ),
            )

            lookup_account_by_email_fn = appsync.AppsyncFunction(
                self,
                "LookupAccountByEmailFn",
                name=f"LookupAccountByEmailFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const email = ctx.args.input.targetAccountEmail;
    return {
        operation: 'Query',
        index: 'GSI8',
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
        util.error(`No account found with email ${ctx.args.input.targetAccountEmail}`, 'NotFound');
    }
    
    const account = ctx.result.items[0];
    ctx.stash.targetAccountId = account.PK.replace('ACCOUNT#', '');
    
    return account;
}
                """
                ),
            )

            create_share_fn = appsync.AppsyncFunction(
                self,
                "CreateShareFn",
                name=f"CreateShareFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
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
    
    const shareItem = {
        PK: profileId,
        SK: 'SHARE#' + targetAccountId,
        shareId: 'SHARE#' + targetAccountId,
        profileId: profileId,
        targetAccountId: targetAccountId,
        permissions: permissions,
        createdByAccountId: ctx.identity.sub,
        createdAt: now,
        GSI1PK: 'ACCOUNT#' + targetAccountId,
        GSI1SK: profileId
    };
    
    // Use PutItem without condition to support both create and update (upsert)
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ PK: profileId, SK: 'SHARE#' + targetAccountId }),
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
            # redeemProfileInvite Pipeline: Query GSI9 for invite → Create Share → Mark invite used
            # ================================================================
            lookup_invite_fn = appsync.AppsyncFunction(
                self,
                "LookupInviteFn",
                name=f"LookupInviteFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.args.input.inviteCode;
    return {
        operation: 'Query',
        index: 'GSI9',
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

            mark_invite_used_fn = appsync.AppsyncFunction(
                self,
                "MarkInviteUsedFn",
                name=f"MarkInviteUsedFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invite = ctx.stash.invite;
    const now = util.time.nowISO8601();
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ PK: invite.PK, SK: invite.SK }),
        update: {
            expression: 'SET used = :used, usedBy = :usedBy, usedAt = :usedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':used': true,
                ':usedBy': ctx.identity.sub,
                ':usedAt': now,
                ':false': false
            })
        },
        condition: { expression: 'attribute_exists(PK) AND used = :false' }
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
            # getMyAccount - Get current user's account
            self.dynamodb_datasource.create_resolver(
                "GetMyAccountResolver",
                type_name="Query",
                field_name="getMyAccount",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "SK": $util.dynamodb.toDynamoDBJson("METADATA")
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

            # getProfile - Get a specific profile by ID (using GSI4)
            self.dynamodb_datasource.create_resolver(
                "GetProfileResolver",
                type_name="Query",
                field_name="getProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI4",
    "query": {
        "expression": "profileId = :profileId",
        "expressionValues": {
            ":profileId": $util.dynamodb.toDynamoDBJson($ctx.args.profileId)
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
## Filter results to find the actual PROFILE item (not seasons/orders with same profileId)
#set($profile = false)
#foreach($item in $ctx.result.items)
    #if($item.SK.startsWith("PROFILE#"))
        #set($profile = $item)
        #break
    #end
#end
#if(!$profile)
    $util.error("Profile not found", "NotFound")
#end
## TODO: Add authorization check here (owner or shared user)
$util.toJson($profile)
                """
                ),
            )

            # listMyProfiles - List profiles owned by current user
            self.dynamodb_datasource.create_resolver(
                "ListMyProfilesResolver",
                type_name="Query",
                field_name="listMyProfiles",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
            ":sk": $util.dynamodb.toDynamoDBJson("PROFILE#")
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

            # listSharedProfiles - List profiles shared with current user (via GSI1)
            self.dynamodb_datasource.create_resolver(
                "ListSharedProfilesResolver",
                type_name="Query",
                field_name="listSharedProfiles",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI1",
    "query": {
        "expression": "GSI1PK = :gsi1pk AND begins_with(GSI1SK, :gsi1sk)",
        "expressionValues": {
            ":gsi1pk": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
            ":gsi1sk": $util.dynamodb.toDynamoDBJson("PROFILE#")
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
## Extract profile IDs from shares and return them
## In production, you'd batch-get the actual profiles
$util.toJson($ctx.result.items)
                """
                ),
            )

            # getSeason - Get a specific season by ID with authorization
            # Pipeline: QuerySeasonFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → ReturnSeasonFn
            
            # Step 1: Query season from GSI7
            query_season_fn = appsync.AppsyncFunction(
                self,
                "QuerySeasonFn",
                name=f"QuerySeasonFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = ctx.args.seasonId;
    return {
        operation: 'Query',
        index: 'GSI7',
        query: {
            expression: 'seasonId = :seasonId AND SK = :sk',
            expressionValues: util.dynamodb.toMapValues({ 
                ':seasonId': seasonId,
                ':sk': seasonId
            })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result.items || ctx.result.items.length === 0) {
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
            
            # Step 3: Query seasons (only if authorized)
            query_seasons_fn = appsync.AppsyncFunction(
                self,
                "QuerySeasonsFn",
                name=f"QuerySeasonsFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized or profile not found, return no-op
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ PK: 'NOOP', SK: 'NOOP' })
        };
    }
    
    const profileId = ctx.args.profileId;
    return {
        operation: 'Query',
        query: {
            expression: 'PK = :pk AND begins_with(SK, :sk)',
            expressionValues: util.dynamodb.toMapValues({ 
                ':pk': profileId,
                ':sk': 'SEASON#'
            })
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
            self.dynamodb_datasource.create_resolver(
                "SeasonCatalogResolver",
                type_name="Season",
                field_name="catalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.source.catalogId)
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
            self.dynamodb_datasource.create_resolver(
                "SeasonTotalOrdersResolver",
                type_name="Season",
                field_name="totalOrders",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.source.seasonId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
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
            self.dynamodb_datasource.create_resolver(
                "SeasonTotalRevenueResolver",
                type_name="Season",
                field_name="totalRevenue",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.source.seasonId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
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
    return callerAccountId === ownerAccountId;
}
                """
                ),
            )

            # getOrder - Get a specific order by ID (using GSI6)
            self.dynamodb_datasource.create_resolver(
                "GetOrderResolver",
                type_name="Query",
                field_name="getOrder",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI6",
    "query": {
        "expression": "orderId = :orderId",
        "expressionValues": {
            ":orderId": $util.dynamodb.toDynamoDBJson($ctx.args.orderId)
        }
    },
    "limit": 1
}
                """
                ),
                response_mapping_template=appsync.MappingTemplate.from_string(
                    """
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.items.isEmpty())
    $util.toJson(null)
#else
    $util.toJson($ctx.result.items[0])
#end
                """
                ),
            )

            # listOrdersBySeason - List all orders for a season (VTL DynamoDB resolver)
            # NOTE: Replaced Lambda with direct DynamoDB query for better performance
            # FIXED Bug #25: Now queries GSI5 (seasonId index) and filters for ORDER# items
            self.dynamodb_datasource.create_resolver(
                "ListOrdersBySeasonResolver",
                type_name="Query",
                field_name="listOrdersBySeason",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI5",
    "query": {
        "expression": "seasonId = :seasonId",
        "expressionValues": {
            ":seasonId": $util.dynamodb.toDynamoDBJson($ctx.args.seasonId)
        }
    },
    "filter": {
        "expression": "begins_with(SK, :sk)",
        "expressionValues": {
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
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

            # listOrdersByProfile - List all orders for a profile (across all seasons)
            # FIXED Bug #26: Now queries main table (PK=profileId) instead of GSI2
            self.dynamodb_datasource.create_resolver(
                "ListOrdersByProfileResolver",
                type_name="Query",
                field_name="listOrdersByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.profileId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
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

            # listSharesByProfile - List all shares for a profile
            self.dynamodb_datasource.create_resolver(
                "ListSharesByProfileResolver",
                type_name="Query",
                field_name="listSharesByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.profileId),
            ":sk": $util.dynamodb.toDynamoDBJson("SHARE#")
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

            # listInvitesByProfile - List all active invites for a profile
            self.dynamodb_datasource.create_resolver(
                "ListInvitesByProfileResolver",
                type_name="Query",
                field_name="listInvitesByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.profileId),
            ":sk": $util.dynamodb.toDynamoDBJson("INVITE#")
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

            # getCatalog - Get a specific catalog by ID
            # FIXED Bug #20: Added authorization check (owner or public catalog)
            self.dynamodb_datasource.create_resolver(
                "GetCatalogResolver",
                type_name="Query",
                field_name="getCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
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
    #set($callerAccountId = $ctx.identity.sub)
    #set($isPublic = $catalog.isPublic)
    #set($isOwner = $catalog.ownerAccountId == $callerAccountId)
    
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

            # listPublicCatalogs - List all public catalogs
            self.dynamodb_datasource.create_resolver(
                "ListPublicCatalogsResolver",
                type_name="Query",
                field_name="listPublicCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI3",
    "query": {
        "expression": "GSI3PK = :gsi3pk AND begins_with(GSI3SK, :gsi3sk)",
        "expressionValues": {
            ":gsi3pk": $util.dynamodb.toDynamoDBJson("PUBLIC"),
            ":gsi3sk": $util.dynamodb.toDynamoDBJson("CATALOG#")
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

            # listMyCatalogs - List catalogs owned by current user
            self.dynamodb_datasource.create_resolver(
                "ListMyCatalogsResolver",
                type_name="Query",
                field_name="listMyCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI3",
    "query": {
        "expression": "GSI3PK = :gsi3pk AND begins_with(GSI3SK, :gsi3sk)",
        "expressionValues": {
            ":gsi3pk": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
            ":gsi3sk": $util.dynamodb.toDynamoDBJson("CATALOG#")
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

            # updateSellerProfile - Update an existing seller profile
            self.dynamodb_datasource.create_resolver(
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
        "PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId)
    },
    "update": {
        "expression": "SET sellerName = :sellerName, updatedAt = :updatedAt",
        "expressionValues": {
            ":sellerName": $util.dynamodb.toDynamoDBJson($ctx.args.input.sellerName),
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
            self.dynamodb_datasource.create_resolver(
                "DeleteSellerProfileResolver",
                type_name="Mutation",
                field_name="deleteSellerProfile",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "DeleteItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.profileId)
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
        $util.error("Profile not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
## Return true if successfully deleted
$util.toJson(true)
                """
                ),
            )

            # createCatalog - Create a new catalog
            self.dynamodb_datasource.create_resolver(
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
{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($catalogId)
    },
    "attributeValues": {
        "catalogId": $util.dynamodb.toDynamoDBJson($catalogId),
        "catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
        "catalogType": $util.dynamodb.toDynamoDBJson("USER_CREATED"),
        "ownerAccountId": $util.dynamodb.toDynamoDBJson($ctx.identity.sub),
        "isPublic": $util.dynamodb.toDynamoDBJson($ctx.args.input.isPublic),
        "products": $util.dynamodb.toDynamoDBJson($productsWithIds),
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now),
        ## GSI3 for catalog listing
        #if($ctx.args.input.isPublic)
            "GSI3PK": $util.dynamodb.toDynamoDBJson("PUBLIC"),
        #else
            "GSI3PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        #end
        "GSI3SK": $util.dynamodb.toDynamoDBJson($catalogId)
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

            # updateCatalog - Update an existing catalog
            self.dynamodb_datasource.create_resolver(
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
{
    "version": "2017-02-28",
    "operation": "UpdateItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    },
    "update": {
        "expression": "SET catalogName = :catalogName, isPublic = :isPublic, products = :products, updatedAt = :updatedAt, GSI3PK = :gsi3pk",
        "expressionValues": {
            ":catalogName": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogName),
            ":isPublic": $util.dynamodb.toDynamoDBJson($ctx.args.input.isPublic),
            ":products": $util.dynamodb.toDynamoDBJson($productsWithIds),
            ":updatedAt": $util.dynamodb.toDynamoDBJson($now),
            #if($ctx.args.input.isPublic)
                ":gsi3pk": $util.dynamodb.toDynamoDBJson("PUBLIC")
            #else
                ":gsi3pk": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub")
            #end
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

            # deleteCatalog - Delete a catalog (owner only)
            self.dynamodb_datasource.create_resolver(
                "DeleteCatalogResolver",
                type_name="Mutation",
                field_name="deleteCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string(
                    """
{
    "version": "2017-02-28",
    "operation": "DeleteItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
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
$util.toJson(true)
                """
                ),
            )

            # createSeason - Create a new season for a profile (Pipeline with authorization)
            create_season_fn = appsync.AppsyncFunction(
                self,
                "CreateSeasonFn",
                name=f"CreateSeasonFn_{env_name}",
                api=self.api,
                data_source=self.dynamodb_datasource,
                runtime=appsync.FunctionRuntime.JS_1_0_0,
                code=appsync.Code.from_inline(
                    """
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const seasonId = 'SEASON#' + util.autoId();
    const now = util.time.nowISO8601();
    const input = ctx.args.input;
    
    const season = {
        PK: input.profileId,
        SK: seasonId,
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
        key: util.dynamodb.toMapValues({ PK: input.profileId, SK: seasonId }),
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
