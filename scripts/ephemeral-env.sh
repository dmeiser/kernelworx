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

if ! validate_run_id "$RUN_ID"; then
  exit 1
fi

STATE_KEY="application/ephemeral/${RUN_ID}/terraform.tfstate"

cd "$ENV_DIR"

# Every tofu plan/apply/destroy evaluates file() against the bundled resolver
# output, so the bundle must exist before any tofu invocation.
ensure_resolvers_built() {
  (cd "$ROOT_DIR" && npm run build:resolvers)
}

build_lambda_layer() {
  log "📦 Building Lambda layer dependencies..."
  LAYER_REQ="$LAYER_DIR/requirements.txt"
  rm -rf "$LAYER_DIR"
  mkdir -p "$LAYER_DIR/python"
  (cd "$ROOT_DIR" && uv export --no-dev --format requirements.txt --no-hashes > "$LAYER_REQ")
  (cd "$ROOT_DIR" && uv pip install --requirement "$LAYER_REQ" --target "$LAYER_DIR/python")
}

case "$ACTION" in
  up)
    log "🚀 Bringing up ephemeral environment: $RUN_ID"
    log "   State: s3://$STATE_BUCKET/$STATE_KEY"
    log ""

    cleanup_stale_lock "$RUN_ID"
    build_lambda_layer

    log "📦 Initializing OpenTofu backend..."
    # -reconfigure: a prior init in this workspace may have saved another run-id's state key.
    tofu init -input=false -reconfigure \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    REGION="${AWS_REGION:-us-east-1}"
    cleanup_cloudwatch_log_groups_for_run "$RUN_ID" "$REGION"
    cleanup_stale_lock "$RUN_ID"

    log "📋 Planning and applying ephemeral stack..."

    log "📦 Building AppSync JS resolvers..."
    ensure_resolvers_built

    # AppSync rejects deleting a pipeline function or data source that a resolver or function
    # still references, and removing such a resource from the config removes the edge that
    # ordered its destroy after the referencing objects' updates. The guard plans, derives
    # every planned aws_appsync_function / aws_appsync_datasource deletion address from the
    # plan JSON, and applies everything else with `-exclude=<addr>` so those references are
    # released before the full apply below performs the deletes. The target set is derived,
    # not hand-maintained — see scripts/appsync-ensure-resolver-order.sh.
    "$ROOT_DIR/scripts/appsync-ensure-resolver-order.sh" \
      -d "$ENV_DIR" \
      -- -var="environment=$RUN_ID"

    tofu apply -input=false -auto-approve -var="environment=$RUN_ID"

    log ""
    log "👤 Creating ephemeral test users..."
    USER_POOL_ID=$(tofu output -raw cognito_user_pool_id)
    USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)
    "$ROOT_DIR/scripts/create-ephemeral-test-users.sh" "$RUN_ID" "$USER_POOL_ID" "$USER_POOL_CLIENT_ID"

    log ""
    log "📤 Environment exports (eval this output):"
    log ""
    TEST_REGION="${AWS_REGION:-us-east-1}"
    COGNITO_DOMAIN=$(tofu output -raw cognito_domain)
    APPSYNC_API_KEY=$(tofu output -raw appsync_api_key 2>/dev/null) || true
    echo "export TEST_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    if [ -n "$APPSYNC_API_KEY" ]; then
      echo "export TEST_APPSYNC_API_KEY=$APPSYNC_API_KEY"
    fi
    echo "export TEST_USER_POOL_ID=$USER_POOL_ID"
    echo "export TEST_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export TEST_REGION=$TEST_REGION"
    echo "export E2E_BASE_URL=http://localhost:4173"
    echo "export VITE_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    if [ -n "$APPSYNC_API_KEY" ]; then
      echo "export VITE_APPSYNC_API_KEY=$APPSYNC_API_KEY"
    fi
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
    # Re-init before reading output: the workspace's saved backend-config may point
    # at another run-id's state (or at nothing), so `tofu output` would fail or read
    # the wrong stack. -reconfigure points the backend at this run's own state
    # object; no state migration. Same init the `up` and `down` branches run.
    tofu init -input=false -reconfigure \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"
    TEST_REGION="${AWS_REGION:-us-east-1}"
    COGNITO_DOMAIN=$(tofu output -raw cognito_domain)
    APPSYNC_API_KEY=$(tofu output -raw appsync_api_key 2>/dev/null) || true
    log "📤 Environment exports for existing stack: $RUN_ID"
    log ""
    echo "export TEST_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    if [ -n "$APPSYNC_API_KEY" ]; then
      echo "export TEST_APPSYNC_API_KEY=$APPSYNC_API_KEY"
    else
      log "⚠️  appsync_api_key output is absent from this stack's state; the stack has not yet deployed the public-orders feature, so TEST_APPSYNC_API_KEY/VITE_APPSYNC_API_KEY are omitted"
    fi
    echo "export TEST_USER_POOL_ID=$(tofu output -raw cognito_user_pool_id)"
    echo "export TEST_USER_POOL_CLIENT_ID=$(tofu output -raw cognito_client_id)"
    echo "export TEST_REGION=$TEST_REGION"
    echo "export E2E_BASE_URL=http://localhost:4173"
    echo "export VITE_APPSYNC_ENDPOINT=$(tofu output -raw appsync_api_url)"
    if [ -n "$APPSYNC_API_KEY" ]; then
      echo "export VITE_APPSYNC_API_KEY=$APPSYNC_API_KEY"
    fi
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

    recover_state_if_missing "$RUN_ID"
    cleanup_stale_lock "$RUN_ID"

    # The Lambda layer only needs to exist during `up`. For `down` we just need
    # a non-empty directory so the archive_file data source does not fail while
    # OpenTofu is destroying resources from state.
    mkdir -p "$LAYER_DIR/python"
    echo "# placeholder" > "$LAYER_DIR/python/.placeholder"

    # Re-init is required in case the workspace was cleaned since the up run.
    # -reconfigure is required because the sweep tears down many run-ids from one
    # workspace: each passes a different state key, and OpenTofu treats that saved
    # backend-config difference as a backend change. Re-configuring from the flags
    # below points the backend at this run's own state object; no state migration.
    tofu init -input=false -reconfigure \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_stale_lock "$RUN_ID"
    empty_ephemeral_s3_buckets "$RUN_ID"

    log "📦 Building AppSync JS resolvers..."
    ensure_resolvers_built

    # AppSync rejects deleting pipeline functions or data sources that are still
    # referenced by a resolver. Run the same ordering guard as `up` (in destroy
    # mode) so resolver references are removed before the full destroy deletes
    # the functions/data sources they reference.
    "$ROOT_DIR/scripts/appsync-ensure-resolver-order.sh" \
      -d "$ENV_DIR" \
      -t module.appsync.aws_appsync_resolver.create_order \
      -t module.appsync.aws_appsync_function.validate_payment_method_appsync \
      -t module.appsync.aws_appsync_resolver.create_seller_profile \
      -t module.appsync.aws_appsync_resolver.create_campaign \
      -t module.appsync.aws_appsync_resolver.update_my_account \
      -t module.appsync.aws_appsync_resolver.list_my_shares \
      -- -destroy -var="environment=$RUN_ID"

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
