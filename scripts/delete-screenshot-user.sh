#!/bin/bash

# Delete the Alex Kernel screenshot/marketing Cognito user.
#
# IMPORTANT: This removes the Cognito user only. The DynamoDB Account record,
# seller profiles, campaigns, orders, payment methods, and shares created for
# screenshots are intentionally preserved by default so screenshots can be
# re-captured later.
#
# To remove ALL Alex Kernel data as well, log in to the app as Alex and use
# Account Settings -> Delete Account, or use the admin delete-user mutation
# (requires an admin account).

set -e

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "Error: .env file not found"
  exit 1
fi

if [ -z "$TEST_USER_POOL_ID" ] || [ -z "$TEST_REGION" ] || [ -z "$TEST_ALEX_EMAIL" ]; then
  echo "Error: Required environment variables not set in .env"
  echo "Required: TEST_USER_POOL_ID, TEST_REGION, TEST_ALEX_EMAIL"
  exit 1
fi

echo "Deleting Cognito user: $TEST_ALEX_EMAIL"
aws cognito-idp admin-delete-user \
  --user-pool-id "$TEST_USER_POOL_ID" \
  --username "$TEST_ALEX_EMAIL" \
  --region "$TEST_REGION"

echo "✅ Cognito user deleted."
echo ""
echo "To delete the associated DynamoDB data, sign in as Alex Kernel and use"
echo "Account Settings -> Delete Account, or ask an admin to run the"
echo "adminDeleteUser mutation for the account."
