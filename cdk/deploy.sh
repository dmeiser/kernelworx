#!/bin/bash
# Deployment script for Popcorn Sales Manager CDK stack
# Minimal configuration - most values are derived automatically

set -e

# Change to script directory
cd "$(dirname "$0")"

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

# Stage 1: Try to import SMS role first (if it exists)
SMS_ROLE_IMPORT=$(uv run python generate_sms_role_import.py 2>/dev/null || echo "")
if [ -n "$SMS_ROLE_IMPORT" ] && [ -f "$SMS_ROLE_IMPORT" ]; then
    echo "📦 Stage 1: Importing SMS role first..."
    echo "Running: npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true --resource-mapping $SMS_ROLE_IMPORT --force"
    echo ""
    
    npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true --resource-mapping "$SMS_ROLE_IMPORT" --force
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
    echo "Running: npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true --resource-mapping $IMPORT_FILE --force"
    echo ""
    
    # Run import operation with mapping file, skipping UserPoolDomain creation
    npx cdk import $CONTEXT_ARGS -c skip_user_pool_domain=true --resource-mapping "$IMPORT_FILE" --force
    IMPORT_EXIT_CODE=$?
    
    if [ $IMPORT_EXIT_CODE -ne 0 ]; then
        echo ""
        echo "❌ Import failed!"
        rm -f "$IMPORT_FILE"
        exit $IMPORT_EXIT_CODE
    fi
    
    echo ""
    echo "✅ Import complete! Now deploying normally..."
    echo ""
    
    # Clean up import file after successful import
    rm -f "$IMPORT_FILE"
    
    # Run normal deployment after import
    # Keep UserPoolDomain skipped until we fix the orphaned domain/certificate issue
    echo "⚠️  Deploying with UserPoolDomain still skipped (to enable: remove orphaned domain and certificates first)"
    npx cdk deploy $CONTEXT_ARGS -c skip_user_pool_domain=true --require-approval never
    exit $?
else
    echo "Running: npx cdk deploy $CONTEXT_ARGS -c skip_user_pool_domain=true --require-approval never"
    echo "⚠️  UserPoolDomain creation skipped (to enable: remove orphaned domain and certificates first)"
    echo ""
    
    npx cdk deploy $CONTEXT_ARGS -c skip_user_pool_domain=true --require-approval never
fi

echo ""
echo "✅ Deployment complete!"
