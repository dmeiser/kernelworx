#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$SCRIPT_DIR/assets/managed-login-settings.json"
BACKUP_FILE="$SCRIPT_DIR/assets/managed-login-settings.json.bak"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy-cognito-branding.sh"
PLAYWRIGHT_CAPTURE_DIR="$SCRIPT_DIR/../frontend/tests/e2e/results"
BASELINE_FILE="$SCRIPT_DIR/branding-baseline.json"

if [ "${1:-}" == "--help" ] || [ -z "${1:-}" ]; then
  echo "Usage: $0 <dot.json.path> <value> [--keep]"
  exit 1
fi

KEY=$1
VALUE=$2
KEEP=${3:-}

if [ ! -f "$SETTINGS_FILE" ]; then
  echo "Settings file not found: $SETTINGS_FILE"
  exit 1
fi

# Back up
cp "$SETTINGS_FILE" "$BACKUP_FILE"

# Set the value (numeric or not) - reuse jq logic
VALUE_STR=${VALUE//\#/}
TMP_FILE="/tmp/managed-login-settings.$$.json"
if [[ "$VALUE_STR" =~ ^(true|false|null|[0-9]+([.][0-9]+)?)$ ]]; then
  jq --argjson val "$VALUE_STR" ".${KEY} = \$val" "$SETTINGS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SETTINGS_FILE"
else
  jq --arg val "$VALUE_STR" ".${KEY} = \$val" "$SETTINGS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SETTINGS_FILE"
fi

# Validate
if ! jq empty "$SETTINGS_FILE" >/dev/null 2>&1; then
  echo "Invalid JSON after change. Restoring backup"
  mv "$BACKUP_FILE" "$SETTINGS_FILE"
  exit 1
fi

# Deploy
bash "$DEPLOY_SCRIPT"

echo "Waiting 30s for propagation..."
sleep 30

# Ensure output dir exists
mkdir -p "$PLAYWRIGHT_CAPTURE_DIR"

# Run Playwright capture (foreground so user can see)
HOSTED_UI_URL="https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173" OUTDIR="$PLAYWRIGHT_CAPTURE_DIR" node ../frontend/playwright-capture.js || true

# Compare results with baseline
RESULT_JSON="$PLAYWRIGHT_CAPTURE_DIR/cognito-branding-results.json"
if [ ! -f "$RESULT_JSON" ]; then
  echo "No results file generated: $RESULT_JSON"
  [ "$KEEP" == "--keep" ] || mv "$BACKUP_FILE" "$SETTINGS_FILE"
  exit 1
fi

# Read expected values and actual values
expected_primary=$(jq -r '.primaryButtonColor' "$BASELINE_FILE")
expected_bg=$(jq -r '.pageBackgroundColor' "$BASELINE_FILE")
expected_link=$(jq -r '.linkColor' "$BASELINE_FILE")
expected_logo=$(jq -r '.logoPresent' "$BASELINE_FILE")

actual_primary=$(jq -r '.primaryButtonColor' "$RESULT_JSON")
actual_bg=$(jq -r '.pageBackgroundColor' "$RESULT_JSON")
actual_link=$(jq -r '.linkColor' "$RESULT_JSON")
actual_logo=$(jq -r '.logoPresent' "$RESULT_JSON")

echo "Baseline vs Actual:"
echo "  primary: $expected_primary vs $actual_primary"
echo "  bg:      $expected_bg vs $actual_bg"
echo "  link:    $expected_link vs $actual_link"
echo "  logo:    $expected_logo vs $actual_logo"

# Determine pass/fail
PASS=true
if [ "$expected_primary" != "$actual_primary" ]; then
  echo "Primary color mismatch"
  PASS=false
fi
if [ "$expected_bg" != "$actual_bg" ]; then
  echo "Background color mismatch"
  PASS=false
fi
if [ "$expected_link" != "$actual_link" ]; then
  echo "Link color mismatch"
  PASS=false
fi
if [ "$expected_logo" != "$actual_logo" ]; then
  echo "Logo presence mismatch"
  PASS=false
fi

OUTDIR_TS="$SCRIPT_DIR/branding-results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR_TS"
cp "$PLAYWRIGHT_CAPTURE_DIR/cognito-page.png" "$OUTDIR_TS/" || true
cp "$PLAYWRIGHT_CAPTURE_DIR/cognito-form.png" "$OUTDIR_TS/" || true
cp "$RESULT_JSON" "$OUTDIR_TS/" || true

if [ "$PASS" == "true" ]; then
  echo "All checks passed!"
else
  echo "Some checks failed; see $OUTDIR_TS for captures and results"
fi

if [ "$KEEP" != "--keep" ]; then
  echo "Restoring previous settings (no --keep)"
  mv "$BACKUP_FILE" "$SETTINGS_FILE"
  echo "If you want to keep changes, run again with --keep"
fi

exit 0
