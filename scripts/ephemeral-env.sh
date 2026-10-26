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

# STACK_OUTPUTS holds the single captured `tofu output -json` document. Every
# separate `tofu output` call is a fresh read of the remote S3 state, so the
# up/env branches capture the document once and read fields out of it with jq.
STACK_OUTPUTS=""

# Capture every stack output in one round trip. A failed read fails the script,
# same as the per-name `tofu output` reads it replaces.
capture_stack_outputs() {
  if ! STACK_OUTPUTS=$(tofu output -json); then
    log "❌ tofu output -json failed for run: $RUN_ID"
    exit 1
  fi
}

# Echo one string output from the captured document; empty when the output is
# absent from the state.
output_value() {
  printf '%s' "$STACK_OUTPUTS" | jq -r --arg name "$1" '.[$name].value // empty'
}

# Fail the script when an output the exports depend on is absent. The old
# single-name read form exited non-zero in exactly this case.
require_output() {
  if [ -z "$(output_value "$1")" ]; then
    log "❌ required tofu output '$1' is missing from the state for run: $RUN_ID"
    exit 1
  fi
}

# Read the stack outputs into the variables the export block emits.
load_stack_outputs() {
  capture_stack_outputs
  require_output cognito_user_pool_id
  require_output cognito_client_id
  require_output appsync_api_url
  require_output cognito_domain
  USER_POOL_ID=$(output_value cognito_user_pool_id)
  USER_POOL_CLIENT_ID=$(output_value cognito_client_id)
  APPSYNC_API_URL=$(output_value appsync_api_url)
  COGNITO_DOMAIN=$(output_value cognito_domain)
  # appsync_api_key is optional: stacks deployed before the public-orders
  # feature do not declare it, and its absence omits the API-key exports.
  APPSYNC_API_KEY=$(output_value appsync_api_key)
}

# Emit the eval-able export block from the values captured by the loader above.
print_stack_exports() {
  local test_region="${AWS_REGION:-us-east-1}"
  echo "export TEST_APPSYNC_ENDPOINT=$APPSYNC_API_URL"
  if [ -n "$APPSYNC_API_KEY" ]; then
    echo "export TEST_APPSYNC_API_KEY=$APPSYNC_API_KEY"
  fi
  echo "export TEST_USER_POOL_ID=$USER_POOL_ID"
  echo "export TEST_USER_POOL_CLIENT_ID=$USER_POOL_CLIENT_ID"
  echo "export TEST_REGION=$test_region"
  echo "export E2E_BASE_URL=http://localhost:4173"
  echo "export VITE_APPSYNC_ENDPOINT=$APPSYNC_API_URL"
  if [ -n "$APPSYNC_API_KEY" ]; then
    echo "export VITE_APPSYNC_API_KEY=$APPSYNC_API_KEY"
  fi
  echo "export VITE_APPSYNC_REGION=$test_region"
  echo "export VITE_COGNITO_USER_POOL_ID=$USER_POOL_ID"
  echo "export VITE_COGNITO_USER_POOL_CLIENT_ID=$USER_POOL_CLIENT_ID"
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

    log "📦 Building AppSync JS resolvers..."
    ensure_resolvers_built

    # AppSync rejects deleting pipeline functions or data sources that are still referenced
    # by a resolver. If the plan would destroy any AppSync functions or data sources, update
    # the affected resolver(s)/function(s) first so the full apply can delete them.
    # Keep this target list in sync with .github/workflows/deploy-shared.yml
    # (appsync-ensure-resolver-order step); a script-parity test asserts the set.
    # Targets cover all Lambda→JS migrations that removed a Lambda data source:
    #   create_order (pipeline fn set), validate_payment_method_appsync (data_source switch #299),
    #   create_seller_profile (#300), create_campaign (#301), update_my_account (#298),
    #   list_my_shares (#334), list_shares_by_profile / list_invites_by_profile (single-step
    #   owner verifier retired for the two-phase owner pair #547).
    "$ROOT_DIR/scripts/appsync-ensure-resolver-order.sh" \
      -d "$ENV_DIR" \
      -t module.appsync.aws_appsync_resolver.create_order \
      -t module.appsync.aws_appsync_function.validate_payment_method_appsync \
      -t module.appsync.aws_appsync_resolver.create_seller_profile \
      -t module.appsync.aws_appsync_resolver.create_campaign \
      -t module.appsync.aws_appsync_resolver.public_create_order \
      -t module.appsync.aws_appsync_resolver.update_my_account \
      -t module.appsync.aws_appsync_resolver.list_my_shares \
      -t module.appsync.aws_appsync_resolver.list_shares_by_profile \
      -t module.appsync.aws_appsync_resolver.list_invites_by_profile \
      -- -var="environment=$RUN_ID"

    tofu apply -input=false -auto-approve -var="environment=$RUN_ID"

    log ""
    log "👤 Creating ephemeral test users..."
    load_stack_outputs
    "$ROOT_DIR/scripts/create-ephemeral-test-users.sh" "$RUN_ID" "$USER_POOL_ID" "$USER_POOL_CLIENT_ID"

    log ""
    log "📤 Environment exports (eval this output):"
    log ""
    print_stack_exports
    ;;

  env)
    log "📤 Environment exports for existing stack: $RUN_ID"
    log ""
    load_stack_outputs
    if [ -z "$APPSYNC_API_KEY" ]; then
      log "⚠️  appsync_api_key output is absent from this stack's state; the stack has not yet deployed the public-orders feature, so TEST_APPSYNC_API_KEY/VITE_APPSYNC_API_KEY are omitted"
    fi
    print_stack_exports
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
    tofu init -input=false \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_stale_lock "$RUN_ID"
    empty_ephemeral_s3_buckets "$RUN_ID"

    log "📦 Building AppSync JS resolvers..."
    ensure_resolvers_built

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
