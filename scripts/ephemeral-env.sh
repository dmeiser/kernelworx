#!/bin/bash
# Manage ephemeral per-run test environments.
#
# Usage:
#   scripts/ephemeral-env.sh up <run-id>
#   eval $(scripts/ephemeral-env.sh env <run-id>)
#   scripts/ephemeral-env.sh down <run-id>
#
# The script sources the repository root .env for AWS credentials/profile and
# the OpenTofu state encryption passphrase, same as deploy.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DIR="$ROOT_DIR/tofu/application/environments/ephemeral"

# TEST-ONLY: allow unit tests to redirect the Lambda layer build directory
# so they do not pollute the developer's worktree. Production runs always use
# the standard location under the repository root.
LAYER_DIR="${KERNELWORX_TEST_LAYER_DIR:-$ROOT_DIR/.build/lambda-layer}"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/ephemeral-recover-common.sh"

log() {
  echo "$@" >&2
}

# Load environment variables from root .env
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

if [ -z "$TF_VAR_encryption_passphrase" ]; then
  log "❌ TF_VAR_encryption_passphrase not set in .env"
  exit 1
fi

# Validate arguments
if [ $# -lt 2 ]; then
  log "Usage: $0 <up|env|down> <run-id>"
  exit 1
fi

ACTION="$1"
RUN_ID="$2"

if [ -z "$RUN_ID" ]; then
  log "❌ run-id cannot be empty"
  exit 1
fi

STATE_KEY="application/ephemeral/${RUN_ID}/terraform.tfstate"

cd "$ENV_DIR"

build_lambda_layer() {
  log "📦 Building Lambda layer dependencies..."
  LAYER_REQ="$LAYER_DIR/requirements.txt"
  rm -rf "$LAYER_DIR"
  mkdir -p "$LAYER_DIR/python"
  (cd "$ROOT_DIR" && uv export --no-dev --format requirements.txt --no-hashes > "$LAYER_REQ")
  (cd "$ROOT_DIR" && uv pip install --requirement "$LAYER_REQ" --target "$LAYER_DIR/python")
}

cleanup_cloudwatch_log_groups() {
  log "🧹 Cleaning up pre-existing CloudWatch log groups for run: $RUN_ID"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-${RUN_ID}"
  local log_groups

  log_groups=$(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/lambda/kernelworx-" \
    --region "$region" \
    --query 'logGroups[*].logGroupName' \
    --output text)

  if [ -z "$log_groups" ] || [ "$log_groups" = "None" ]; then
    log "   No existing log groups found."
    return 0
  fi

  local found=0
  for name in $log_groups; do
    case "$name" in
      *"$suffix")
        log "   Deleting log group: $name"
        aws logs delete-log-group --log-group-name "$name" --region "$region" || true
        found=1
        ;;
    esac
  done

  if [ "$found" -eq 0 ]; then
    log "   No existing log groups found for this run."
  fi
}

# If the state object has been deleted (e.g. by a previous failed teardown run
# that removed state before destroy succeeded), restore the latest S3 version
# so `tofu destroy` can run against the real resource state.
recover_state_if_missing() {
  local state_url="s3://${STATE_BUCKET}/${STATE_KEY}"

  log "📦 Checking state object: $state_url"
  if aws s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" --region "$STATE_REGION" >/dev/null 2>&1; then
    log "   State object exists."
    return 0
  fi

  log "   State object is missing; searching S3 versions for recoverable state..."
  local latest_version
  latest_version=$(aws s3api list-object-versions \
    --bucket "$STATE_BUCKET" \
    --prefix "$STATE_KEY" \
    --region "$STATE_REGION" \
    --query "sort_by(Versions[?Key=='${STATE_KEY}'], &LastModified)[-1].VersionId" \
    --output text 2>/dev/null | head -n1)

  if [ -z "$latest_version" ] || [ "$latest_version" = "None" ]; then
    log "   ⚠️  No previous state version found; continuing with empty state."
    return 0
  fi

  log "   🔄 Restoring state from version $latest_version"
  aws s3api copy-object \
    --bucket "$STATE_BUCKET" \
    --key "$STATE_KEY" \
    --copy-source "${STATE_BUCKET}/${STATE_KEY}?versionId=${latest_version}" \
    --region "$STATE_REGION"
}


case "$ACTION" in
  up)
    log "🚀 Bringing up ephemeral environment: $RUN_ID"
    log "   State: s3://$STATE_BUCKET/$STATE_KEY"
    log ""

    cleanup_stale_lock "$RUN_ID"
    build_lambda_layer

    log "📦 Initializing OpenTofu backend..."
    tofu init -input=false \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_cloudwatch_log_groups
    cleanup_stale_lock "$RUN_ID"

    log "📋 Planning and applying ephemeral stack..."

    # AppSync rejects deleting pipeline functions that are still referenced by a
    # resolver. If the plan would destroy any AppSync functions, update the
    # affected pipeline resolver(s) first so the full apply can delete them.
    "$ROOT_DIR/scripts/appsync-ensure-resolver-order.sh" \
      -d "$ENV_DIR" \
      -t module.appsync.aws_appsync_resolver.create_order \
      -- -var="environment=$RUN_ID"

    tofu apply -input=false -auto-approve -var="environment=$RUN_ID"

    log ""
    log "👤 Creating ephemeral test users..."
    USER_POOL_ID=$(tofu output -raw cognito_user_pool_id)
    "$ROOT_DIR/scripts/create-ephemeral-test-users.sh" "$RUN_ID" "$USER_POOL_ID"

    log ""
    log "📤 Environment exports (eval this output):"
    log ""
    TEST_REGION="${AWS_REGION:-us-east-1}"
    COGNITO_DOMAIN=$(tofu output -raw cognito_domain)
    echo "export TEST_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    echo "export TEST_USER_POOL_ID=$USER_POOL_ID"
    echo "export TEST_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export TEST_REGION=$TEST_REGION"
    echo "export E2E_BASE_URL=http://localhost:4173"
    echo "export VITE_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    echo "export VITE_APPSYNC_REGION=$TEST_REGION"
    echo "export VITE_COGNITO_USER_POOL_ID=$USER_POOL_ID"
    echo "export VITE_COGNITO_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN"
    echo "export VITE_OAUTH_REDIRECT_SIGNIN=http://localhost:4173/"
    echo "export VITE_OAUTH_REDIRECT_SIGNOUT=http://localhost:4173/"
    echo "export ACCOUNTS_TABLE_NAME=kernelworx-accounts-ue1-${RUN_ID}"
    echo "export PROFILES_TABLE_NAME=kernelworx-profiles-ue1-${RUN_ID}"
    echo "export CAMPAIGNS_TABLE_NAME=kernelworx-campaigns-ue1-${RUN_ID}"
    echo "export ORDERS_TABLE_NAME=kernelworx-orders-ue1-${RUN_ID}"
    echo "export SHARES_TABLE_NAME=kernelworx-shares-ue1-${RUN_ID}"
    echo "export CATALOGS_TABLE_NAME=kernelworx-catalogs-ue1-${RUN_ID}"
    echo "export INVITES_TABLE_NAME=kernelworx-invites-ue1-${RUN_ID}"
    echo "export SHARED_CAMPAIGNS_TABLE_NAME=kernelworx-shared-campaigns-ue1-${RUN_ID}"
    ;;

  env)
    TEST_REGION="${AWS_REGION:-us-east-1}"
    COGNITO_DOMAIN=$(tofu output -raw cognito_domain)
    log "📤 Environment exports for existing stack: $RUN_ID"
    log ""
    echo "export TEST_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    echo "export TEST_USER_POOL_ID=$(tofu output -raw cognito_user_pool_id)"
    echo "export TEST_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export TEST_REGION=$TEST_REGION"
    echo "export E2E_BASE_URL=http://localhost:4173"
    echo "export VITE_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    echo "export VITE_APPSYNC_REGION=$TEST_REGION"
    echo "export VITE_COGNITO_USER_POOL_ID=$(tofu output -raw cognito_user_pool_id)"
    echo "export VITE_COGNITO_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN"
    echo "export VITE_OAUTH_REDIRECT_SIGNIN=http://localhost:4173/"
    echo "export VITE_OAUTH_REDIRECT_SIGNOUT=http://localhost:4173/"
    echo "export ACCOUNTS_TABLE_NAME=kernelworx-accounts-ue1-${RUN_ID}"
    echo "export PROFILES_TABLE_NAME=kernelworx-profiles-ue1-${RUN_ID}"
    echo "export CAMPAIGNS_TABLE_NAME=kernelworx-campaigns-ue1-${RUN_ID}"
    echo "export ORDERS_TABLE_NAME=kernelworx-orders-ue1-${RUN_ID}"
    echo "export SHARES_TABLE_NAME=kernelworx-shares-ue1-${RUN_ID}"
    echo "export CATALOGS_TABLE_NAME=kernelworx-catalogs-ue1-${RUN_ID}"
    echo "export INVITES_TABLE_NAME=kernelworx-invites-ue1-${RUN_ID}"
    echo "export SHARED_CAMPAIGNS_TABLE_NAME=kernelworx-shared-campaigns-ue1-${RUN_ID}"
    ;;

  down)
    log "🗑️  Tearing down ephemeral environment: $RUN_ID"
    log "   State: s3://$STATE_BUCKET/$STATE_KEY"
    log ""

    recover_state_if_missing
    cleanup_stale_lock "$RUN_ID"

    # The Lambda layer only needs to exist during `up`. For `down` we just need
    # a non-empty directory so the archive_file data source does not fail while
    # OpenTofu is destroying resources from state.
    mkdir -p "$LAYER_DIR/python"
    echo "# placeholder" > "$LAYER_DIR/python/.placeholder"

    # Re-init is required in case the workspace was cleaned since the up run.
    tofu init -input=false \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_stale_lock "$RUN_ID"

    log "💥 Destroying AWS resources..."
    if tofu destroy -input=false -auto-approve -var="environment=$RUN_ID"; then
      log "🧹 Deleting state objects..."
      aws s3 rm "s3://$STATE_BUCKET/$STATE_KEY" --region "$STATE_REGION" || true
      aws s3 rm "s3://$STATE_BUCKET/${STATE_KEY}.tflock" --region "$STATE_REGION" || true

      log ""
      log "✅ Ephemeral environment $RUN_ID torn down."
    else
      log ""
      log "❌ OpenTofu destroy failed for $RUN_ID; state objects left in place for inspection."
      exit 1
    fi
    ;;

  *)
    log "Usage: $0 <up|env|down> <run-id>"
    exit 1
    ;;
esac
