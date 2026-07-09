#!/bin/bash
# Frontend deployment script
# Fetches configuration from CloudFormation, builds, and deploys to S3/CloudFront

set -e

# Configuration
ENVIRONMENT="${ENVIRONMENT:-dev}"
REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="kernelworx-ue1-${ENVIRONMENT}"

echo "🚀 Deploying Frontend"
echo "   Environment: ${ENVIRONMENT}"
echo "   Stack: ${STACK_NAME}"
echo "   Region: ${REGION}"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# Step 1: Fetch configuration from CloudFormation
# ============================================================
echo "📡 Fetching configuration from CloudFormation..."

# Get Cognito User Pool ID (try direct lookup first, then from existing .env)
USER_POOL_ID=$(aws cloudformation list-stack-resources \
    --stack-name "$STACK_NAME" \
    --query "StackResourceSummaries[?LogicalResourceId=='UserPool6BA7E5F2'].PhysicalResourceId" \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" == "None" ]; then
    # User Pool might be imported - check existing .env or use known value
    if [ -f .env ]; then
        USER_POOL_ID=$(grep VITE_COGNITO_USER_POOL_ID .env | cut -d= -f2)
    fi
fi

if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" == "None" ]; then
    # Last resort - look up User Pool by name
    POOL_NAME="kernelworx-users-ue1-${ENVIRONMENT}"
    USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 50 \
        --query "UserPools[?Name=='$POOL_NAME'].Id | [0]" \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
fi

if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" == "None" ]; then
    echo "❌ Error: Could not find Cognito User Pool in stack $STACK_NAME"
    exit 1
fi
echo "   User Pool ID: $USER_POOL_ID"

# Get Cognito App Client ID from CloudFormation outputs
CLIENT_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" == "None" ]; then
    # Fallback: try to find it as a stack resource (old method)
    CLIENT_ID=$(aws cloudformation list-stack-resources \
        --stack-name "$STACK_NAME" \
        --query "StackResourceSummaries[?LogicalResourceId=='UserPoolAppClientDD0407EC'].PhysicalResourceId" \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
fi

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" == "None" ]; then
    # Last resort: look up client from User Pool
    CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
        --user-pool-id "$USER_POOL_ID" \
        --max-results 1 \
        --query "UserPoolClients[0].ClientId" \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
fi

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" == "None" ]; then
    echo "❌ Error: Could not find Cognito App Client in stack $STACK_NAME"
    exit 1
fi
echo "   Client ID: $CLIENT_ID"

# Construct site domain early; needed for fallback construction below
if [ "$ENVIRONMENT" == "prod" ]; then
    SITE_DOMAIN="kernelworx.app"
else
    SITE_DOMAIN="${ENVIRONMENT}.kernelworx.app"
fi

# OpenTofu environment directory (for output lookups)
TOFU_DIR="$SCRIPT_DIR/../tofu/application/environments/$ENVIRONMENT"

# Get Cognito custom domain
# 1. Prefer OpenTofu output (matches the managed infrastructure config)
# 2. Fall back to the actual Cognito user pool custom domain via AWS CLI
# 3. Last resort: construct the expected domain and warn
COGNITO_DOMAIN=$(cd "$TOFU_DIR" && tofu output -raw cognito_domain 2>/dev/null || echo "")

if [ -z "$COGNITO_DOMAIN" ] || [ "$COGNITO_DOMAIN" == "None" ]; then
    COGNITO_DOMAIN=$(aws cognito-idp describe-user-pool \
        --user-pool-id "$USER_POOL_ID" \
        --query 'UserPool.CustomDomain' \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
fi

if [ -z "$COGNITO_DOMAIN" ] || [ "$COGNITO_DOMAIN" == "None" ]; then
    COGNITO_DOMAIN="login.${SITE_DOMAIN}"
    echo "⚠️  Warning: Could not discover Cognito custom domain; using constructed value: $COGNITO_DOMAIN"
fi
echo "   Cognito Domain: $COGNITO_DOMAIN"

# Get S3 bucket for static assets
S3_BUCKET=$(aws cloudformation list-stack-resources \
    --stack-name "$STACK_NAME" \
    --query "StackResourceSummaries[?LogicalResourceId=='StaticAssetsDDEE9873'].PhysicalResourceId" \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$S3_BUCKET" ] || [ "$S3_BUCKET" == "None" ]; then
    # Fallback to naming convention
    S3_BUCKET="kernelworx-static-ue1-${ENVIRONMENT}"
fi

# Verify bucket exists
if ! aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
    echo "❌ Error: S3 bucket $S3_BUCKET does not exist"
    exit 1
fi
echo "   S3 Bucket: $S3_BUCKET"

# Get CloudFront Distribution ID
CF_DISTRIBUTION=$(aws cloudformation list-stack-resources \
    --stack-name "$STACK_NAME" \
    --query "StackResourceSummaries[?ResourceType=='AWS::CloudFront::Distribution'].PhysicalResourceId" \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$CF_DISTRIBUTION" ] || [ "$CF_DISTRIBUTION" == "None" ]; then
    # Fallback: Find distribution by domain alias
    if [ "$ENVIRONMENT" == "prod" ]; then
        SITE_ALIAS="kernelworx.app"
    else
        SITE_ALIAS="${ENVIRONMENT}.kernelworx.app"
    fi
    CF_DISTRIBUTION=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?contains(Aliases.Items, '$SITE_ALIAS')].Id | [0]" \
        --output text 2>/dev/null || echo "")
fi

if [ -z "$CF_DISTRIBUTION" ] || [ "$CF_DISTRIBUTION" == "None" ]; then
    echo "❌ Error: Could not find CloudFront distribution for $STACK_NAME"
    exit 1
fi
echo "   CloudFront Distribution: $CF_DISTRIBUTION"

# Construct API endpoint
API_ENDPOINT="https://api.${SITE_DOMAIN}/graphql"
echo "   Site Domain: $SITE_DOMAIN"
echo "   API Endpoint: $API_ENDPOINT"

# ============================================================
# Step 2: Generate .env.production file (used by Vite for builds)
# ============================================================
echo ""
echo "📝 Generating .env.production file..."

cat > .env.production << EOF
# Auto-generated by deploy.sh - $(date)
# AppSync GraphQL API
VITE_APPSYNC_ENDPOINT=${API_ENDPOINT}
VITE_APPSYNC_REGION=${REGION}

# Cognito User Pool
VITE_COGNITO_USER_POOL_ID=${USER_POOL_ID}
VITE_COGNITO_USER_POOL_CLIENT_ID=${CLIENT_ID}
VITE_COGNITO_DOMAIN=${COGNITO_DOMAIN}

# OAuth Configuration
VITE_OAUTH_REDIRECT_SIGNIN=https://${SITE_DOMAIN}
VITE_OAUTH_REDIRECT_SIGNOUT=https://${SITE_DOMAIN}
EOF

# Also update .env for local dev consistency
cp .env.production .env

echo "   .env.production file updated"

# ============================================================
# Step 3: Build frontend
# ============================================================
echo ""
echo "🔨 Building frontend..."
npm run build

# ============================================================
# Step 4: Sync to S3
# ============================================================
echo ""
echo "☁️  Uploading to S3..."
aws s3 sync dist "s3://${S3_BUCKET}" --delete --region "$REGION"

# ============================================================
# Step 5: Invalidate CloudFront cache
# ============================================================
echo ""
echo "🔄 Invalidating CloudFront cache..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$CF_DISTRIBUTION" \
    --paths "/*" \
    --query "Invalidation.Id" \
    --output text)

echo "   Invalidation ID: $INVALIDATION_ID"

# ============================================================
# Done!
# ============================================================
DEPLOY_TIME=$(date '+%Y-%m-%d %H:%M:%S %Z')

echo ""
echo "✅ Deployment complete!"
echo ""
echo "   Site URL: https://${SITE_DOMAIN}"
echo "   CloudFront invalidation may take 1-2 minutes to complete."
echo "   Deployed at: ${DEPLOY_TIME}"
echo ""
