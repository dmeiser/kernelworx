#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 <command> [options]

Commands:
  set <dot.path> <value>   Set a single JSON path value in settings
  apply <path-to-json>     Replace settings JSON with provided file
  deploy                   Deploy current settings only
  preview [--detach]       Deploy and open Playwright preview (foreground by default)
  validate                 Validate the current settings JSON

Options:
  --no-confirm             Don't ask to keep changes after preview
  --detach                 Run preview in background (for preview command)
EOF
  exit 1
}

# Playground for updating managed login settings and previewing in Playwright
# Usage: ./brand-playground.sh set <JSON-path> <value> OR ./brand-playground.sh apply <path-to-json>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$SCRIPT_DIR/assets/managed-login-settings.json"
BACKUP_FILE="$SCRIPT_DIR/assets/managed-login-settings.json.bak"
TMP_FILE="/tmp/managed-login-settings.$$.json"
PLAYGROUND_MODE=false
DETACH=false
NO_CONFIRM=false

if [ ! -f "$SETTINGS_FILE" ]; then
  echo "Error: settings file not found: $SETTINGS_FILE"
  exit 1
fi

validate_json() {
  local file="$1"
  if ! jq empty "$file" >/dev/null 2>&1; then
    echo "Invalid JSON: $file"
    return 1
  fi
  return 0
}

CMD=${1:-}
shift || true
if [ -z "$CMD" ]; then
  usage
fi

case "$CMD" in
  set)
  # Convert a dot-notation path to jq assignment, example:
  # components.primaryButton.lightMode.defaults.backgroundColor
  # value should be passed exactly as expected (e.g. 1976d2ff or "something")
  KEY=$1
  VALUE=${2:-}
  if [ -z "$KEY" ] || [ -z "$VALUE" ]; then
    echo "Usage: $0 set <dot.path> <value>"
    exit 1
  fi

  # Create a backup
  cp "$SETTINGS_FILE" "$BACKUP_FILE"

  # Strip leading # if present
  VALUE_STR=${VALUE//\#/}
  # If value is numeric use --argjson otherwise use --arg
  # When value is simple literal true|false|null|number use --argjson
  if [[ "$VALUE_STR" =~ ^(true|false|null|[0-9]+([.][0-9]+)?)$ ]]; then
    jq --argjson val "$VALUE_STR" ".${KEY} = \$val" "$SETTINGS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SETTINGS_FILE"
  else
    jq --arg val "$VALUE_STR" ".${KEY} = \$val" "$SETTINGS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SETTINGS_FILE"
  fi
  # Validate
  if ! validate_json "$SETTINGS_FILE"; then
    echo "Rolling back due to invalid JSON"
    mv "$BACKUP_FILE" "$SETTINGS_FILE"
    exit 1
  fi
  echo "Updated $KEY -> $VALUE_STR"

  ;;
  apply)
    SRC=$1
    if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
      echo "Usage: $0 apply <path-to-json>"
      exit 1
    fi

    # Validate source JSON first
    if ! validate_json "$SRC"; then
      echo "Source JSON is invalid. Aborting."
      exit 1
    fi

    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    cp "$SRC" "$SETTINGS_FILE"
    echo "Applied $SRC"
    ;;
  deploy)
    # Deploy only
    ;;
  preview)
    # extra flags: --detach, --no-confirm
    while (("$#")); do
      case "$1" in
        --detach) DETACH=true ; shift ;;
        --no-confirm) NO_CONFIRM=true ; shift ;;
        *) echo "Unknown option $1"; usage; ;;
      esac
    done
    PLAYGROUND_MODE=true
    ;;
  validate)
    if validate_json "$SETTINGS_FILE"; then
      echo "OK: $SETTINGS_FILE is valid JSON"
      exit 0
    else
      echo "Invalid settings"
      exit 1
    fi
    ;;
  *)
    echo "Unknown command: $CMD"
    usage
    ;;
esac

## NOTE: previous legacy branch removed

# Deploy branding
bash "$SCRIPT_DIR/deploy-cognito-branding.sh"

# Wait for a clip of time to allow propagation
echo "Waiting 30s for updates to propagate (CloudFront caching)"
sleep 30

# Launch interactive Playwright view, optionally detach
if [ "$PLAYGROUND_MODE" = true ]; then
  pushd "$SCRIPT_DIR/../frontend" > /dev/null
  HOSTED_UI_URL="https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173"
  if [ "$DETACH" = true ]; then
    echo "Launching Playwright in background (detached)"
    nohup node playwright-interactive.js > /tmp/playwright.log 2>&1 &
    echo "Playwright launched (detached). Inspect /tmp/playwright.log for output. PID: $!"
    popd > /dev/null
  else
    echo "Launching Playwright (foreground). Press Ctrl+C to close preview when done."
    # Run foreground and wait for user to close the browser
    node playwright-interactive.js
    popd > /dev/null
  fi
fi

# After closing preview, optionally restore backup (only if not --no-confirm)
if [ "$PLAYGROUND_MODE" = true ] && [ "$NO_CONFIRM" = false ]; then
  read -p "Keep changes? (y/N): " KEEP
  if [[ "$KEEP" =~ ^[Yy]$ ]]; then
    echo "Changes kept"
  else
    echo "Restoring backup"
    mv "$BACKUP_FILE" "$SETTINGS_FILE"
  fi
fi

echo "Done."