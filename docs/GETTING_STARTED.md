# Getting Started - Popcorn Sales Manager

## Prerequisites

- **Python 3.13+** with `uv` package manager
- **Node.js 18+** with `npm`
- **AWS CLI** configured with appropriate credentials
- **AWS Account** with permissions for DynamoDB, S3, Cognito, AppSync, CloudFormation
- **Git** for version control

## Initial Setup

### 1. Clone and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/dmeiser/popcorn-sales-manager.git
cd popcorn-sales-manager

# Install Python dependencies (Lambda functions)
uv sync

# Install CDK dependencies
cd cdk
uv sync
npm install
cd ..
```

### 2. Configure AWS Credentials

```bash
# Configure AWS CLI with your dev account
aws configure --profile dev

# Set as default profile (optional)
export AWS_PROFILE=dev
```

### 3. Configure Deployment Settings

**Important**: Create a `.env` file in the `cdk/` directory with your configuration:

```bash
cd cdk
cp .env.example .env
```

Edit `cdk/.env` with your settings:

```bash
# Environment name (dev, staging, prod)
ENVIRONMENT=dev

# Domain Configuration - your Route53 hosted zone
BASE_DOMAIN=psm.repeatersolutions.com

# AWS Account Configuration
AWS_ACCOUNT_ID=750620721302
AWS_REGION=us-east-1

# Existing Resource Names (for import - leave blank for new deployment)
STATIC_BUCKET_NAME=
EXPORTS_BUCKET_NAME=
TABLE_NAME=
USER_POOL_ID=
APPSYNC_API_ID=
```

**⚠️ Security Note**: The `.env` file is gitignored and should **never** be committed to version control. It contains environment-specific configuration that may be sensitive.

### 4. Verify Environment

```bash
# Check Python version
python --version  # Should be 3.13+

# Check uv
uv --version

# Check Node.js
node --version  # Should be 18+

# Check AWS credentials
aws sts get-caller-identity
```

## Deployment

### Quick Start Deployment (Recommended)

The easiest way to deploy is using the provided deployment script, which reads configuration from your `.env` file:

```bash
cd cdk

# Ensure .env is configured (see step 3 above)

# Deploy using the script
./deploy.sh
```

The script will:
1. Load configuration from `.env`
2. Validate required settings
3. Auto-detect existing resources if specified in `.env`
4. Deploy the CDK stack

### Manual Deployment

If you prefer to deploy manually:

```bash
cd cdk

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Synthesize CloudFormation template
npx cdk synth

# Deploy the stack (reads from .env automatically)
npx cdk deploy --require-approval never
```

### Deployment with Existing Resources (Import)

If you have existing resources from a previous deployment, add them to your `.env` file:

```bash
# Edit cdk/.env
STATIC_BUCKET_NAME=kernelworx-static-dev
EXPORTS_BUCKET_NAME=kernelworx-exports-dev
TABLE_NAME=psm-app-dev
USER_POOL_ID=us-east-1_m861e2M
APPSYNC_API_ID=xxxxxxxxxxxxx
```

Then deploy normally with `./deploy.sh` - the script will automatically pass these as context parameters.

**Finding existing resources:**

```bash
# Find DynamoDB tables
aws dynamodb list-tables --query 'TableNames[?contains(@, `psm`)]'

# Find S3 buckets
aws s3 ls | grep kernelworx

# Find Cognito User Pools
aws cognito-idp list-user-pools --max-results 60 | grep popcorn

# Find AppSync APIs
aws appsync list-graphql-apis --query 'graphqlApis[?contains(name, `popcorn`)].id'
```

### Environment-Specific Deployments

Change the `ENVIRONMENT` variable in your `.env` file:

```bash
# For dev environment (default)
ENVIRONMENT=dev

# For prod environment
ENVIRONMENT=prod
```

Each environment gets its own isolated resources with environment-specific naming.
- S3 buckets: `kernelworx-static-{env}` and `kernelworx-exports-{env}`

## Social Authentication (Optional)

To enable social login providers, set environment variables before deployment:

```bash
# Google OAuth
export GOOGLE_CLIENT_ID="your-client-id"
export GOOGLE_CLIENT_SECRET="your-client-secret"

# Facebook OAuth
export FACEBOOK_APP_ID="your-app-id"
export FACEBOOK_APP_SECRET="your-app-secret"

# Apple Sign In
export APPLE_SERVICES_ID="your-services-id"
export APPLE_TEAM_ID="your-team-id"
export APPLE_KEY_ID="your-key-id"
export APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"

# Deploy with social providers
npx cdk deploy -c environment=dev
```

If these variables are not set, only email/password authentication will be available.

## Development Workflow

### Running Tests

```bash
# Run all Lambda function tests with coverage
uv run pytest tests/unit --cov=src --cov-fail-under=100

# Run specific test file
uv run pytest tests/unit/test_profile_sharing.py -v

# Run with coverage report
uv run pytest tests/unit --cov=src --cov-report=html
```

### Code Quality Checks

```bash
# Format code
uv run isort src/ tests/
uv run black src/ tests/

# Type checking
uv run mypy src/

# Run all checks
uv run isort src/ tests/ && \
uv run black src/ tests/ && \
uv run mypy src/ && \
uv run pytest tests/unit --cov=src --cov-fail-under=100
```

### CDK Commands

```bash
cd cdk

# Synthesize CloudFormation template
npx cdk synth

# Show differences between deployed and local
npx cdk diff -c environment=dev

# Deploy changes
npx cdk deploy -c environment=dev

# Destroy stack (WARNING: keeps data due to RETAIN policy)
npx cdk destroy -c environment=dev
```

## Accessing Deployed Resources

After deployment, CDK outputs key resource identifiers:

```bash
# Get stack outputs
aws cloudformation describe-stacks \
  --stack-name kernelworx-dev \
  --query 'Stacks[0].Outputs'
```

Key outputs include:
- **UserPoolId**: Cognito User Pool ID
- **UserPoolClientId**: App client ID for authentication
- **ApiEndpoint**: AppSync GraphQL API endpoint
- **TableName**: DynamoDB table name
- **StaticAssetsBucket**: S3 bucket for SPA hosting
- **ExportsBucket**: S3 bucket for generated reports

## Troubleshooting

### "Stack does not exist" but resources exist

Use the auto-import deployment method:
```bash
./cdk/deploy-with-import.sh dev
```

### CloudFormation stack stuck in REVIEW_IN_PROGRESS

```bash
# Delete the failed changeset
aws cloudformation delete-change-set \
  --stack-name kernelworx-dev \
  --change-set-name <changeset-name>
```

### Cognito domain already exists

Delete the existing domain or use a different environment name:
```bash
# Delete domain
aws cognito-idp delete-user-pool-domain \
  --domain popcorn-sales-dev-750620721302 \
  --user-pool-id us-east-1_XXXXXXXXX
```

### DynamoDB table already exists

Either:
1. Import it using context: `-c table_name=psm-app-dev`
2. Delete it: `aws dynamodb delete-table --table-name psm-app-dev`
3. Rename in different environment: `-c environment=prod`

## Cost Management

The deployed resources use serverless/on-demand pricing:

- **DynamoDB**: Pay-per-request (PAY_PER_REQUEST)
- **S3**: Pay for storage and requests
- **Cognito**: Essentials tier (~$0.015 per MAU after 50 free MAUs)
- **AppSync**: Pay per request and data transfer
- **Lambda**: Pay per invocation (not yet deployed)

**Monthly Budget**: $10/month with alerts at 80% and 100% configured in CloudWatch Billing Alerts.

## Next Steps

1. **Add Lambda Functions to CDK Stack** - Integrate the profile sharing handlers
2. **Deploy Frontend** - Create React SPA and deploy to S3 + CloudFront
3. **Configure Social Providers** - Set up OAuth apps with Google/Facebook/Apple
4. **Enable CloudFront** - Once account verification is complete
5. **Set Up CI/CD** - GitHub Actions for automated testing and deployment

## Support

- **Documentation**: See `Planning Documents/` folder for detailed specifications
- **Issues**: File issues on GitHub repository
- **Contact**: dave@repeatersolutions.com
