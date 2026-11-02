#!/bin/bash

# Create test users in Cognito for integration tests
# Uses credentials from .env file
#
# Also provisions (or re-provisions) a TOTP device for the owner user: the
# #336 admin gate requires the amr 'mfa' claim, so the owner admin needs MFA.
# The fresh TOTP secret is written to .env as TEST_OWNER_TOTP_SECRET.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env (same set -a/source pattern as
# scripts/ephemeral-env.sh; the old `export $(grep ... | xargs)` split values on
# whitespace and mangled quoted values).
if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  source "./.env"
  set +a
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

# Credentials must never sit on a command line: a running process's argv is
# world-readable on Linux via /proc/<pid>/cmdline and shows up in `ps` for as
# long as the process lives, so any co-tenant on the machine could read the
# password there (#710). Every Cognito call that carries a password reads it
# from a private mktemp file passed with --cli-input-json file://..., matching
# scripts/provision-user-totp.sh (#569/#597). The file is removed on every exit
# path by the EXIT trap, so a failed run cannot leave a credential on disk.
CRED_PARAMS_FILE=$(mktemp)
chmod 600 "$CRED_PARAMS_FILE"
trap 'rm -f "$CRED_PARAMS_FILE"' EXIT

# Rewrite the parameter file for each credential-carrying call: $1 is the
# Cognito input member holding the secret (TemporaryPassword or Password).
# Built with python3 so a password containing JSON metacharacters is escaped,
# and the value travels through the environment rather than this argv.
write_password_params() {
  local key=$1
  local password=$2
  KW_PARAM_KEY="$key" KW_PARAM_PASSWORD="$password" python3 - "$CRED_PARAMS_FILE" <<'PY'
import json, os, sys

with open(sys.argv[1], "w") as handle:
    json.dump({os.environ["KW_PARAM_KEY"]: os.environ["KW_PARAM_PASSWORD"]}, handle)
PY
}

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
  write_password_params TemporaryPassword "$password"
  aws cognito-idp admin-create-user \
    --user-pool-id "$TEST_USER_POOL_ID" \
    --username "$email" \
    --message-action SUPPRESS \
    --cli-input-json "file://$CRED_PARAMS_FILE" \
    --region "$TEST_REGION" \
    2>/dev/null || echo "  (User may already exist)"
  
  # Set permanent password
  write_password_params Password "$password"
  aws cognito-idp admin-set-user-password \
    --user-pool-id "$TEST_USER_POOL_ID" \
    --username "$email" \
    --permanent \
    --cli-input-json "file://$CRED_PARAMS_FILE" \
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

# Create test users
create_or_update_user "Owner" "$TEST_OWNER_EMAIL" "$TEST_OWNER_PASSWORD"
create_or_update_user "Contributor" "$TEST_CONTRIBUTOR_EMAIL" "$TEST_CONTRIBUTOR_PASSWORD"
create_or_update_user "Read-only" "$TEST_READONLY_EMAIL" "$TEST_READONLY_PASSWORD"
if [ -n "$TEST_SMOKE_EMAIL" ] && [ -n "$TEST_SMOKE_PASSWORD" ]; then
  create_or_update_user "Smoke" "$TEST_SMOKE_EMAIL" "$TEST_SMOKE_PASSWORD"
fi

echo ""
echo "🔐 Provisioning TOTP MFA for the owner admin user (#336)..."
# The password is passed through the environment, not argv: process argv is
# world-readable via /proc/<pid>/cmdline and shows up in `ps` (#569).
OWNER_TOTP_SECRET=$(PROVISION_USER_TOTP_PASSWORD="$TEST_OWNER_PASSWORD" \
  "$SCRIPT_DIR/provision-user-totp.sh" \
  "$TEST_USER_POOL_ID" "$TEST_USER_POOL_CLIENT_ID" "$TEST_OWNER_EMAIL")

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
# Usernames only: the passwords already live in .env (this script loaded them
# from there), so printing them here added nothing but terminal scrollback and
# log exposure (#710).
echo "Test users (passwords are in .env and are not printed):"
echo "  Owner:       $TEST_OWNER_EMAIL"
echo "  Contributor: $TEST_CONTRIBUTOR_EMAIL"
echo "  Read-only:   $TEST_READONLY_EMAIL"
if [ -n "$TEST_SMOKE_EMAIL" ]; then
  echo "  Smoke:       $TEST_SMOKE_EMAIL"
fi
echo ""
echo "Integration tests can now be run with: npm run test"
