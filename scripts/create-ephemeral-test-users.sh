#!/bin/bash
# Create ephemeral run-scoped test users in a Cognito User Pool.
#
# Usage:
#   create-ephemeral-test-users.sh <run-id> <user-pool-id> <client-id>
#
# Emails use the pattern <run-id>-owner@kernelworx.test so they are clearly
# scoped to a single ephemeral run and never collide with dev/prod test users.
# A dedicated smoke user (<run-id>-smoke@kernelworx.test) is pre-created and
# confirmed so smoke suites can run without burning Cognito's daily email quota (#483).
# The owner user is added to the ADMIN group, matching the deploy-shared.yml
# smoke-test setup. The owner also gets a TOTP device (re-provisioned on every
# run) because the #336 admin gate requires the amr 'mfa' claim; the secret is
# exported as TEST_OWNER_TOTP_SECRET for the test harnesses.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  echo "$@" >&2
}

if [ $# -lt 3 ]; then
  log "Usage: $0 <run-id> <user-pool-id> <client-id>"
  exit 1
fi

RUN_ID="$1"
USER_POOL_ID="$2"
CLIENT_ID="$3"

# The run-id is caller-supplied (it comes from the pr_number workflow inputs)
# and is interpolated into the test-user emails, so reject anything outside
# [A-Za-z0-9._-] before the first Cognito call. #568 (PR #584) owns the rule;
# this script reuses its shared validate_run_id helper rather than repeating it.
# shellcheck source=/dev/null
source "$(cd "$(dirname "$0")" && pwd)/ephemeral-recover-common.sh"

validate_run_id "$RUN_ID" || exit 1

REGION="${AWS_REGION:-us-east-1}"
TEST_DOMAIN="${EPHEMERAL_TEST_DOMAIN:-kernelworx.test}"

OWNER_EMAIL="${RUN_ID}-owner@${TEST_DOMAIN}"
CONTRIBUTOR_EMAIL="${RUN_ID}-contributor@${TEST_DOMAIN}"
READONLY_EMAIL="${RUN_ID}-readonly@${TEST_DOMAIN}"
SMOKE_EMAIL="${RUN_ID}-smoke@${TEST_DOMAIN}"

# Generate a password satisfying Cognito's policy:
# minimum 15, lowercase, uppercase, number, symbol.
#
# Each required character class is guaranteed BY CONSTRUCTION, not by the
# randomness of the prefix: hex output is [0-9a-f], so a prefix alone can never
# provide an uppercase letter or symbol, and the fixed suffix "Aa1!" supplies
# lowercase, uppercase, digit and symbol unconditionally. This matters because
# the password is generated once and then retried as-is: if the generator could
# emit a policy-rejected password (e.g. a base64 prefix whose surviving
# characters were all non-lowercase with suffix "A1!"), every attempt would
# fail with the same invalid password.
generate_password() {
  local prefix
  prefix=$(openssl rand -hex 9)
  echo "${prefix}Aa1!"
}

# Cognito error codes this script branches on. Both appear in the aws CLI's
# stderr as "(<Code>) when calling the <Operation> operation: <message>".
USERNAME_EXISTS_EXCEPTION="UsernameExistsException"
USER_NOT_FOUND_EXCEPTION="UserNotFoundException"

# The TEST_*_PASSWORD values this script exports are the credentials the
# integration and e2e suites sign in with, so a password Cognito did not accept
# must never be exported: the suites would keep presenting a password that does
# not work until Cognito's failed-attempt backoff ("Password attempts exceeded")
# locks the user out, and the run then fails on a misleading auth error far from
# the real cause. The admin control plane fails transiently (throttling,
# propagation), so retry the assignment briefly and abort the run if it still
# has not taken effect.
PASSWORD_SET_ATTEMPTS=5
PASSWORD_SET_BACKOFF_SECONDS=2

set_user_password() {
  local email=$1
  local password=$2
  local attempt=1
  local error=""
  while [ "$attempt" -le "$PASSWORD_SET_ATTEMPTS" ]; do
    error=$(aws cognito-idp admin-set-user-password \
      --user-pool-id "$USER_POOL_ID" \
      --username "$email" \
      --password "$password" \
      --permanent \
      --region "$REGION" 2>&1) && return 0
    # A missing user is not a transient condition: no number of retries can
    # make the password call succeed, and the caller never created the user.
    # Say so once and stop instead of repeating the same doomed call.
    case "$error" in
      *"An error occurred ($USER_NOT_FOUND_EXCEPTION) when calling the "*)
        log "ERROR: Cognito has no user $email ($USER_NOT_FOUND_EXCEPTION), so its password cannot be set."
        log "  The user creation above did not take effect; this is not a retryable failure."
        return 1
        ;;
    esac
    log "  (Attempt $attempt/$PASSWORD_SET_ATTEMPTS could not set the password for $email: $error)"
    attempt=$((attempt + 1))
    sleep "$PASSWORD_SET_BACKOFF_SECONDS"
  done
  log "Refusing to export test credentials: the password for $email was never set."
  if [ -n "$error" ]; then
    log "  Last Cognito error: $error"
  fi
  return 1
}

OWNER_PASSWORD=$(generate_password)
CONTRIBUTOR_PASSWORD=$(generate_password)
READONLY_PASSWORD=$(generate_password)
SMOKE_PASSWORD=$(generate_password)

log "Creating ephemeral test users in pool: $USER_POOL_ID"
log "  Region: $REGION"
log ""

create_or_update_user() {
  local user_type=$1
  local email=$2
  local password=$3

  log "Setting up $user_type user: $email"

  # Only UsernameExistsException means "the user is already there". Any other
  # failure (a quota, a malformed attribute, a network error) previously fell
  # into the same "may already exist" message, so the run carried on and the
  # password step then failed against a user that was never created, hiding the
  # real cause. Surface it and abort instead.
  local create_error=""
  if ! create_error=$(aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$email" \
    --message-action SUPPRESS \
    --temporary-password "$password" \
    --region "$REGION" 2>&1); then
    case "$create_error" in
      *"An error occurred ($USERNAME_EXISTS_EXCEPTION) when calling the "*)
        log "  (User already exists; continuing with the existing account)"
        ;;
      *)
        log "ERROR: could not create the $user_type user $email. Cognito said:"
        log "  $create_error"
        log "  This is not an 'already exists' condition, so the run cannot continue."
        exit 1
        ;;
    esac
  fi

  set_user_password "$email" "$password"

  aws cognito-idp admin-update-user-attributes \
    --user-pool-id "$USER_POOL_ID" \
    --username "$email" \
    --user-attributes Name=email_verified,Value=true \
    --region "$REGION" \
    >/dev/null 2>&1 || true

  log "  ✓ $user_type user ready"
}

create_or_update_user "Owner" "$OWNER_EMAIL" "$OWNER_PASSWORD"
create_or_update_user "Contributor" "$CONTRIBUTOR_EMAIL" "$CONTRIBUTOR_PASSWORD"
create_or_update_user "Read-only" "$READONLY_EMAIL" "$READONLY_PASSWORD"
create_or_update_user "Smoke" "$SMOKE_EMAIL" "$SMOKE_PASSWORD"

# The owner must be in the ADMIN group for admin-only smoke tests to pass.
log ""
log "Ensuring ADMIN group exists..."
aws cognito-idp create-group \
  --user-pool-id "$USER_POOL_ID" \
  --group-name ADMIN \
  --region "$REGION" \
  >/dev/null 2>&1 || log "  (ADMIN group may already exist)"

log "Adding owner to ADMIN group..."
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username "$OWNER_EMAIL" \
  --group-name ADMIN \
  --region "$REGION" \
  >/dev/null 2>&1 || log "  (Group membership may already exist)"

log ""
log "🔐 Provisioning TOTP MFA for the owner admin user (#336)..."
# The password is passed through the environment, not argv: process argv is
# world-readable via /proc/<pid>/cmdline and shows up in `ps` (#569).
OWNER_TOTP_SECRET=$(PROVISION_USER_TOTP_PASSWORD="$OWNER_PASSWORD" \
  "$SCRIPT_DIR/provision-user-totp.sh" \
  "$USER_POOL_ID" "$CLIENT_ID" "$OWNER_EMAIL")

log ""
echo "export TEST_OWNER_EMAIL=$OWNER_EMAIL"
echo "export TEST_OWNER_PASSWORD=$OWNER_PASSWORD"
echo "export TEST_OWNER_TOTP_SECRET=$OWNER_TOTP_SECRET"
echo "export TEST_CONTRIBUTOR_EMAIL=$CONTRIBUTOR_EMAIL"
echo "export TEST_CONTRIBUTOR_PASSWORD=$CONTRIBUTOR_PASSWORD"
echo "export TEST_READONLY_EMAIL=$READONLY_EMAIL"
echo "export TEST_READONLY_PASSWORD=$READONLY_PASSWORD"
echo "export TEST_SMOKE_EMAIL=$SMOKE_EMAIL"
echo "export TEST_SMOKE_PASSWORD=$SMOKE_PASSWORD"
