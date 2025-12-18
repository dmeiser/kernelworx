#!/bin/bash
# Add user to ADMIN group in Cognito User Pool
#
# Usage: ./add-admin.sh <email-or-username>
#
# Example: ./add-admin.sh dmeiser@gmail.com

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <email-or-username>"
  echo "Example: $0 dmeiser@gmail.com"
  exit 1
fi

USER_POOL_ID="us-east-1_G1E0XFifR"
USERNAME="$1"

echo "Adding $USERNAME to ADMIN group in User Pool $USER_POOL_ID..."

# Add user to ADMIN group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --group-name "ADMIN"

echo "✅ Successfully added $USERNAME to ADMIN group"
echo ""
echo "Note: User must log out and log back in for group membership to take effect"
