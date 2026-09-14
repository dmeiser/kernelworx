#!/bin/bash
# Provision (or re-provision) a Cognito TOTP device for a user and print the
# base32 TOTP secret on stdout.
#
# Usage:
#   provision-user-totp.sh <user-pool-id> <client-id> <username> <password>
#
# The #336 admin gate requires the JWT amr claim to contain "mfa", so every
# user that exercises admin-gated API paths in tests (the owner test user)
# needs a TOTP device. Re-provisioning always issues a fresh secret: an
# existing SOFTWARE_TOKEN_MFA device is disabled first, because a previously
# issued secret cannot be recovered from Cognito. Callers that need a stable
# secret across runs must persist the printed value themselves (e.g. in .env
# or as a CI environment export).
#
# After verifying the new device, this script waits (up to 30 seconds) for
# the current 30-second TOTP window to roll over: verify-software-token
# consumes the code for that window, and Cognito rejects a second submission
# of the same code within the same window (ExpiredCodeException). Without the
# wait, the first browser login right after provisioning would resubmit the
# same code and fail its MFA step.
#
# Requires: aws CLI, python3 (stdlib only), and IAM permissions for
# cognito-idp associate-software-token / verify-software-token /
# admin-set-user-mfa-preference / admin-get-user. The access token comes
# from the non-admin initiate-auth USER_PASSWORD_AUTH flow, so the pool
# client must allow USER_PASSWORD_AUTH (no admin auth flow is required).

set -e

log() {
  echo "$@" >&2
}

if [ $# -lt 4 ]; then
  log "Usage: $0 <user-pool-id> <client-id> <username> <password>"
  exit 1
fi

USER_POOL_ID="$1"
CLIENT_ID="$2"
USERNAME="$3"
PASSWORD="$4"
REGION="${AWS_REGION:-us-east-1}"

log "Provisioning TOTP device for: $USERNAME"

# A device from an earlier provisioning cannot be re-read (Cognito never
# returns the secret again), so disable it and issue a fresh one.
if aws cognito-idp admin-get-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --region "$REGION" \
  --query 'UserMFASettingList' --output text 2>/dev/null | grep -q "SOFTWARE_TOKEN_MFA"; then
  log "  (Replacing existing TOTP device)"
  aws cognito-idp admin-set-user-mfa-preference \
    --user-pool-id "$USER_POOL_ID" \
    --username "$USERNAME" \
    --software-token-mfa-settings Enabled=false \
    --region "$REGION" >/dev/null
fi

ACCESS_TOKEN=$(aws cognito-idp initiate-auth \
  --client-id "$CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=${USERNAME},PASSWORD=${PASSWORD}" \
  --region "$REGION" \
  --query 'AuthenticationResult.AccessToken' --output text 2>/dev/null) || \
ACCESS_TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_NO_SRP_AUTH \
  --auth-parameters "USERNAME=${USERNAME},PASSWORD=${PASSWORD}" \
  --region "$REGION" \
  --query 'AuthenticationResult.AccessToken' --output text)

TOTP_SECRET=$(aws cognito-idp associate-software-token \
  --access-token "$ACCESS_TOKEN" \
  --region "$REGION" \
  --query 'SecretCode' --output text)

TOTP_CODE=$(TOTP_SECRET="$TOTP_SECRET" python3 - <<'PY'
import base64, hashlib, hmac, os, struct, time
# Cognito issues the secret unpadded; b32decode requires RFC 4648 padding.
secret = os.environ["TOTP_SECRET"].upper()
secret += "=" * (-len(secret) % 8)
key = base64.b32decode(secret)
counter = int(time.time() // 30)
digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
offset = digest[-1] & 0x0F
print(f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}")
PY
)

aws cognito-idp verify-software-token \
  --access-token "$ACCESS_TOKEN" \
  --user-code "$TOTP_CODE" \
  --region "$REGION" >/dev/null

# The verify-software-token call above consumed the TOTP code for the current
# 30-second window. Cognito rejects a second submission of the same code
# within that window (ExpiredCodeException), which would break the first
# browser login run right after provisioning (e.g. the first owner sign-in of
# the dev smoke suite). Wait for the window to roll over so every later code
# generated from this secret is a fresh one.
NOW=$(date +%s)
WAIT=$((30 - NOW % 30))
log "  (waiting ${WAIT}s for the next TOTP window)"
sleep "$WAIT"

aws cognito-idp admin-set-user-mfa-preference \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --software-token-mfa-settings Enabled=true,PreferredMfa=true \
  --region "$REGION" >/dev/null

log "  ✓ TOTP device provisioned"
echo "$TOTP_SECRET"
