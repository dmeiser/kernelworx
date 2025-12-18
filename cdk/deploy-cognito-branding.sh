#!/bin/bash
#
# Deploy Cognito Managed Login Branding
#
# This script configures the Cognito Hosted UI with:
# - Custom logo (PNG popcorn banner)
# - Solid color background (SVG)
# - Brand colors (primary blue #1976d2)
# - COPPA compliance warning (13+ age requirement)
# - Satisfy font for headings, Open Sans for body
#
# Prerequisites:
# - AWS CLI configured with appropriate credentials
# - CDK stack deployed (to get User Pool ID and Client ID)
# - Asset files (popcorn-banner.png, favicon.ico, page-background.svg) present in docs/branding directory
#
# Usage:
#   ./deploy-cognito-branding.sh

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Cognito Managed Login Branding Deployment ===${NC}\n"

# Get stack outputs
echo -e "${YELLOW}Getting CloudFormation outputs...${NC}"
STACK_NAME="kernelworx-dev"

# Extract User Pool ID from CDK stack (works for both imported and managed)
USER_POOL_ID=$(aws cloudformation describe-stack-resources \
  --stack-name "$STACK_NAME" \
  --query 'StackResources[?ResourceType==`AWS::Cognito::UserPool`].PhysicalResourceId' \
  --output text)

# If not found in stack (imported resource), find by name
if [ -z "$USER_POOL_ID" ]; then
  echo -e "${YELLOW}User Pool not found in stack, searching by name...${NC}"
  USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 20 \
    --query "UserPools[?Name=='kernelworx-users-dev'].Id" \
    --output text)
fi

if [ -z "$USER_POOL_ID" ]; then
  echo -e "${RED}Error: Could not find User Pool ID${NC}"
  exit 1
fi

echo -e "User Pool ID: ${GREEN}$USER_POOL_ID${NC}"

# Extract Client ID from User Pool
CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
  --user-pool-id "$USER_POOL_ID" \
  --query 'UserPoolClients[0].ClientId' \
  --output text)

if [ -z "$CLIENT_ID" ]; then
  echo -e "${RED}Error: Could not find Client ID for User Pool $USER_POOL_ID${NC}"
  exit 1
fi

echo -e "Client ID: ${GREEN}$CLIENT_ID${NC}\n"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANDING_DIR="$SCRIPT_DIR/../docs/branding"

# Check if assets exist
LOGO_PNG="$BRANDING_DIR/popcorn-banner.png"
FAVICON_ICO="$BRANDING_DIR/favicon.ico"
BACKGROUND_SVG="$BRANDING_DIR/page-background.svg"
SETTINGS_FILE="$BRANDING_DIR/managed-login-settings.json"

if [ ! -f "$LOGO_PNG" ]; then
  echo -e "${RED}Error: Logo file not found: $LOGO_PNG${NC}"
  exit 1
fi

if [ ! -f "$FAVICON_ICO" ]; then
  echo -e "${RED}Error: Favicon file not found: $FAVICON_ICO${NC}"
  exit 1
fi

if [ ! -f "$BACKGROUND_SVG" ]; then
  echo -e "${RED}Error: Background SVG file not found: $BACKGROUND_SVG${NC}"
  exit 1
fi

if [ ! -f "$SETTINGS_FILE" ]; then
  echo -e "${RED}Error: Settings file not found: $SETTINGS_FILE${NC}"
  exit 1
fi

echo -e "${YELLOW}Encoding assets to base64...${NC}"
LOGO_BASE64=$(base64 -w 0 < "$LOGO_PNG")
FAVICON_BASE64=$(base64 -w 0 < "$FAVICON_ICO")
BACKGROUND_BASE64=$(base64 -w 0 < "$BACKGROUND_SVG")

echo -e "${YELLOW}Reading branding settings...${NC}"
SETTINGS_JSON=$(cat "$SETTINGS_FILE")

echo -e "${YELLOW}Creating managed login branding configuration with logo, favicon, background, and header...${NC}\n"

# Create Assets array with logo, favicon, background, and header logo
ASSETS_JSON=$(cat <<EOF
[
  {
    "Category": "FORM_LOGO",
    "ColorMode": "LIGHT",
    "Extension": "PNG",
    "Bytes": "$LOGO_BASE64"
  },
  {
    "Category": "PAGE_HEADER_LOGO",
    "ColorMode": "LIGHT",
    "Extension": "PNG",
    "Bytes": "$LOGO_BASE64"
  },
  {
    "Category": "FAVICON_ICO",
    "ColorMode": "LIGHT",
    "Extension": "ICO",
    "Bytes": "$FAVICON_BASE64"
  },
  {
    "Category": "PAGE_BACKGROUND",
    "ColorMode": "LIGHT",
    "Extension": "SVG",
    "Bytes": "$BACKGROUND_BASE64"
  }
]
EOF
)

# Create JSON input for AWS CLI with Settings and Assets
cat > /tmp/cognito-branding-input.json <<EOF
{
  "UserPoolId": "$USER_POOL_ID",
  "ClientId": "$CLIENT_ID",
  "UseCognitoProvidedValues": false,
  "Settings": $SETTINGS_JSON,
  "Assets": $ASSETS_JSON
}
EOF

# Check if branding already exists
echo -e "${YELLOW}Checking for existing branding...${NC}"
EXISTING_BRANDING=$(aws cognito-idp describe-managed-login-branding-by-client \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --output json 2>/dev/null || echo "{}")

BRANDING_ID=$(echo "$EXISTING_BRANDING" | jq -r '.ManagedLoginBranding.ManagedLoginBrandingId // empty')

if [ -z "$BRANDING_ID" ]; then
  # Create new branding
  echo -e "${GREEN}No existing branding found. Creating new branding...${NC}\n"
  
  RESULT=$(aws cognito-idp create-managed-login-branding \
    --cli-input-json file:///tmp/cognito-branding-input.json \
    --output json)
  
  BRANDING_ID=$(echo "$RESULT" | jq -r '.ManagedLoginBranding.ManagedLoginBrandingId')
  
  echo -e "${GREEN}✓ Branding created successfully!${NC}"
  echo -e "Branding ID: ${GREEN}$BRANDING_ID${NC}\n"
else
  # Update existing branding
  echo -e "${YELLOW}Found existing branding: $BRANDING_ID${NC}"
  echo -e "${GREEN}Updating branding...${NC}\n"
  
  # Remove ClientId and add ManagedLoginBrandingId for update
  jq --arg id "$BRANDING_ID" 'del(.ClientId) | . + {ManagedLoginBrandingId: $id}' \
    /tmp/cognito-branding-input.json > /tmp/cognito-branding-update.json
  
  RESULT=$(aws cognito-idp update-managed-login-branding \
    --cli-input-json file:///tmp/cognito-branding-update.json \
    --output json)
  
  echo -e "${GREEN}✓ Branding updated successfully!${NC}\n"
fi

# Clean up temp files
rm -f /tmp/cognito-branding-input.json /tmp/cognito-branding-update.json

# Show Hosted UI URL
REGION=$(aws configure get region)
HOSTED_UI_URL="https://kernelworx-dev.auth.${REGION}.amazoncognito.com/login?client_id=${CLIENT_ID}&response_type=code&redirect_uri=http://localhost:5173"

# Ensure domain is using Managed Login (not Hosted UI classic)
echo -e "${YELLOW}Verifying domain branding version...${NC}"
CURRENT_VERSION=$(aws cognito-idp describe-user-pool-domain \
  --domain kernelworx-dev \
  --query 'DomainDescription.ManagedLoginVersion' \
  --output text)

if [ "$CURRENT_VERSION" != "2" ]; then
  echo -e "${YELLOW}Domain is using version $CURRENT_VERSION. Updating to Managed Login v2...${NC}"
  aws cognito-idp update-user-pool-domain \
    --domain kernelworx-dev \
    --user-pool-id "$USER_POOL_ID" \
    --managed-login-version 2 \
    --output json > /dev/null
  echo -e "${GREEN}✓ Domain updated to Managed Login v2${NC}"
  echo -e "${YELLOW}Note: Changes may take up to 4 minutes to propagate${NC}\n"
else
  echo -e "${GREEN}✓ Domain already using Managed Login v2${NC}\n"
fi

echo -e "${GREEN}=== Deployment Complete ===${NC}\n"
echo -e "Test your branding at:"
echo -e "${GREEN}${HOSTED_UI_URL}${NC}\n"
echo -e "You should see:"
echo -e "  ✓ Primary blue buttons (#1976d2)"
echo -e "  ✓ Styled form with custom colors"
echo -e "  ✓ Solid light gray background (#f5f5f5)"
echo -e "  ✓ Popcorn banner logo in the form"
echo -e "\n${YELLOW}Note: Do a hard refresh (Ctrl+Shift+R) to clear browser cache${NC}\n"
