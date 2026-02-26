#!/bin/bash
# Update integration test environment variables from AWS
set -e

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="kernelworx-ue1-${ENVIRONMENT}"
ENV_FILE="$(dirname "$0")/../.env"

echo "🔍 Fetching Cognito User Pool Client ID from AWS..."
echo "   Stack: $STACK_NAME"
echo "   Region: $REGION"
echo ""

# Get User Pool ID
USER_POOL_ID=$(grep TEST_USER_POOL_ID "$ENV_FILE" | cut -d= -f2)

if [ -z "$USER_POOL_ID" ]; then
    echo "❌ Error: TEST_USER_POOL_ID not found in .env"
    exit 1
fi

echo "   User Pool ID: $USER_POOL_ID"

# Get Cognito App Client ID from User Pool
CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
    --user-pool-id "$USER_POOL_ID" \
    --max-results 10 \
    --query "UserPoolClients[?ClientName=='kernelworx-ue1-${ENVIRONMENT}-web'].ClientId | [0]" \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" == "None" ]; then
    # Fallback: get first web client
    CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
        --user-pool-id "$USER_POOL_ID" \
        --max-results 1 \
        --query "UserPoolClients[0].ClientId" \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
fi

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" == "None" ]; then
    echo "❌ Error: Could not find Cognito App Client for User Pool $USER_POOL_ID"
    exit 1
fi

echo "   Client ID: $CLIENT_ID"
echo ""

# Update .env file
echo "📝 Updating $ENV_FILE..."

# Use sed to update the TEST_USER_POOL_CLIENT_ID line
if grep -q "^TEST_USER_POOL_CLIENT_ID=" "$ENV_FILE"; then
    # Update existing line
    sed -i "s|^TEST_USER_POOL_CLIENT_ID=.*|TEST_USER_POOL_CLIENT_ID=$CLIENT_ID|" "$ENV_FILE"
else
    # Add new line (shouldn't happen if .env was already updated)
    echo "TEST_USER_POOL_CLIENT_ID=$CLIENT_ID" >> "$ENV_FILE"
fi

echo "✅ Integration test environment updated!"
echo ""
echo "You can now run integration tests with:"
echo "   cd tests/integration && npm test"
