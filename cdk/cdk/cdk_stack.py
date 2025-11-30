from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_iam as iam,
    aws_cognito as cognito,
    aws_appsync as appsync,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
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

        # ====================================================================
        # DynamoDB Table - Single Table Design
        # ====================================================================
        
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
            point_in_time_recovery=True,
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

        # ====================================================================
        # S3 Buckets
        # ====================================================================

        # Static assets bucket (for SPA hosting)
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
        # Cognito User Pool - Authentication (Essentials tier)
        # ====================================================================

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
            advanced_security_mode=cognito.AdvancedSecurityMode.ENFORCED,  # Essentials tier
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
                callback_urls=["http://localhost:5173", "https://PLACEHOLDER"],
                logout_urls=["http://localhost:5173", "https://PLACEHOLDER"],
            ),
            supported_identity_providers=supported_providers,
            prevent_user_existence_errors=True,
        )

        # Hosted UI domain
        self.user_pool_domain = self.user_pool.add_domain(
            "UserPoolDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"popcorn-sales-{env_name}-{self.account}"
            ),
        )

        # ====================================================================
        # AppSync GraphQL API
        # ====================================================================

        # Read GraphQL schema from file
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "schema", "schema.graphql"
        )

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

        # ====================================================================
        # CloudFront Distribution for SPA
        # ====================================================================

        # Temporarily disabled - pending account verification support case
        # TODO: Re-enable once account verification is complete
        
        # # Origin Access Identity for S3
        # self.origin_access_identity = cloudfront.OriginAccessIdentity(
        #     self, "OAI", comment="OAI for Popcorn Sales Manager SPA"
        # )

        # # Grant CloudFront read access to static assets bucket
        # self.static_assets_bucket.grant_read(self.origin_access_identity)

        # # CloudFront distribution
        # self.distribution = cloudfront.Distribution(
        #     self,
        #     "Distribution",
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

