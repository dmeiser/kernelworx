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
git clone https://github.com/dmeiser/kernelworx.git
cd kernelworx

# Install Python dependencies (Lambda functions)
uv sync

# Install OpenTofu (macOS with Homebrew)
brew install opentofu

# Or on Linux
curl -fsSL https://get.opentofu.org | bash
```

### 2. Configure AWS Credentials

```bash
# Configure AWS CLI with your dev account
aws configure --profile dev

# Set as default profile (optional)
export AWS_PROFILE=dev
```

### 3. Configure Deployment Settings

**Important**: Create a `.env` file in the `tofu/` directory with your configuration:

```bash
cd tofu
cp .env.example .env
```

Edit `tofu/.env` with your settings:

```bash
# Encryption passphrase for state files (generate a secure random string)
ENCRYPTION_PASSPHRASE=your-secure-passphrase-here
```

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

The easiest way to deploy is using OpenTofu:

```bash
cd tofu/environments/dev

# Initialize OpenTofu (first time only)
tofu init

# Preview changes
tofu plan

# Apply changes
tofu apply
```

The script will:
1. Load configuration from `.env`
2. Validate required settings
3. Auto-detect existing resources if specified in `.env`
4. Deploy the CDK stack

### Manual Deployment

If you prefer more control:

```bash
cd tofu/environments/dev

# Set encryption passphrase
export TF_VAR_encryption_passphrase='your-passphrase'

# Initialize OpenTofu
tofu init

# Preview changes
tofu plan -out=tfplan

# Apply the plan
tofu apply tfplan
```

### Deployment with Existing Resources (Import)

If you have existing resources from a previous deployment, you can import them into OpenTofu state:

```bash
cd tofu/environments/dev

# Import existing DynamoDB table
tofu import 'module.dynamodb.aws_dynamodb_table.main' table-name

# Import existing S3 bucket
tofu import 'module.s3.aws_s3_bucket.static' bucket-name
```

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

Each environment has its own directory:

```bash
# For dev environment
cd tofu/environments/dev
tofu apply

# For prod environment (when ready)
cd tofu/environments/prod
tofu apply
```

Each environment gets its own isolated resources with environment-specific naming.

## Social Authentication (Optional)

To enable social login providers, set environment variables before deployment:

```bash
# Set OAuth credentials as OpenTofu variables
export TF_VAR_google_client_id="your-client-id"
export TF_VAR_google_client_secret="your-client-secret"

# Deploy
cd tofu/environments/dev
tofu apply
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
uv run ruff format src/ tests/

# Type checking
uv run mypy src/

# Run all checks
uv run isort src/ tests/ && \
uv run ruff format src/ tests/ && \
uv run mypy src/ && \
uv run pytest tests/unit --cov=src --cov-fail-under=100
```

### OpenTofu Commands

```bash
cd tofu/environments/dev

# Initialize working directory
tofu init

# Show differences between deployed and local
tofu plan

# Deploy changes
tofu apply

# Destroy resources (WARNING: use with caution)
tofu destroy
```

## Accessing Deployed Resources

After deployment, OpenTofu outputs key resource identifiers:

```bash
# Get outputs
cd tofu/environments/dev
tofu output
```

Key outputs include:
- **UserPoolId**: Cognito User Pool ID
- **UserPoolClientId**: App client ID for authentication
- **ApiEndpoint**: AppSync GraphQL API endpoint
- **TableName**: DynamoDB table name
- **StaticAssetsBucket**: S3 bucket for SPA hosting
- **ExportsBucket**: S3 bucket for generated reports

## Troubleshooting

### State lock issues

If a previous apply was interrupted:
```bash
tofu force-unlock <lock-id>
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
3. **Configure Social Providers** - Set up OAuth apps with Google/Facebook
4. **Enable CloudFront** - Once account verification is complete
5. **Set Up CI/CD** - GitHub Actions for automated testing and deployment

## Support

- **Documentation**: See `Planning Documents/` folder for detailed specifications
- **Issues**: File issues on GitHub repository
- **Contact**: dave@repeatersolutions.com
