#!/bin/bash
# Create ephemeral run-scoped test users in a Cognito User Pool.
#
# Usage:
#   create-ephemeral-test-users.sh <run-id> <user-pool-id>
#
# Emails use the pattern <run-id>-owner@kernelworx.test so they are clearly
# scoped to a single ephemeral run and never collide with dev/prod test users.
# The owner user is added to the ADMIN group, matching the deploy-shared.yml
# smoke-test setup.

set -e

log() {
  echo "$@" >&2
}

if [ $# -lt 2 ]; then
  log "Usage: $0 <run-id> <user-pool-id>"
  exit 1
fi

RUN_ID="$1"
USER_POOL_ID="$2"
REGION="${AWS_REGION:-us-east-1}"
TEST_DOMAIN="${EPHEMERAL_TEST_DOMAIN:-kernelworx.test}"

OWNER_EMAIL="${RUN_ID}-owner@${TEST_DOMAIN}"
CONTRIBUTOR_EMAIL="${RUN_ID}-contributor@${TEST_DOMAIN}"
READONLY_EMAIL="${RUN_ID}-readonly@${TEST_DOMAIN}"

# Generate a password satisfying Cognito's policy:
# minimum 8, lowercase, uppercase, number, symbol.
generate_password() {
  local prefix
  prefix=$(openssl rand -base64 9 | tr -d '=+/')
  echo "${prefix}A1!"
}

OWNER_PASSWORD=$(generate_password)
CONTRIBUTOR_PASSWORD=$(generate_password)
READONLY_PASSWORD=$(generate_password)

log "Creating ephemeral test users in pool: $USER_POOL_ID"
log "  Region: $REGION"
log ""

create_or_update_user() {
  local user_type=$1
  local email=$2
  local password=$3

  log "Setting up $user_type user: $email"

  aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$email" \
    --message-action SUPPRESS \
    --temporary-password "$password" \
    --region "$REGION" \
    2>/dev/null || log "  (User may already exist)"

  aws cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$email" \
    --password "$password" \
    --permanent \
    --region "$REGION" \
    2>/dev/null || log "  (Could not set password)"

  aws cognito-idp admin-update-user-attributes \
    --user-pool-id "$USER_POOL_ID" \
    --username "$email" \
    --user-attributes Name=email_verified,Value=true \
    --region "$REGION" \
    2>/dev/null || true

  log "  ✓ $user_type user ready"
}

create_or_update_user "Owner" "$OWNER_EMAIL" "$OWNER_PASSWORD"
create_or_update_user "Contributor" "$CONTRIBUTOR_EMAIL" "$CONTRIBUTOR_PASSWORD"
create_or_update_user "Read-only" "$READONLY_EMAIL" "$READONLY_PASSWORD"

# The owner must be in the ADMIN group for admin-only smoke tests to pass.
log ""
log "Ensuring ADMIN group exists..."
aws cognito-idp create-group \
  --user-pool-id "$USER_POOL_ID" \
  --group-name ADMIN \
  --region "$REGION" \
  2>/dev/null || log "  (ADMIN group may already exist)"

log "Adding owner to ADMIN group..."
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username "$OWNER_EMAIL" \
  --group-name ADMIN \
  --region "$REGION" \
  2>/dev/null || log "  (Group membership may already exist)"

log ""
echo "export TEST_OWNER_EMAIL=$OWNER_EMAIL"
echo "export TEST_OWNER_PASSWORD=$OWNER_PASSWORD"
echo "export TEST_CONTRIBUTOR_EMAIL=$CONTRIBUTOR_EMAIL"
echo "export TEST_CONTRIBUTOR_PASSWORD=$CONTRIBUTOR_PASSWORD"
echo "export TEST_READONLY_EMAIL=$READONLY_EMAIL"
echo "export TEST_READONLY_PASSWORD=$READONLY_PASSWORD"
