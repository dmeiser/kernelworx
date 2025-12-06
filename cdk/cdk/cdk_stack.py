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
        base_domain = os.getenv("BASE_DOMAIN", "psm.repeatersolutions.com")

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
        # Note: CloudFront and Cognito custom domains temporarily disabled due to account verification requirement
        # Certificate currently only includes AppSync API domain
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=self.api_domain,
            subject_alternative_names=[
                # self.cognito_domain,  # Uncomment when Cognito custom domain is re-enabled
                # self.site_domain,  # Uncomment when CloudFront is re-enabled
            ],
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )

        # ====================================================================
        # DynamoDB Table - Single Table Design
        # ====================================================================
        
        # Check if we should import existing table
        existing_table_name = self.node.try_get_context("table_name")
        if existing_table_name:
            self.table = dynamodb.Table.from_table_name(
                self, "PsmApp", existing_table_name
            )
        else:
            self.table = dynamodb.Table(
                self,
                "PsmApp",
                table_name=f"psm-app-{env_name}",
                partition_key=dynamodb.Attribute(
                    name="PK", type=dynamodb.AttributeType.STRING
                ),
                sort_key=dynamodb.Attribute(
                    name="SK", type=dynamodb.AttributeType.STRING
                ),
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
                partition_key=dynamodb.Attribute(
                    name="GSI1PK", type=dynamodb.AttributeType.STRING
                ),
                sort_key=dynamodb.Attribute(
                    name="GSI1SK", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI2: Orders by profile (for cross-season order queries)
            self.table.add_global_secondary_index(
                index_name="GSI2",
                partition_key=dynamodb.Attribute(
                    name="GSI2PK", type=dynamodb.AttributeType.STRING
                ),
                sort_key=dynamodb.Attribute(
                    name="GSI2SK", type=dynamodb.AttributeType.STRING
                ),
                projection_type=dynamodb.ProjectionType.ALL,
            )

            # GSI3: Catalog ownership and sharing (for catalog management)
            self.table.add_global_secondary_index(
                index_name="GSI3",
                partition_key=dynamodb.Attribute(
                    name="GSI3PK", type=dynamodb.AttributeType.STRING
                ),
                sort_key=dynamodb.Attribute(
                    name="GSI3SK", type=dynamodb.AttributeType.STRING
                ),
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

            # GSI5: Season lookup by seasonId (for direct getSeason queries)
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

            # TTL configuration for invite expiration
            # ProfileInvite and CatalogShareInvite items have expiresAt attribute
            cfn_table = self.table.node.default_child
            cfn_table.time_to_live_specification = dynamodb.CfnTable.TimeToLiveSpecificationProperty(
                attribute_name="expiresAt",
                enabled=True,
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
                bucket_name=None,  # Auto-generate name
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
                bucket_name=None,  # Auto-generate name
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
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Grant Lambda role access to DynamoDB table
        self.table.grant_read_write_data(self.lambda_execution_role)

        # Grant Lambda role access to exports bucket
        self.exports_bucket.grant_read_write(self.lambda_execution_role)

        # AppSync service role (for direct DynamoDB resolvers)
        self.appsync_service_role = iam.Role(
            self,
            "AppSyncServiceRole",
            assumed_by=iam.ServicePrincipal("appsync.amazonaws.com"),
        )

        # Grant AppSync role access to DynamoDB table
        self.table.grant_read_write_data(self.appsync_service_role)

        # ====================================================================
        # Lambda Functions
        # ====================================================================

        # Path to Lambda source code (parent directory)
        lambda_src_path = os.path.join(os.path.dirname(__file__), "..", "..")

        # Common Lambda environment variables
        lambda_env = {
            "TABLE_NAME": self.table.table_name,
            "EXPORTS_BUCKET": self.exports_bucket.bucket_name,
            "POWERTOOLS_SERVICE_NAME": "popcorn-sales-manager",
            "LOG_LEVEL": "INFO",
        }

        # Asset bundling options to exclude unnecessary files
        from aws_cdk import BundlingOptions
        asset_bundling = lambda_.AssetCode(
            lambda_src_path,
            exclude=[
                ".venv",
                "cdk.out",
                "cdk",
                "htmlcov",
                ".pytest_cache",
                ".git",
                ".temp",
                "*.pyc",
                "__pycache__",
                "tests",
            ],
        )

        # Profile Sharing Lambda Functions
        self.create_profile_invite_fn = lambda_.Function(
            self,
            "CreateProfileInviteFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.profile_sharing.create_profile_invite",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.redeem_profile_invite_fn = lambda_.Function(
            self,
            "RedeemProfileInviteFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.profile_sharing.redeem_profile_invite",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.share_profile_direct_fn = lambda_.Function(
            self,
            "ShareProfileDirectFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.profile_sharing.share_profile_direct",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.revoke_share_fn = lambda_.Function(
            self,
            "RevokeShareFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.profile_sharing.revoke_share",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Season Operations Lambda Functions
        self.update_season_fn = lambda_.Function(
            self,
            "UpdateSeasonFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.season_operations.update_season",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.delete_season_fn = lambda_.Function(
            self,
            "DeleteSeasonFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.season_operations.delete_season",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Order Operations Lambda Functions
        self.update_order_fn = lambda_.Function(
            self,
            "UpdateOrderFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.order_operations.update_order",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.delete_order_fn = lambda_.Function(
            self,
            "DeleteOrderFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.order_operations.delete_order",
            code=asset_bundling,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.request_season_report_fn = lambda_.Function(
            self,
            "RequestSeasonReportFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="src.handlers.report_generation.request_season_report",
            code=asset_bundling,
            timeout=Duration.seconds(60),  # Reports may take longer
            memory_size=512,  # More memory for Excel generation
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
            # For imported pools, also get the client if provided
            existing_client_id = self.node.try_get_context("user_pool_client_id")
            if existing_client_id:
                self.user_pool_client = cognito.UserPoolClient.from_user_pool_client_id(
                    self, "AppClient", existing_client_id
                )
        else:
            self.user_pool = cognito.UserPool(
                self,
                "UserPool",
                user_pool_name=f"popcorn-sales-manager-{env_name}",
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
                # Enable Cognito Essentials (Advanced Security) for better branding and security
                advanced_security_mode=cognito.AdvancedSecurityMode.ENFORCED,
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
                user_pool_client_name="PopcornSalesManager-Web",
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
            # This provides Hosted UI at: https://popcorn-sales-manager-{env}.auth.{region}.amazoncognito.com
            # Custom domain (login.{env}.psm.repeatersolutions.com) will be enabled after AWS account verification
            self.user_pool_domain = self.user_pool.add_domain(
                "UserPoolDomain",
                cognito_domain=cognito.CognitoDomainOptions(
                    domain_prefix=f"popcorn-sales-manager-{env_name}",
                ),
            )
            
            # Cognito Hosted UI Customization
            # Note: CSS must be inline (no external files) and max 100KB
            cognito_ui_css = """
                /* Popcorn Sales Manager - Cognito Hosted UI Branding */
                
                /* Import fonts via CSS @import (must be first) */
                @import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&family=Satisfy&display=swap');
                
                /* COPPA Warning Banner */
                .banner-customizable {
                    background-color: #fff3cd !important;
                    border: 2px solid #ffc107 !important;
                    border-radius: 8px !important;
                    padding: 16px !important;
                    margin-bottom: 24px !important;
                    text-align: center !important;
                    font-family: 'Open Sans', sans-serif !important;
                }
                
                .banner-customizable::before {
                    content: "⚠️ Age Requirement: You must be 13 years or older to create an account. By signing up, you confirm that you meet this requirement." !important;
                    display: block !important;
                    font-weight: 600 !important;
                    color: #856404 !important;
                    font-size: 14px !important;
                    line-height: 1.5 !important;
                }
                
                /* Main container */
                .modal-content {
                    background-color: #ffffff !important;
                    border-radius: 12px !important;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15) !important;
                    font-family: 'Open Sans', sans-serif !important;
                }
                
                /* Logo/Header area */
                .logo-customizable {
                    max-width: 100% !important;
                    max-height: 100px !important;
                }
                
                /* Title */
                .textDescription-customizable {
                    font-family: 'Satisfy', cursive !important;
                    font-weight: 600 !important;
                    letter-spacing: 0.08em !important;
                    color: #1976d2 !important;
                    font-size: 2rem !important;
                    margin-bottom: 1.5rem !important;
                }
                
                /* Input labels */
                .label-customizable {
                    font-family: 'Open Sans', sans-serif !important;
                    font-weight: 600 !important;
                    color: #333333 !important;
                    font-size: 14px !important;
                }
                
                /* Input fields */
                .input-customizable {
                    font-family: 'Open Sans', sans-serif !important;
                    border: 1px solid #ccc !important;
                    border-radius: 4px !important;
                    padding: 10px 12px !important;
                    font-size: 16px !important;
                    color: #333333 !important;
                    background-color: #ffffff !important;
                }
                
                .input-customizable:focus {
                    border-color: #1976d2 !important;
                    outline: none !important;
                    box-shadow: 0 0 0 3px rgba(25, 118, 210, 0.1) !important;
                }
                
                /* Primary buttons (Sign in, Sign up) */
                .submitButton-customizable {
                    background-color: #1976d2 !important;
                    border: none !important;
                    border-radius: 4px !important;
                    color: #ffffff !important;
                    font-family: 'Open Sans', sans-serif !important;
                    font-weight: 600 !important;
                    font-size: 16px !important;
                    padding: 12px 24px !important;
                    cursor: pointer !important;
                    transition: background-color 0.2s ease !important;
                }
                
                .submitButton-customizable:hover {
                    background-color: #1565c0 !important;
                }
                
                /* Secondary buttons */
                .btn-secondary {
                    background-color: #f5f5f5 !important;
                    border: 1px solid #ccc !important;
                    color: #333333 !important;
                    font-family: 'Open Sans', sans-serif !important;
                }
                
                /* Social login buttons */
                .socialButton-customizable {
                    border-radius: 4px !important;
                    padding: 12px 16px !important;
                    font-family: 'Open Sans', sans-serif !important;
                    font-weight: 600 !important;
                    margin: 8px 0 !important;
                }
                
                /* Links */
                .anchor-customizable {
                    color: #1976d2 !important;
                    font-family: 'Open Sans', sans-serif !important;
                    text-decoration: none !important;
                }
                
                .anchor-customizable:hover {
                    text-decoration: underline !important;
                }
                
                /* Error messages */
                .error-customizable {
                    background-color: #ffebee !important;
                    border: 1px solid #f44336 !important;
                    border-radius: 4px !important;
                    color: #c62828 !important;
                    padding: 12px !important;
                    font-family: 'Open Sans', sans-serif !important;
                    font-size: 14px !important;
                }
                
                /* Background */
                body {
                    background-color: #f5f5f5 !important;
                    font-family: 'Open Sans', sans-serif !important;
                }
            """
            
            # Apply UI customization
            cognito.CfnUserPoolUICustomizationAttachment(
                self,
                "UserPoolUICustomization",
                user_pool_id=self.user_pool.user_pool_id,
                client_id=self.user_pool_client.user_pool_client_id,
                css=cognito_ui_css,
                # Optional: Add logo image (must be base64 encoded, max 100KB)
                # image_file="<base64-encoded-image-data>"
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

        # Output Cognito Hosted UI URL for easy access
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
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "schema", "schema.graphql"
        )

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
                name=f"popcorn-sales-manager-api-{env_name}",
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

            # Lambda data sources for profile sharing
            self.create_profile_invite_ds = self.api.add_lambda_data_source(
                "CreateProfileInviteDS",
                lambda_function=self.create_profile_invite_fn,
            )
            
            self.redeem_profile_invite_ds = self.api.add_lambda_data_source(
                "RedeemProfileInviteDS",
                lambda_function=self.redeem_profile_invite_fn,
            )
            
            self.share_profile_direct_ds = self.api.add_lambda_data_source(
                "ShareProfileDirectDS",
                lambda_function=self.share_profile_direct_fn,
            )
            
            self.revoke_share_ds = self.api.add_lambda_data_source(
                "RevokeShareDS",
                lambda_function=self.revoke_share_fn,
            )

            # Lambda data sources for season operations
            self.update_season_ds = self.api.add_lambda_data_source(
                "UpdateSeasonDS",
                lambda_function=self.update_season_fn,
            )

            self.delete_season_ds = self.api.add_lambda_data_source(
                "DeleteSeasonDS",
                lambda_function=self.delete_season_fn,
            )

            # Lambda data sources for order operations
            self.update_order_ds = self.api.add_lambda_data_source(
                "UpdateOrderDS",
                lambda_function=self.update_order_fn,
            )

            self.delete_order_ds = self.api.add_lambda_data_source(
                "DeleteOrderDS",
                lambda_function=self.delete_order_fn,
            )

            self.request_season_report_ds = self.api.add_lambda_data_source(
                "RequestSeasonReportDS",
                lambda_function=self.request_season_report_fn,
            )

            # Resolvers for profile sharing mutations
            self.create_profile_invite_ds.create_resolver(
                "CreateProfileInviteResolver",
                type_name="Mutation",
                field_name="createProfileInvite",
            )
            
            self.redeem_profile_invite_ds.create_resolver(
                "RedeemProfileInviteResolver",
                type_name="Mutation",
                field_name="redeemProfileInvite",
            )
            
            self.share_profile_direct_ds.create_resolver(
                "ShareProfileDirectResolver",
                type_name="Mutation",
                field_name="shareProfileDirect",
            )
            
            self.revoke_share_ds.create_resolver(
                "RevokeShareResolver",
                type_name="Mutation",
                field_name="revokeShare",
            )

            # DynamoDB resolvers for queries
            # getMyAccount - Get current user's account
            self.dynamodb_datasource.create_resolver(
                "GetMyAccountResolver",
                type_name="Query",
                field_name="getMyAccount",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "SK": $util.dynamodb.toDynamoDBJson("METADATA")
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.isEmpty())
    $util.error("Account not found", "NotFound")
#end
$util.toJson($ctx.result)
                """),
            )

            # getProfile - Get a specific profile by ID (using GSI4)
            self.dynamodb_datasource.create_resolver(
                "GetProfileResolver",
                type_name="Query",
                field_name="getProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI4",
    "query": {
        "expression": "profileId = :profileId",
        "expressionValues": {
            ":profileId": $util.dynamodb.toDynamoDBJson($ctx.args.profileId)
        }
    },
    "limit": 1
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
## Check authorization: caller must be owner or have share access
#if($ctx.result.items.isEmpty())
    $util.error("Profile not found", "NotFound")
#end
## TODO: Add authorization check here (owner or shared user)
$util.toJson($ctx.result.items[0])
                """),
            )

            # listMyProfiles - List profiles owned by current user
            self.dynamodb_datasource.create_resolver(
                "ListMyProfilesResolver",
                type_name="Query",
                field_name="listMyProfiles",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # listSharedProfiles - List profiles shared with current user (via GSI1)
            self.dynamodb_datasource.create_resolver(
                "ListSharedProfilesResolver",
                type_name="Query",
                field_name="listSharedProfiles",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI1",
    "query": {
        "expression": "GSI1PK = :gsi1pk AND begins_with(GSI1SK, :gsi1sk)",
        "expressionValues": {
            ":gsi1pk": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
            ":gsi1sk": $util.dynamodb.toDynamoDBJson("SHARE#")
        }
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
## Extract profile IDs from shares and return them
## In production, you'd batch-get the actual profiles
$util.toJson($ctx.result.items)
                """),
            )

            # getSeason - Get a specific season by ID (using GSI5)
            self.dynamodb_datasource.create_resolver(
                "GetSeasonResolver",
                type_name="Query",
                field_name="getSeason",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
    "limit": 1
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.items.isEmpty())
    $util.toJson(null)
#else
    $util.toJson($ctx.result.items[0])
#end
                """),
            )

            # listSeasonsByProfile - List all seasons for a profile
            self.dynamodb_datasource.create_resolver(
                "ListSeasonsByProfileResolver",
                type_name="Query",
                field_name="listSeasonsByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.profileId),
            ":sk": $util.dynamodb.toDynamoDBJson("SEASON#")
        }
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # getOrder - Get a specific order by ID (using GSI6)
            self.dynamodb_datasource.create_resolver(
                "GetOrderResolver",
                type_name="Query",
                field_name="getOrder",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
#if($ctx.result.items.isEmpty())
    $util.toJson(null)
#else
    $util.toJson($ctx.result.items[0])
#end
                """),
            )

            # listOrdersBySeason - List all orders for a season
            self.dynamodb_datasource.create_resolver(
                "ListOrdersBySeasonResolver",
                type_name="Query",
                field_name="listOrdersBySeason",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.seasonId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
        }
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # listOrdersByProfile - List all orders for a profile (across all seasons)
            self.dynamodb_datasource.create_resolver(
                "ListOrdersByProfileResolver",
                type_name="Query",
                field_name="listOrdersByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "index": "GSI2",
    "query": {
        "expression": "GSI2PK = :profileId",
        "expressionValues": {
            ":profileId": $util.dynamodb.toDynamoDBJson($ctx.args.profileId)
        }
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # listSharesByProfile - List all shares for a profile
            self.dynamodb_datasource.create_resolver(
                "ListSharesByProfileResolver",
                type_name="Query",
                field_name="listSharesByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # listInvitesByProfile - List all active invites for a profile
            self.dynamodb_datasource.create_resolver(
                "ListInvitesByProfileResolver",
                type_name="Query",
                field_name="listInvitesByProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # getCatalog - Get a specific catalog by ID
            self.dynamodb_datasource.create_resolver(
                "GetCatalogResolver",
                type_name="Query",
                field_name="getCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "GetItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("CATALOG"),
        "SK": $util.dynamodb.toDynamoDBJson($ctx.args.catalogId)
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """),
            )

            # listPublicCatalogs - List all public catalogs
            self.dynamodb_datasource.create_resolver(
                "ListPublicCatalogsResolver",
                type_name="Query",
                field_name="listPublicCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # listMyCatalogs - List catalogs owned by current user
            self.dynamodb_datasource.create_resolver(
                "ListMyCatalogsResolver",
                type_name="Query",
                field_name="listMyCatalogs",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
                """),
            )

            # ================================================================
            # CRUD Mutation Resolvers
            # ================================================================

            # createSellerProfile - Create a new seller profile
            self.dynamodb_datasource.create_resolver(
                "CreateSellerProfileResolver",
                type_name="Mutation",
                field_name="createSellerProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
#set($profileId = "PROFILE#" + $util.autoId())
#set($now = $util.time.nowISO8601())
{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson("ACCOUNT#$ctx.identity.sub"),
        "SK": $util.dynamodb.toDynamoDBJson($profileId)
    },
    "attributeValues": {
        "profileId": $util.dynamodb.toDynamoDBJson($profileId),
        "ownerAccountId": $util.dynamodb.toDynamoDBJson($ctx.identity.sub),
        "sellerName": $util.dynamodb.toDynamoDBJson($ctx.args.input.sellerName),
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now),
        "isOwner": $util.dynamodb.toDynamoDBJson(true),
        "permissions": $util.dynamodb.toDynamoDBJson(["READ", "WRITE"])
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """),
            )

            # updateSellerProfile - Update an existing seller profile
            self.dynamodb_datasource.create_resolver(
                "UpdateSellerProfileResolver",
                type_name="Mutation",
                field_name="updateSellerProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Profile not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson($ctx.result)
                """),
            )

            # deleteSellerProfile - Delete a seller profile (owner only)
            self.dynamodb_datasource.create_resolver(
                "DeleteSellerProfileResolver",
                type_name="Mutation",
                field_name="deleteSellerProfile",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Profile not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
## Return true if successfully deleted
$util.toJson(true)
                """),
            )

            # createCatalog - Create a new catalog
            self.dynamodb_datasource.create_resolver(
                "CreateCatalogResolver",
                type_name="Mutation",
                field_name="createCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string("""
#set($catalogId = "CATALOG#" + $util.autoId())
#set($now = $util.time.nowISO8601())
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
        "products": $util.dynamodb.toDynamoDBJson($ctx.args.input.products),
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """),
            )

            # updateCatalog - Update an existing catalog
            self.dynamodb_datasource.create_resolver(
                "UpdateCatalogResolver",
                type_name="Mutation",
                field_name="updateCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string("""
#set($now = $util.time.nowISO8601())
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
            ":products": $util.dynamodb.toDynamoDBJson($ctx.args.input.products),
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Catalog not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson($ctx.result)
                """),
            )

            # deleteCatalog - Delete a catalog (owner only)
            self.dynamodb_datasource.create_resolver(
                "DeleteCatalogResolver",
                type_name="Mutation",
                field_name="deleteCatalog",
                request_mapping_template=appsync.MappingTemplate.from_string("""
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
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Catalog not found or access denied", "Forbidden")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson(true)
                """),
            )

            # createSeason - Create a new season for a profile
            self.dynamodb_datasource.create_resolver(
                "CreateSeasonResolver",
                type_name="Mutation",
                field_name="createSeason",
                request_mapping_template=appsync.MappingTemplate.from_string("""
#set($seasonId = "SEASON#" + $util.autoId())
#set($now = $util.time.nowISO8601())
{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "SK": $util.dynamodb.toDynamoDBJson($seasonId)
    },
    "attributeValues": {
        "seasonId": $util.dynamodb.toDynamoDBJson($seasonId),
        "profileId": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "seasonName": $util.dynamodb.toDynamoDBJson($ctx.args.input.seasonName),
        "startDate": $util.dynamodb.toDynamoDBJson($ctx.args.input.startDate),
        #if($ctx.args.input.endDate)
            "endDate": $util.dynamodb.toDynamoDBJson($ctx.args.input.endDate),
        #end
        "catalogId": $util.dynamodb.toDynamoDBJson($ctx.args.input.catalogId),
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now)
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """),
            )

            # updateSeason - Update an existing season (Lambda resolver)
            self.update_season_ds.create_resolver(
                "UpdateSeasonResolver",
                type_name="Mutation",
                field_name="updateSeason",
            )

            # createOrder - Create a new order for a season
            self.dynamodb_datasource.create_resolver(
                "CreateOrderResolver",
                type_name="Mutation",
                field_name="createOrder",
                request_mapping_template=appsync.MappingTemplate.from_string("""
#set($orderId = "ORDER#" + $util.autoId())
#set($now = $util.time.nowISO8601())

## Calculate total amount from line items
#set($totalAmount = 0.0)
#foreach($item in $ctx.args.input.lineItems)
    #set($totalAmount = $totalAmount + ($item.quantity * $item.pricePerUnit))
#end

{
    "version": "2017-02-28",
    "operation": "PutItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson($ctx.args.input.seasonId),
        "SK": $util.dynamodb.toDynamoDBJson($orderId)
    },
    "attributeValues": {
        "orderId": $util.dynamodb.toDynamoDBJson($orderId),
        "profileId": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "seasonId": $util.dynamodb.toDynamoDBJson($ctx.args.input.seasonId),
        "customerName": $util.dynamodb.toDynamoDBJson($ctx.args.input.customerName),
        #if($ctx.args.input.customerPhone)
            "customerPhone": $util.dynamodb.toDynamoDBJson($ctx.args.input.customerPhone),
        #end
        #if($ctx.args.input.customerAddress)
            "customerAddress": $util.dynamodb.toDynamoDBJson($ctx.args.input.customerAddress),
        #end
        "orderDate": $util.dynamodb.toDynamoDBJson($ctx.args.input.orderDate),
        "paymentMethod": $util.dynamodb.toDynamoDBJson($ctx.args.input.paymentMethod),
        "lineItems": $util.dynamodb.toDynamoDBJson($ctx.args.input.lineItems),
        "totalAmount": $util.dynamodb.toDynamoDBJson($totalAmount),
        #if($ctx.args.input.notes)
            "notes": $util.dynamodb.toDynamoDBJson($ctx.args.input.notes),
        #end
        "createdAt": $util.dynamodb.toDynamoDBJson($now),
        "updatedAt": $util.dynamodb.toDynamoDBJson($now),
        ## Add GSI2 keys for orders by profile
        "GSI2PK": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "GSI2SK": $util.dynamodb.toDynamoDBJson($orderId)
    }
}
                """),
                response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result)
                """),
            )

            # updateOrder - Update an existing order (Lambda resolver)
            self.update_order_ds.create_resolver(
                "UpdateOrderResolver",
                type_name="Mutation",
                field_name="updateOrder",
            )

            # deleteOrder - Delete an order (Lambda resolver)
            self.delete_order_ds.create_resolver(
                "DeleteOrderResolver",
                type_name="Mutation",
                field_name="deleteOrder",
            )

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
        # TEMPORARILY DISABLED: AWS account needs verification before creating CloudFront resources
        # Error: "Your account must be verified before you can add new CloudFront resources"
        # Action Required: Contact AWS Support to verify account
        # Once verified, uncomment the code below to enable CloudFront with custom domain
        
        # # Origin Access Identity for S3
        # self.origin_access_identity = cloudfront.OriginAccessIdentity(
        #     self, "OAI", comment="OAI for Popcorn Sales Manager SPA"
        # )

        # # Grant CloudFront read access to static assets bucket
        # self.static_assets_bucket.grant_read(self.origin_access_identity)

        # # CloudFront distribution with custom domain
        # self.distribution = cloudfront.Distribution(
        #     self,
        #     "Distribution",
        #     domain_names=[self.site_domain],
        #     certificate=self.certificate,
        #     default_behavior=cloudfront.BehaviorOptions(
        #         origin=origins.S3Origin(
        #             self.static_assets_bucket,
        #             origin_access_identity=self.origin_access_identity,
        #         ),
        #         viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        #         cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
        #         compress=True,
        #     ),
        #     default_root_object="index.html",
        #     error_responses=[
        #         cloudfront.ErrorResponse(
        #             http_status=403,
        #             response_http_status=200,
        #             response_page_path="/index.html",
        #             ttl=Duration.seconds(0),
        #         ),
        #         cloudfront.ErrorResponse(
        #             http_status=404,
        #             response_http_status=200,
        #             response_page_path="/index.html",
        #             ttl=Duration.seconds(0),
        #         ),
        #     ],
        #     price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # US, Canada, Europe only
        #     enabled=True,
        # )

        # # Route53 record for CloudFront distribution
        # route53.ARecord(
        #     self,
        #     "SiteDomainRecord",
        #     zone=self.hosted_zone,
        #     record_name=self.site_domain,
        #     target=route53.RecordTarget.from_alias(
        #         targets.CloudFrontTarget(self.distribution)
        #     ),
        # )


