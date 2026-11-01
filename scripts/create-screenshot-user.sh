#!/bin/bash

# Create the Alex Kernel screenshot/marketing user in Cognito.
# Idempotent: safe to re-run if the user already exists.

set -e

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
if [ -z "$TEST_USER_POOL_ID" ] || [ -z "$TEST_REGION" ] || [ -z "$TEST_ALEX_EMAIL" ] || [ -z "$TEST_ALEX_PASSWORD" ]; then
  echo "Error: Required environment variables not set in .env"
  echo "Required: TEST_USER_POOL_ID, TEST_REGION, TEST_ALEX_EMAIL, TEST_ALEX_PASSWORD"
  exit 1
fi

# Credentials must never sit on a command line: a running process's argv is
# world-readable on Linux via /proc/<pid>/cmdline and shows up in `ps`, so any
# co-tenant on the machine could read the password there (#710). The password
# rides in a private mktemp file passed with --cli-input-json file://..., the
# same shape as scripts/provision-user-totp.sh (#569/#597), and the EXIT trap
# removes the file on every exit path.
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

echo "Creating screenshot user in Cognito User Pool: $TEST_USER_POOL_ID"
echo "Region: $TEST_REGION"
echo ""
echo "Setting up screenshot user: $TEST_ALEX_EMAIL (Alex Kernel)"

# Admin create user (initial setup)
write_password_params TemporaryPassword "$TEST_ALEX_PASSWORD"
aws cognito-idp admin-create-user \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --message-action SUPPRESS \
  --cli-input-json "file://$CRED_PARAMS_FILE" \
  --user-attributes \
    Name=email,Value="$TEST_ALEX_EMAIL" \
    Name=given_name,Value="Alex" \
    Name=family_name,Value="Kernel" \
    Name=name,Value="Alex Kernel" \
  --region "$TEST_REGION" \
  2>/dev/null || echo "  (User may already exist)"

# Set permanent password
write_password_params Password "$TEST_ALEX_PASSWORD"
aws cognito-idp admin-set-user-password \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --permanent \
  --cli-input-json "file://$CRED_PARAMS_FILE" \
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
echo "  Email: $TEST_ALEX_EMAIL"
echo "  Password: in .env as TEST_ALEX_PASSWORD (not printed, #710)"
echo ""
echo "First login will create the DynamoDB Account record via the post-authentication trigger."
