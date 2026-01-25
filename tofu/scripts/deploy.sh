#!/bin/bash
# OpenTofu deployment script
set -e

ENV="${1:-dev}"
ACTION="${2:-plan}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_DIR="$SCRIPT_DIR/../environments/$ENV"

# Load environment variables from root .env
if [ -f "$ROOT_DIR/.env" ]; then
    echo "📂 Loading environment from $ROOT_DIR/.env"
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

# Set OpenTofu variables from env
export TF_VAR_encryption_passphrase="${ENCRYPTION_PASSPHRASE:-}"
export TF_VAR_google_client_id="${GOOGLE_CLIENT_ID:-}"
export TF_VAR_google_client_secret="${GOOGLE_CLIENT_SECRET:-}"

# Validation
if [ -z "$TF_VAR_encryption_passphrase" ]; then
    echo "❌ ENCRYPTION_PASSPHRASE not set in .env"
    exit 1
fi

if [ -z "$TF_VAR_google_client_id" ] || [ -z "$TF_VAR_google_client_secret" ]; then
    echo "⚠️  Warning: Google OAuth credentials not set"
fi

cd "$ENV_DIR"

echo ""
echo "🚀 OpenTofu $ACTION for $ENV"
echo "   Working directory: $ENV_DIR"
echo ""

case "$ACTION" in
    init)
        echo "📦 Initializing OpenTofu..."
        tofu init -upgrade
        ;;
    plan)
        echo "📋 Planning changes..."
        tofu plan -out=tfplan
        ;;
    apply)
        if [ -f tfplan ]; then
            echo "🚀 Applying saved plan..."
            tofu apply tfplan
            rm tfplan
        else
            echo "🚀 Applying changes..."
            tofu apply
        fi
        ;;
    destroy)
        echo "⚠️  Are you sure? This will destroy all resources!"
        read -p "Type 'yes' to confirm: " confirm
        if [ "$confirm" == "yes" ]; then
            tofu destroy
        else
            echo "Aborted."
        fi
        ;;
    import)
        echo "📥 Running import script..."
        "$SCRIPT_DIR/import-resources.sh" "$ENV"
        ;;
    validate)
        echo "✅ Validating configuration..."
        tofu validate
        ;;
    fmt)
        echo "🎨 Formatting configuration..."
        tofu fmt -recursive "$SCRIPT_DIR/.."
        ;;
    *)
        echo "Usage: $0 <env> <init|plan|apply|destroy|import|validate|fmt>"
        echo ""
        echo "Commands:"
        echo "  init      Initialize OpenTofu (download providers)"
        echo "  plan      Preview changes"
        echo "  apply     Apply changes"
        echo "  destroy   Destroy all resources (with confirmation)"
        echo "  import    Import existing AWS resources"
        echo "  validate  Validate configuration"
        echo "  fmt       Format configuration files"
        exit 1
        ;;
esac

echo ""
echo "✅ Done!"
