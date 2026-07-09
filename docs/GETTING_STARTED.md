# Getting Started - Popcorn Sales Manager

## Prerequisites

- **Python 3.14+** with `uv` package manager
- **Node.js 20+** with `npm`
- **AWS CLI v2** configured with appropriate credentials
- **AWS Account** with permissions for IAM, DynamoDB, S3, Cognito, AppSync, ACM, Route 53, CloudFront, Lambda, SNS, CloudFormation, and CloudWatch/Billing
- **Git** for version control
- **OpenTofu** >= 1.7.0

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

### 3. Bootstrap the OpenTofu State Bucket

OpenTofu stores state in S3. The backend bucket must exist before the first `tofu init`:

```bash
# Deploy the bootstrap CloudFormation stack (adjust Environment if needed)
aws cloudformation deploy \
  --template-file tofu/bootstrap/state-bucket.yaml \
  --stack-name kernelworx-tofu-state \
  --parameter-overrides Environment=dev \
  --region us-east-1
```

Verify the bucket name matches the backend configured in `tofu/application/environments/dev/main.tf` (default: `kernelworx-tofu-state-us-east-1-dev`). If you changed regions or naming conventions, update the backend config or the template parameters accordingly.

### 4. Configure Deployment Settings

**Important**: Create a `.env` file in the repository root with your configuration:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Encryption passphrase for state files (generate a secure random string)
TF_VAR_encryption_passphrase=your-secure-passphrase-here
```

The deployment helper scripts source this root `.env` file. If you run `tofu` directly, export the variable instead:

```bash
export TF_VAR_encryption_passphrase='your-passphrase'
```

### 5. Verify Environment

```bash
# Check Python version
python --version  # Should be 3.14+

# Check uv
uv --version

# Check Node.js
node --version  # Should be 20+

# Check AWS credentials
aws sts get-caller-identity
```

## Deployment

### Quick Start Deployment (Recommended)

The easiest way to deploy is using OpenTofu:

```bash
cd tofu/application/environments/dev

# Initialize OpenTofu (first time only)
tofu init

# Preview changes
tofu plan

# Apply changes
tofu apply
```

The process will:
1. Load configuration from the root `.env`
2. Validate required settings
3. Deploy the OpenTofu-managed infrastructure

### Manual Deployment

If you prefer more control:

```bash
cd tofu/application/environments/dev

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
cd tofu/application/environments/dev

# Import existing DynamoDB table
tofu import 'module.dynamodb.aws_dynamodb_table.accounts' table-name

# Import existing S3 bucket
tofu import 'module.s3.aws_s3_bucket.static_assets' bucket-name
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
cd tofu/application/environments/dev
tofu apply

# For prod environment (when ready)
cd tofu/application/environments/prod
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
cd tofu/application/environments/dev
tofu apply
```

**Important:** the dev environment currently enables Google IdP and WebAuthn by default. If you do not have Google OAuth credentials, set `enable_google_idp = false` and `enable_webauthn = false` in `tofu/application/environments/dev/main.tf` before running `tofu apply`, or the deployment may create a broken Cognito configuration. If these variables are not set and Google IdP remains enabled, only email/password authentication will work reliably.

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

### E2E Smoke Tests

A Playwright-based e2e smoke suite exercises the deployed dev environment end-to-end (auth, profiles, campaigns, orders, sharing, signup). It requires the dev environment to be live and test users pre-created.

```bash
# Install Playwright browsers (first time only)
uv run playwright install chromium

# Run the full e2e suite
uv run pytest tests/e2e/ --ignore=tests/unit -v
```

See [`tests/e2e/README.md`](../tests/e2e/README.md) for full prerequisites, `.env` requirements, and troubleshooting.

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
cd tofu/application/environments/dev

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
cd tofu/application/environments/dev
tofu output
```

Key outputs include:
- **cognito_user_pool_id**: Cognito User Pool ID
- **cognito_client_id**: App client ID for authentication
- **appsync_api_url**: AppSync GraphQL API endpoint
- **cloudfront_distribution_id**: CloudFront distribution ID for invalidations
- **static_assets_bucket**: S3 bucket for SPA hosting
- **exports_bucket**: S3 bucket for generated reports
- **site_url**: Public URL of the deployed application

### Frontend Build and Deploy

After the backend is deployed, build and deploy the React SPA:

```bash
cd frontend

# Copy and fill in values from `tofu output`
cp .env.example .env.local

# Build the production bundle
npm run build

# Upload to S3
aws s3 sync dist s3://$(tofu -chdir=../tofu/application/environments/dev output -raw static_assets_bucket) --delete

# Invalidate the CloudFront distribution
aws cloudfront create-invalidation \
  --distribution-id $(tofu -chdir=../tofu/application/environments/dev output -raw cloudfront_distribution_id) \
  --paths "/*"
```

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

1. **Run Backend Tests** - `uv run pytest tests/unit --cov=src --cov-fail-under=100`
2. **Deploy Frontend** - Build the React SPA and deploy to S3 + CloudFront
3. **Configure Social Providers** - Set up OAuth apps with Google/Facebook (optional)
4. **Create an Admin Catalog** - Required before campaigns can be created
5. **Create Test Users** - `bash scripts/create-test-users.sh`
6. **Run E2E Smoke Tests** - `uv run pytest tests/e2e/ --ignore=tests/unit -v`
7. **Set Up CI/CD** - GitHub Actions for automated testing and deployment

## Support

- **Documentation**: See [AGENT.md](../AGENT.md) and [docs/](../) for development guidelines and specifications
- **Issues**: File issues on GitHub repository
- **Contact**: dave@repeatersolutions.com
