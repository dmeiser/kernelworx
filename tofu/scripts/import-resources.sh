#!/bin/bash
# Import existing AWS resources into OpenTofu state
set -e

ENV="${1:-dev}"
REGION="us-east-1"
REGION_ABBREV="ue1"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_DIR="$SCRIPT_DIR/../environments/$ENV"

# Load environment variables
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

export TF_VAR_encryption_passphrase="${ENCRYPTION_PASSPHRASE:-}"
export TF_VAR_google_client_id="${GOOGLE_CLIENT_ID:-}"
export TF_VAR_google_client_secret="${GOOGLE_CLIENT_SECRET:-}"

if [ -z "$TF_VAR_encryption_passphrase" ]; then
    echo "❌ ENCRYPTION_PASSPHRASE not set"
    exit 1
fi

cd "$ENV_DIR"

echo "🔄 Importing existing resources for $ENV environment..."
echo ""

# Helper function to import a resource
import_resource() {
    local address="$1"
    local id="$2"
    
    echo "  📥 Importing: $address"
    if tofu import "$address" "$id" 2>/dev/null; then
        echo "     ✅ Success"
    else
        echo "     ⚠️  Already imported or not found"
    fi
}

# DynamoDB Tables
echo ""
echo "📦 Importing DynamoDB tables..."
import_resource 'module.dynamodb.aws_dynamodb_table.accounts' "kernelworx-accounts-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.catalogs' "kernelworx-catalogs-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.profiles' "kernelworx-profiles-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.campaigns' "kernelworx-campaigns-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.orders' "kernelworx-orders-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.shares' "kernelworx-shares-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.invites' "kernelworx-invites-${REGION_ABBREV}-${ENV}"
import_resource 'module.dynamodb.aws_dynamodb_table.shared_campaigns' "kernelworx-shared-campaigns-${REGION_ABBREV}-${ENV}"

# S3 Buckets
echo ""
echo "📦 Importing S3 buckets..."
import_resource 'module.s3.aws_s3_bucket.static' "kernelworx-static-${REGION_ABBREV}-${ENV}"
import_resource 'module.s3.aws_s3_bucket.exports' "kernelworx-exports-${REGION_ABBREV}-${ENV}"

# IAM Roles
echo ""
echo "📦 Importing IAM roles..."
import_resource 'module.iam.aws_iam_role.lambda_execution' "kernelworx-lambda-exec-${REGION_ABBREV}-${ENV}"
import_resource 'module.iam.aws_iam_role.appsync_service' "kernelworx-appsync-${REGION_ABBREV}-${ENV}"
import_resource 'module.iam.aws_iam_role.cognito_sms' "kernelworx-${REGION_ABBREV}-${ENV}-UserPoolsmsRole"

# ACM Certificates
echo ""
echo "📦 Importing ACM certificates..."
SITE_CERT_ARN=$(aws acm list-certificates --region $REGION --query "CertificateSummaryList[?DomainName=='${ENV}.kernelworx.app'].CertificateArn" --output text)
API_CERT_ARN=$(aws acm list-certificates --region $REGION --query "CertificateSummaryList[?DomainName=='api.${ENV}.kernelworx.app'].CertificateArn" --output text)
LOGIN_CERT_ARN=$(aws acm list-certificates --region $REGION --query "CertificateSummaryList[?DomainName=='login.${ENV}.kernelworx.app'].CertificateArn" --output text)

if [ -n "$SITE_CERT_ARN" ]; then
    import_resource 'module.certificates.aws_acm_certificate.site' "$SITE_CERT_ARN"
fi
if [ -n "$API_CERT_ARN" ]; then
    import_resource 'module.certificates.aws_acm_certificate.api' "$API_CERT_ARN"
fi
if [ -n "$LOGIN_CERT_ARN" ]; then
    import_resource 'module.certificates.aws_acm_certificate.login' "$LOGIN_CERT_ARN"
fi

# Cognito
echo ""
echo "📦 Importing Cognito resources..."
USER_POOL_ID="us-east-1_sDiuCOarb"
CLIENT_ID="2atbkksvd3ited0fsqrr8nbgcb"

import_resource 'module.cognito.aws_cognito_user_pool.main' "$USER_POOL_ID"
import_resource 'module.cognito.aws_cognito_user_pool_client.web' "${USER_POOL_ID}/${CLIENT_ID}"
import_resource 'module.cognito.aws_cognito_identity_provider.google' "${USER_POOL_ID}/Google"
import_resource 'module.cognito.aws_cognito_user_pool_domain.custom' "login.${ENV}.kernelworx.app"

# Lambda Functions
echo ""
echo "📦 Importing Lambda functions..."
LAMBDA_FUNCTIONS=(
    "list-my-shares"
    "list-catalogs-in-use"
    "create-profile"
    "request-report"
    "unit-reporting"
    "list-unit-catalogs"
    "list-unit-campaign-catalogs"
    "campaign-operations"
    "delete-profile-orders-cascade"
    "update-account"
    "delete-account"
    "transfer-ownership"
    "post-auth"
    "pre-signup"
    "request-qr-upload"
    "confirm-qr-upload"
    "generate-qr-code-presigned-url"
    "delete-qr-code"
    "validate-payment-method"
    "admin-operations"
)

for fn in "${LAMBDA_FUNCTIONS[@]}"; do
    FUNC_NAME="kernelworx-${fn}-${REGION_ABBREV}-${ENV}"
    import_resource "module.lambda.aws_lambda_function.functions[\"${fn}\"]" "$FUNC_NAME"
done

# Lambda Layer
echo ""
echo "📦 Importing Lambda layer..."
LAYER_ARN=$(aws lambda list-layer-versions --layer-name "kernelworx-deps-${REGION_ABBREV}-${ENV}" --region $REGION --query "LayerVersions[0].LayerVersionArn" --output text 2>/dev/null || echo "")
if [ -n "$LAYER_ARN" ] && [ "$LAYER_ARN" != "None" ]; then
    import_resource 'module.lambda.aws_lambda_layer_version.shared' "$LAYER_ARN"
fi

# AppSync
echo ""
echo "📦 Importing AppSync resources..."
APPSYNC_API_ID=$(aws appsync list-graphql-apis --region $REGION --query "graphqlApis[?name=='kernelworx-api-${REGION_ABBREV}-${ENV}'].apiId" --output text)
if [ -n "$APPSYNC_API_ID" ]; then
    import_resource 'module.appsync.aws_appsync_graphql_api.main' "$APPSYNC_API_ID"
    import_resource 'module.appsync.aws_appsync_domain_name.api' "api.${ENV}.kernelworx.app"
    import_resource 'module.appsync.aws_appsync_domain_name_api_association.api' "$APPSYNC_API_ID/api.${ENV}.kernelworx.app"
fi

# CloudFront
echo ""
echo "📦 Importing CloudFront resources..."
CF_DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Aliases.Items, '${ENV}.kernelworx.app')].Id" --output text)
if [ -n "$CF_DIST_ID" ]; then
    import_resource 'module.cloudfront.aws_cloudfront_distribution.site' "$CF_DIST_ID"
fi

# CloudFront OAI
OAI_ID=$(aws cloudfront list-cloud-front-origin-access-identities --query "CloudFrontOriginAccessIdentityList.Items[?contains(Comment, '${ENV}')].Id" --output text | head -1)
if [ -n "$OAI_ID" ]; then
    import_resource 'module.cloudfront.aws_cloudfront_origin_access_identity.main' "$OAI_ID"
fi

echo ""
echo "✅ Import complete!"
echo ""
echo "⚠️  Run 'tofu plan' to verify state matches actual resources."
echo "   Resolve any drift before applying changes."
