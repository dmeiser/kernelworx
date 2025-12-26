#!/bin/bash
# Deployment script for Popcorn Sales Manager CDK stack
# Minimal configuration - most values are derived automatically

set -e

# Change to script directory
cd "$(dirname "$0")"

# Parse command line arguments
DRY_RUN=false
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
    esac
done

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Environment defaults to 'dev' if not set
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Region defaults to AWS_REGION env var or us-east-1
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION

echo "🚀 Deploying Popcorn Sales Manager"
echo "   Environment: $ENVIRONMENT"
echo "   Region: $AWS_REGION"
echo "   Account: ${AWS_ACCOUNT_ID:-<from AWS profile>}"
if [ "$DRY_RUN" = true ]; then
    echo "   Mode: DRY RUN (no changes will be made)"
fi
echo ""

# Build context arguments
CONTEXT_ARGS="-c environment=$ENVIRONMENT"

if [ -n "$STATIC_BUCKET_NAME" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c static_bucket_name=$STATIC_BUCKET_NAME"
fi
if [ -n "$EXPORTS_BUCKET_NAME" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c exports_bucket_name=$EXPORTS_BUCKET_NAME"
fi
if [ -n "$TABLE_NAME" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c table_name=$TABLE_NAME"
fi
if [ -n "$USER_POOL_ID" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c user_pool_id=$USER_POOL_ID"
fi
if [ -n "$APPSYNC_API_ID" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c appsync_api_id=$APPSYNC_API_ID"
fi
if [ -n "$CREATE_COGNITO_DOMAIN" ]; then
    CONTEXT_ARGS="$CONTEXT_ARGS -c create_cognito_domain=$CREATE_COGNITO_DOMAIN"
fi

# Generate import file for resources that need to be imported
# TWO-STAGE IMPORT: First import SMS role (if needed), then everything else
echo "🔍 Checking for resources to import..."

# Cleanup orphaned resources before importing
echo ""
if [ "$DRY_RUN" = true ]; then
    echo "🔍 DRY RUN: Showing what cleanup would do (no changes will be made)..."
    uv run python -c "
from cdk.cleanup_hook import cleanup_before_deploy
cleanup_before_deploy(
    domain_names=['api.$ENVIRONMENT.kernelworx.app', 'login.$ENVIRONMENT.kernelworx.app'],
    site_domain='$ENVIRONMENT.kernelworx.app',
    environment_name='$ENVIRONMENT',
    dry_run=True
)
" || echo "   ⚠️  Cleanup check had warnings"
    echo ""
    echo "✅ Dry run complete. No changes were made."
    exit 0
fi

echo "🧹 Running cleanup for orphaned resources (CloudFront, OAI, certificates)..."
uv run python -c "
from cdk.cleanup_hook import cleanup_before_deploy
cleanup_before_deploy(
    domain_names=['api.$ENVIRONMENT.kernelworx.app', 'login.$ENVIRONMENT.kernelworx.app'],
    site_domain='$ENVIRONMENT.kernelworx.app',
    environment_name='$ENVIRONMENT'
)
" || echo "   ⚠️  Cleanup had warnings (continuing anyway)"
echo ""

# Stage 1: Try to import SMS role first (if it exists)
SMS_ROLE_IMPORT=$(uv run python generate_sms_role_import.py 2>/dev/null || echo "")
if [ -n "$SMS_ROLE_IMPORT" ] && [ -f "$SMS_ROLE_IMPORT" ]; then
    echo "📦 Stage 1: Importing SMS role first..."
    echo "Running: npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true -c skip_lambda_triggers=true --resource-mapping $SMS_ROLE_IMPORT --force"
    echo ""
    
    npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true -c skip_lambda_triggers=true --resource-mapping "$SMS_ROLE_IMPORT" --force --yes
    SMS_IMPORT_EXIT_CODE=$?
    rm -f "$SMS_ROLE_IMPORT"
    
    if [ $SMS_IMPORT_EXIT_CODE -ne 0 ]; then
        echo ""
        echo "❌ SMS role import failed!"
        exit $SMS_IMPORT_EXIT_CODE
    fi
    
    echo ""
    echo "✅ SMS role imported! Continuing with remaining resources..."
    echo ""
fi

# Stage 2: Import all other resources (including UserPool)
IMPORT_FILE=$(uv run python generate_import_file.py)

# Run deployment
if [ -n "$IMPORT_FILE" ] && [ -f "$IMPORT_FILE" ]; then
    echo "📦 Stage 2: Importing remaining resources from: $IMPORT_FILE"
    echo "Running: npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true -c skip_lambda_triggers=true --resource-mapping $IMPORT_FILE --force --yes"
    echo ""
    
    # Run import operation with mapping file, skipping UserPoolDomain and Lambda triggers
    # Lambda triggers must be skipped during import because the Lambda functions don't exist in CloudFormation yet
    npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true -c skip_lambda_triggers=true --resource-mapping "$IMPORT_FILE" --force --yes
    IMPORT_EXIT_CODE=$?
    
    if [ $IMPORT_EXIT_CODE -ne 0 ]; then
        echo ""
        echo "❌ Import failed!"
        rm -f "$IMPORT_FILE"
        exit $IMPORT_EXIT_CODE
    fi
    
    echo ""
    echo "✅ Import complete! Now deploying to create Lambda functions and other resources..."
    echo ""
    
    # Clean up import file after successful import
    rm -f "$IMPORT_FILE"
    
    # Run normal deployment after import
    echo "Running: npx cdk deploy $CONTEXT_ARGS --require-approval never"
    echo ""
    npx cdk deploy $CONTEXT_ARGS --require-approval never
    DEPLOY_EXIT_CODE=$?
else
    echo "Running: npx cdk deploy $CONTEXT_ARGS --require-approval never"
    echo ""
    
    npx cdk deploy $CONTEXT_ARGS --require-approval never
    DEPLOY_EXIT_CODE=$?
fi

if [ $DEPLOY_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Deployment failed!"
    exit $DEPLOY_EXIT_CODE
fi

echo ""
echo "✅ Deployment complete!"

# Sync DNS to Cloudflare (during migration period while domain is locked)
sync_cloudflare_dns() {
    local ZONE_ID="${CLOUDFLARE_ZONE_ID:-8ba92fe5e64b2cfb270462b6d88d2f76}"
    local SITE_DOMAIN="$ENVIRONMENT.kernelworx.app"
    local API_DOMAIN="api.$ENVIRONMENT.kernelworx.app"
    local LOGIN_DOMAIN="login.$ENVIRONMENT.kernelworx.app"
    
    echo ""
    echo "☁️  Syncing DNS to Cloudflare..."
    
    # Get CloudFront distribution domain for site
    local CF_DOMAIN=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?contains(Aliases.Items, \`$SITE_DOMAIN\`)].DomainName | [0]" \
        --output text 2>/dev/null)
    
    if [ -z "$CF_DOMAIN" ] || [ "$CF_DOMAIN" == "None" ]; then
        echo "   ⚠️  No CloudFront distribution found for $SITE_DOMAIN"
    else
        echo "   📍 $SITE_DOMAIN → $CF_DOMAIN"
        upsert_cloudflare_cname "$ZONE_ID" "$SITE_DOMAIN" "$CF_DOMAIN"
    fi
    
    # Get AppSync custom domain's CloudFront domain
    local APPSYNC_CF_DOMAIN=$(aws appsync get-domain-name \
        --domain-name "$API_DOMAIN" \
        --query 'domainNameConfig.appsyncDomainName' \
        --output text 2>/dev/null)
    
    if [ -z "$APPSYNC_CF_DOMAIN" ] || [ "$APPSYNC_CF_DOMAIN" == "None" ]; then
        echo "   ⚠️  No AppSync domain found for $API_DOMAIN"
    else
        echo "   📍 $API_DOMAIN → $APPSYNC_CF_DOMAIN"
        upsert_cloudflare_cname "$ZONE_ID" "$API_DOMAIN" "$APPSYNC_CF_DOMAIN"
    fi
    
    # Get Cognito User Pool Domain's CloudFront domain
    local COGNITO_CF_DOMAIN=$(aws cognito-idp describe-user-pool-domain \
        --domain "$LOGIN_DOMAIN" \
        --query 'DomainDescription.CloudFrontDistribution' \
        --output text 2>/dev/null)
    
    if [ -z "$COGNITO_CF_DOMAIN" ] || [ "$COGNITO_CF_DOMAIN" == "None" ]; then
        echo "   ⚠️  No Cognito domain found for $LOGIN_DOMAIN"
    else
        echo "   📍 $LOGIN_DOMAIN → $COGNITO_CF_DOMAIN"
        upsert_cloudflare_cname "$ZONE_ID" "$LOGIN_DOMAIN" "$COGNITO_CF_DOMAIN"
    fi
    
    echo "   ✅ Cloudflare DNS sync complete"
}

upsert_cloudflare_cname() {
    local ZONE_ID="$1"
    local NAME="$2"
    local CONTENT="$3"
    
    # Check if record already exists
    local EXISTING=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?type=CNAME&name=$NAME" \
        -H "Authorization: Bearer $CLOUDFLARE_TOKEN" \
        -H "Content-Type: application/json")
    
    local RECORD_ID=$(echo "$EXISTING" | grep -o '"id":"[^"]*"' | head -1 | sed 's/"id":"//;s/"//')
    local EXISTING_CONTENT=$(echo "$EXISTING" | grep -o '"content":"[^"]*"' | head -1 | sed 's/"content":"//;s/"//')
    
    if [ -n "$RECORD_ID" ]; then
        # Record exists - check if update needed
        if [ "$EXISTING_CONTENT" == "$CONTENT" ]; then
            echo "      ✓ $NAME already up-to-date"
            return 0
        fi
        
        # Update existing record
        local RESULT=$(curl -s -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$RECORD_ID" \
            -H "Authorization: Bearer $CLOUDFLARE_TOKEN" \
            -H "Content-Type: application/json" \
            --data "{\"type\":\"CNAME\",\"name\":\"$NAME\",\"content\":\"$CONTENT\",\"ttl\":1,\"proxied\":false}")
        
        if echo "$RESULT" | grep -q '"success":true'; then
            echo "      ✓ Updated $NAME"
        else
            echo "      ⚠️  Failed to update $NAME: $RESULT"
        fi
    else
        # Create new record
        local RESULT=$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
            -H "Authorization: Bearer $CLOUDFLARE_TOKEN" \
            -H "Content-Type: application/json" \
            --data "{\"type\":\"CNAME\",\"name\":\"$NAME\",\"content\":\"$CONTENT\",\"ttl\":1,\"proxied\":false}")
        
        if echo "$RESULT" | grep -q '"success":true'; then
            echo "      ✓ Created $NAME"
        else
            echo "      ⚠️  Failed to create $NAME: $RESULT"
        fi
    fi
}

# Only sync if CLOUDFLARE_TOKEN is set
if [ -n "$CLOUDFLARE_TOKEN" ]; then
    sync_cloudflare_dns
else
    echo ""
    echo "ℹ️  Skipping Cloudflare sync (set CLOUDFLARE_TOKEN to enable)"
fi
