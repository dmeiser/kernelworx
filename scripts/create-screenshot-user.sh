#!/bin/bash

# Create the Alex Kernel screenshot/marketing user in Cognito.
# Idempotent: safe to re-run if the user already exists.

set -e

# Load environment variables from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "Error: .env file not found"
  exit 1
fi

# Validate required environment variables
if [ -z "$TEST_USER_POOL_ID" ] || [ -z "$TEST_REGION" ] || [ -z "$TEST_ALEX_EMAIL" ] || [ -z "$TEST_ALEX_PASSWORD" ]; then
  echo "Error: Required environment variables not set in .env"
  echo "Required: TEST_USER_POOL_ID, TEST_REGION, TEST_ALEX_EMAIL, TEST_ALEX_PASSWORD"
  exit 1
fi

echo "Creating screenshot user in Cognito User Pool: $TEST_USER_POOL_ID"
echo "Region: $TEST_REGION"
echo ""
echo "Setting up screenshot user: $TEST_ALEX_EMAIL (Alex Kernel)"

# Admin create user (initial setup)
aws cognito-idp admin-create-user \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --message-action SUPPRESS \
  --temporary-password "$TEST_ALEX_PASSWORD" \
  --user-attributes \
    Name=email,Value="$TEST_ALEX_EMAIL" \
    Name=given_name,Value="Alex" \
    Name=family_name,Value="Kernel" \
    Name=name,Value="Alex Kernel" \
  --region "$TEST_REGION" \
  2>/dev/null || echo "  (User may already exist)"

# Set permanent password
aws cognito-idp admin-set-user-password \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --password "$TEST_ALEX_PASSWORD" \
  --permanent \
  --region "$TEST_REGION" \
  2>/dev/null || echo "  (Could not set password, user may have issues)"

# Mark email as verified
aws cognito-idp admin-update-user-attributes \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --user-attributes Name=email_verified,Value=true \
  --region "$TEST_REGION" \
  2>/dev/null || true

echo "  ✓ Screenshot user created/updated"
echo ""
echo "✅ Alex Kernel user is ready!"
echo "  Email:    $TEST_ALEX_EMAIL"
echo "  Password: $TEST_ALEX_PASSWORD"
echo ""
echo "First login will create the DynamoDB Account record via the post-authentication trigger."
