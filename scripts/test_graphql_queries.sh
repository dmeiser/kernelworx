#!/bin/bash

# Test GraphQL Queries Script
# This script tests all deployed GraphQL query resolvers

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Popcorn Sales Manager - GraphQL Query Testing ===${NC}\n"

# Get API endpoint from AWS
echo "Getting API endpoint..."
API_ENDPOINT=$(aws appsync list-graphql-apis \
  --query "graphqlApis[?name=='kernelworx-api-dev'].uris.GRAPHQL" \
  --output text)

if [ -z "$API_ENDPOINT" ]; then
  echo -e "${RED}ERROR: Could not find API endpoint${NC}"
  exit 1
fi

echo -e "${GREEN}API Endpoint: $API_ENDPOINT${NC}\n"

# Get User Pool details
USER_POOL_ID="us-east-1_m861e2MtM"
echo "User Pool ID: $USER_POOL_ID"

# Check for existing test user
echo "Checking for test user..."
EXISTING_USER=$(aws cognito-idp list-users \
  --user-pool-id $USER_POOL_ID \
  --filter "email = \"test@popcorn-sales.example\"" \
  --query 'Users[0].Username' \
  --output text 2>/dev/null || echo "")

if [ "$EXISTING_USER" == "None" ] || [ -z "$EXISTING_USER" ]; then
  echo -e "${YELLOW}Creating test user...${NC}"
  
  # Create test user
  aws cognito-idp admin-create-user \
    --user-pool-id $USER_POOL_ID \
    --username test@popcorn-sales.example \
    --user-attributes Name=email,Value=test@popcorn-sales.example Name=email_verified,Value=true \
    --temporary-password "TempPass123!" \
    --message-action SUPPRESS > /dev/null
  
  # Set permanent password
  aws cognito-idp admin-set-user-password \
    --user-pool-id $USER_POOL_ID \
    --username test@popcorn-sales.example \
    --password "TestPassword123!" \
    --permanent > /dev/null
  
  echo -e "${GREEN}✓ Test user created${NC}"
else
  echo -e "${GREEN}✓ Test user already exists${NC}"
fi

# Get Client ID
echo "Getting User Pool Client ID..."
CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
  --user-pool-id $USER_POOL_ID \
  --query 'UserPoolClients[0].ClientId' \
  --output text)

if [ -z "$CLIENT_ID" ]; then
  echo -e "${RED}ERROR: Could not find User Pool Client${NC}"
  exit 1
fi

echo -e "${GREEN}Client ID: $CLIENT_ID${NC}\n"

# Get ID Token
echo "Authenticating user..."
AUTH_RESULT=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id $CLIENT_ID \
  --auth-parameters USERNAME=test@popcorn-sales.example,PASSWORD=TestPassword123! \
  --query 'AuthenticationResult' \
  --output json 2>&1)

if echo "$AUTH_RESULT" | grep -q "error"; then
  echo -e "${RED}ERROR: Authentication failed${NC}"
  echo "$AUTH_RESULT"
  exit 1
fi

ID_TOKEN=$(echo "$AUTH_RESULT" | jq -r '.IdToken')
USER_SUB=$(echo "$ID_TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null | jq -r '.sub' 2>/dev/null || echo "")

echo -e "${GREEN}✓ Authentication successful${NC}"
echo "User Sub: $USER_SUB"
echo ""

# Insert test data into DynamoDB
echo "Inserting test data into DynamoDB..."
TABLE_NAME="psm-app-dev"

# Create account record
aws dynamodb put-item \
  --table-name $TABLE_NAME \
  --item "{
    \"PK\": {\"S\": \"ACCOUNT#$USER_SUB\"},
    \"SK\": {\"S\": \"METADATA\"},
    \"accountId\": {\"S\": \"$USER_SUB\"},
    \"email\": {\"S\": \"test@popcorn-sales.example\"},
    \"isAdmin\": {\"BOOL\": false},
    \"createdAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
  }" > /dev/null 2>&1

# Create profile record
aws dynamodb put-item \
  --table-name $TABLE_NAME \
  --item "{
    \"PK\": {\"S\": \"ACCOUNT#$USER_SUB\"},
    \"SK\": {\"S\": \"PROFILE#test-profile-001\"},
    \"profileId\": {\"S\": \"PROFILE#test-profile-001\"},
    \"sellerName\": {\"S\": \"Test Scout\"},
    \"ownerAccountId\": {\"S\": \"$USER_SUB\"},
    \"createdAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"},
    \"updatedAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
  }" > /dev/null 2>&1

# Create season record
aws dynamodb put-item \
  --table-name $TABLE_NAME \
  --item "{
    \"PK\": {\"S\": \"PROFILE#test-profile-001\"},
    \"SK\": {\"S\": \"SEASON#test-season-001\"},
    \"seasonId\": {\"S\": \"SEASON#test-season-001\"},
    \"profileId\": {\"S\": \"PROFILE#test-profile-001\"},
    \"seasonName\": {\"S\": \"Fall 2025\"},
    \"startDate\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"},
    \"catalogId\": {\"S\": \"CATALOG#default\"},
    \"createdAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"},
    \"updatedAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
  }" > /dev/null 2>&1

# Create order record
aws dynamodb put-item \
  --table-name $TABLE_NAME \
  --item "{
    \"PK\": {\"S\": \"SEASON#test-season-001\"},
    \"SK\": {\"S\": \"ORDER#test-order-001\"},
    \"orderId\": {\"S\": \"ORDER#test-order-001\"},
    \"seasonId\": {\"S\": \"SEASON#test-season-001\"},
    \"customerName\": {\"S\": \"Test Customer\"},
    \"totalAmount\": {\"N\": \"50.00\"},
    \"paymentMethod\": {\"S\": \"CASH\"},
    \"createdAt\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
  }" > /dev/null 2>&1

echo -e "${GREEN}✓ Test data inserted${NC}\n"

# Function to test a GraphQL query
test_query() {
  local query_name=$1
  local query=$2
  
  echo -e "${YELLOW}Testing: $query_name${NC}"
  
  RESPONSE=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: $ID_TOKEN" \
    "$API_ENDPOINT" \
    -d "{\"query\": \"$query\"}")
  
  if echo "$RESPONSE" | jq -e '.errors' > /dev/null 2>&1; then
    echo -e "${RED}✗ FAILED${NC}"
    echo "$RESPONSE" | jq '.errors'
  elif echo "$RESPONSE" | jq -e '.data' > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SUCCESS${NC}"
    echo "$RESPONSE" | jq '.data'
  else
    echo -e "${RED}✗ UNEXPECTED RESPONSE${NC}"
    echo "$RESPONSE" | jq '.'
  fi
  
  echo ""
}

# Run all query tests
echo -e "${YELLOW}=== Testing Query Resolvers ===${NC}\n"

test_query "getMyAccount" \
  "query { getMyAccount { accountId email isAdmin createdAt } }"

test_query "listMyProfiles" \
  "query { listMyProfiles { profileId sellerName ownerAccountId createdAt } }"

test_query "getProfile" \
  "query { getProfile(profileId: \\\"PROFILE#test-profile-001\\\") { profileId sellerName ownerAccountId } }"

test_query "listSharedProfiles" \
  "query { listSharedProfiles { profileId permissions } }"

test_query "getSeason" \
  "query { getSeason(seasonId: \\\"SEASON#test-season-001\\\") { seasonId profileId seasonName catalogId } }"

test_query "listSeasonsByProfile" \
  "query { listSeasonsByProfile(profileId: \\\"PROFILE#test-profile-001\\\") { seasonId seasonName catalogId } }"

test_query "getOrder" \
  "query { getOrder(orderId: \\\"ORDER#test-order-001\\\") { orderId customerName totalAmount paymentMethod } }"

test_query "listOrdersBySeason" \
  "query { listOrdersBySeason(seasonId: \\\"SEASON#test-season-001\\\") { orderId customerName totalAmount } }"

echo -e "${GREEN}=== Testing Complete ===${NC}"
echo ""
echo "To clean up test data, run:"
echo "aws dynamodb delete-item --table-name $TABLE_NAME --key '{\"PK\": {\"S\": \"ACCOUNT#$USER_SUB\"}, \"SK\": {\"S\": \"METADATA\"}}'"
echo "aws dynamodb delete-item --table-name $TABLE_NAME --key '{\"PK\": {\"S\": \"ACCOUNT#$USER_SUB\"}, \"SK\": {\"S\": \"PROFILE#test-profile-001\"}}'"
echo "aws dynamodb delete-item --table-name $TABLE_NAME --key '{\"PK\": {\"S\": \"PROFILE#test-profile-001\"}, \"SK\": {\"S\": \"SEASON#test-season-001\"}}'"
echo "aws dynamodb delete-item --table-name $TABLE_NAME --key '{\"PK\": {\"S\": \"SEASON#test-season-001\"}, \"SK\": {\"S\": \"ORDER#test-order-001\"}}'"
