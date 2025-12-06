#!/usr/bin/env bash
set -e

# Loop through colors and deploy
COLORS=("1976d2" "2e7d32" "e53935")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$SCRIPT_DIR/assets/managed-login-settings.json"
RESULT_DIR="$SCRIPT_DIR/test-results"
mkdir -p "$RESULT_DIR"

for c in "${COLORS[@]}"; do
  color8="${c}ff"
  echo "\n=== Deploying branding with primary color #$c ==="
  echo "Updating $SETTINGS_FILE"
  jq --arg col "$color8" '.components.primaryButton.lightMode.defaults.backgroundColor = $col | .components.primaryButton.lightMode.hover.backgroundColor = $col | .components.primaryButton.lightMode.active.backgroundColor = $col' "$SETTINGS_FILE" > /tmp/managed-login-settings.json
  mv /tmp/managed-login-settings.json "$SETTINGS_FILE"

  echo "Deploying branding..."
  bash "$SCRIPT_DIR/deploy-cognito-branding.sh" || { echo "deploy failed"; exit 1; }

  echo "Waiting 60 seconds for propagation (CloudFront)"
  sleep 60

  echo "Running Playwright tests (headed) for color #$c"
  pushd "$SCRIPT_DIR/../frontend" > /dev/null
  EXPECTED_PRIMARY_COLOR="$c" HOSTED_UI_URL="https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173" npm run test:e2e:headed || true
  popd > /dev/null

  # Save the screenshot from results folder
  if [ -f "$SCRIPT_DIR/../frontend/tests/e2e/results/cognito-page.png" ]; then
    cp "$SCRIPT_DIR/../frontend/tests/e2e/results/cognito-page.png" "$RESULT_DIR/cognito-page-$c.png"
  fi

  echo "Saved result to $RESULT_DIR/cognito-page-$c.png"
done

echo "All done"
