#!/bin/bash

# Create test users in Cognito for integration tests
# Uses credentials from .env file
#
# Also provisions (or re-provisions) a TOTP device for the owner user: the
# #336 admin gate requires the amr 'mfa' claim, so the owner admin needs MFA.
# The fresh TOTP secret is written to .env as TEST_OWNER_TOTP_SECRET.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "Error: .env file not found"
  exit 1
fi

# Validate required environment variables
if [ -z "$TEST_USER_POOL_ID" ] || [ -z "$TEST_USER_POOL_CLIENT_ID" ] || [ -z "$TEST_OWNER_EMAIL" ] || [ -z "$TEST_OWNER_PASSWORD" ]; then
  echo "Error: Required environment variables not set in .env"
  echo "Required: TEST_USER_POOL_ID, TEST_USER_POOL_CLIENT_ID, TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD, etc."
  exit 1
fi

echo "Creating test users in Cognito User Pool: $TEST_USER_POOL_ID"
echo "Region: $TEST_REGION"
echo ""

# Function to create or update a user
create_or_update_user() {
  local user_type=$1
  local email=$2
  local password=$3
  
  echo "Setting up $user_type user: $email"
  
  # Admin create user (initial setup)
  aws cognito-idp admin-create-user \
    --user-pool-id "$TEST_USER_POOL_ID" \
    --username "$email" \
    --message-action SUPPRESS \
    --temporary-password "$password" \
    --region "$TEST_REGION" \
    2>/dev/null || echo "  (User may already exist)"
  
  # Set permanent password
  aws cognito-idp admin-set-user-password \
    --user-pool-id "$TEST_USER_POOL_ID" \
    --username "$email" \
    --password "$password" \
    --permanent \
    --region "$TEST_REGION" \
    2>/dev/null || echo "  (Could not set password, user may have issues)"
  
  # Mark email as verified
  aws cognito-idp admin-update-user-attributes \
    --user-pool-id "$TEST_USER_POOL_ID" \
    --username "$email" \
    --user-attributes Name=email_verified,Value=true \
    --region "$TEST_REGION" \
    2>/dev/null || true
  
  echo "  ✓ $user_type user created/updated"
}

# Create the three test users
create_or_update_user "Owner" "$TEST_OWNER_EMAIL" "$TEST_OWNER_PASSWORD"
create_or_update_user "Contributor" "$TEST_CONTRIBUTOR_EMAIL" "$TEST_CONTRIBUTOR_PASSWORD"
create_or_update_user "Read-only" "$TEST_READONLY_EMAIL" "$TEST_READONLY_PASSWORD"

echo ""
echo "🔐 Provisioning TOTP MFA for the owner admin user (#336)..."
OWNER_TOTP_SECRET=$("$SCRIPT_DIR/provision-user-totp.sh" \
  "$TEST_USER_POOL_ID" "$TEST_USER_POOL_CLIENT_ID" "$TEST_OWNER_EMAIL" "$TEST_OWNER_PASSWORD")

# Persist the fresh secret in .env so integration and e2e test harnesses can
# answer the owner's SOFTWARE_TOKEN_MFA challenge.
if grep -q '^TEST_OWNER_TOTP_SECRET=' .env; then
  sed -i.bak "s|^TEST_OWNER_TOTP_SECRET=.*|TEST_OWNER_TOTP_SECRET=$OWNER_TOTP_SECRET|" .env
  rm -f .env.bak
else
  printf '\n# TOTP secret for the owner admin test user (provisioned by this script, #336)\nTEST_OWNER_TOTP_SECRET=%s\n' "$OWNER_TOTP_SECRET" >> .env
fi

echo ""
echo "✅ Test users created successfully!"
echo ""
echo "Credentials:"
echo "  Owner:       $TEST_OWNER_EMAIL / $TEST_OWNER_PASSWORD"
echo "  Contributor: $TEST_CONTRIBUTOR_EMAIL / $TEST_CONTRIBUTOR_PASSWORD"
echo "  Read-only:   $TEST_READONLY_EMAIL / $TEST_READONLY_PASSWORD"
echo ""
echo "Integration tests can now be run with: npm run test"
