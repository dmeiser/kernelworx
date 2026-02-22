#!/bin/bash
# OpenTofu deployment script
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
fi

ENV="${1:-dev}"
ACTION="${2:-plan}"
shift 2 2>/dev/null || shift $#  # Remove first two args, keep rest as extra flags
EXTRA_FLAGS="$@"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_DIR="$SCRIPT_DIR/../environments/$ENV"

LAYER_DIR="$ROOT_DIR/.build/lambda-layer"
LAYER_REQ="$LAYER_DIR/requirements.txt"

# Load environment variables from root .env
if [ -f "$ROOT_DIR/.env" ]; then
    echo "📂 Loading environment from $ROOT_DIR/.env"
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

# Validation (TF_VAR_* already sourced from .env)
if [ -z "$TF_VAR_encryption_passphrase" ]; then
    echo "❌ TF_VAR_encryption_passphrase not set in .env"
    exit 1
fi

if [ -z "$TF_VAR_google_client_id" ] || [ -z "$TF_VAR_google_client_secret" ]; then
    echo "⚠️  Warning: Google OAuth credentials not set (TF_VAR_google_client_id/secret)"
fi

build_lambda_layer() {
    echo "📦 Building Lambda layer dependencies (prod-only)..."
    rm -rf "$LAYER_DIR"
    mkdir -p "$LAYER_DIR/python"

    (cd "$ROOT_DIR" && uv export --no-dev --format requirements.txt --no-hashes > "$LAYER_REQ")
    (cd "$ROOT_DIR" && uv pip install --requirement "$LAYER_REQ" --target "$LAYER_DIR/python")
}

cd "$ENV_DIR"

echo ""
echo "🚀 OpenTofu $ACTION for $ENV"
echo "   Working directory: $ENV_DIR"
echo ""

case "$ACTION" in
    init)
        echo "📦 Initializing OpenTofu..."
        tofu init -upgrade $EXTRA_FLAGS
        ;;
    plan)
        echo "📋 Planning changes..."
        build_lambda_layer
        tofu plan -out=tfplan $EXTRA_FLAGS
        ;;
    apply)
        AUTO_APPROVE_FLAG=""
        if [ "${AUTO_APPROVE:-}" = "1" ]; then
            AUTO_APPROVE_FLAG="-auto-approve"
        fi

        build_lambda_layer
        if [ -f tfplan ]; then
            echo "🚀 Applying saved plan..."
            tofu apply $AUTO_APPROVE_FLAG $EXTRA_FLAGS tfplan
            rm tfplan
        else
            echo "🚀 Applying changes..."
            tofu apply $AUTO_APPROVE_FLAG $EXTRA_FLAGS
        fi
        ;;
    destroy)
        echo "⚠️  Are you sure? This will destroy all resources!"
        read -p "Type 'yes' to confirm: " confirm
        if [ "$confirm" == "yes" ]; then
            tofu destroy $EXTRA_FLAGS
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
        tofu validate $EXTRA_FLAGS
        ;;
    fmt)
        echo "🎨 Formatting configuration..."
        tofu fmt -recursive "$SCRIPT_DIR/.."
        ;;
    *)
        echo "Usage: $0 <env> <init|plan|apply|destroy|import|validate|fmt> [extra-flags]"
        echo ""
        echo "Commands:"
        echo "  init      Initialize OpenTofu (download providers)"
        echo "  plan      Preview changes"
        echo "  apply     Apply changes"
        echo "  destroy   Destroy all resources (with confirmation)"
        echo "  import    Import existing AWS resources"
        echo "  validate  Validate configuration"
        echo "  fmt       Format configuration files"
        echo ""
        echo "Examples:"
        echo "  $0 dev init -migrate-state    # Migrate state during init"
        echo "  $0 dev init -reconfigure      # Reconfigure backend without migration"
        echo "  $0 dev plan -target=module.s3 # Plan only s3 module"
                exit 1
        ;;
esac
echo ""
echo "✅ Done!"
