#!/bin/bash
# Manage ephemeral per-run test environments.
#
# Usage:
#   scripts/ephemeral-env.sh up <run-id>
#   eval $(scripts/ephemeral-env.sh env <run-id>)
#   scripts/ephemeral-env.sh down <run-id>
#   scripts/ephemeral-env.sh cleanup-orphans <run-id>
#   scripts/ephemeral-env.sh recover-orphans <run-id>
#
# The script sources the repository root .env for AWS credentials/profile and
# the OpenTofu state encryption passphrase, same as deploy.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DIR="$ROOT_DIR/tofu/application/environments/ephemeral"
STATE_BUCKET="kernelworx-tofu-state-us-east-1-dev"
STATE_REGION="us-east-1"

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
  log "Usage: $0 <up|env|down|cleanup-orphans|recover-orphans> <run-id>"
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
  LAYER_DIR="$ROOT_DIR/.build/lambda-layer"
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
    --query 'Versions[?IsLatest==`true`].VersionId' \
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

# Remove a stale S3 lockfile left behind by a crashed or cancelled run.
# OpenTofu's S3 backend uses a .tflock object when use_lockfile=true.
# A lock from a different host is always considered stale (each CI run gets a
# fresh runner). A lock from the same host is removed only when it is older
# than EPHEMERAL_LOCK_STALE_SECONDS (default 10 minutes).
cleanup_stale_lock() {
  local lock_key="${STATE_KEY}.tflock"
  local lock_url="s3://${STATE_BUCKET}/${lock_key}"
  local stale_threshold_seconds="${EPHEMERAL_LOCK_STALE_SECONDS:-600}"

  log "🔒 Checking for stale state lock: $lock_url"

  if ! aws s3api head-object --bucket "$STATE_BUCKET" --key "$lock_key" --region "$STATE_REGION" >/dev/null 2>&1; then
    log "   No lock object found."
    return 0
  fi

  local lock_info
  lock_info=$(aws s3 cp "$lock_url" - --region "$STATE_REGION" 2>/dev/null || true)
  if [ -z "$lock_info" ]; then
    log "   ⚠️  Lock object exists but content could not be read; leaving it in place."
    return 0
  fi

  log "   Lock info: $lock_info"

  local lock_created lock_who lock_host
  lock_created=$(echo "$lock_info" | python3 -c 'import sys, json; print(json.load(sys.stdin).get("Created", ""))' 2>/dev/null || true)
  lock_who=$(echo "$lock_info" | python3 -c 'import sys, json; print(json.load(sys.stdin).get("Who", ""))' 2>/dev/null || true)
  lock_host="${lock_who#*@}"
  local this_host
  this_host=$(hostname)

  # A lock created by a different host cannot belong to the current run, so
  # treat it as stale. This handles CI runners that crash or are cancelled.
  if [ -n "$lock_host" ] && [ "$lock_host" != "$this_host" ]; then
    log "   🗑️  Lock belongs to a different host ($lock_host != $this_host); removing as stale."
    aws s3 rm "$lock_url" --region "$STATE_REGION" || true
    return 0
  fi

  # Same host: fall back to age-based check to avoid deleting a lock held by a
  # concurrent local process.
  if [ -n "$lock_created" ]; then
    local lock_age_seconds
    lock_age_seconds=$(python3 - <<PY
from datetime import datetime, timezone
import sys
try:
    last = datetime.fromisoformat("${lock_created}".replace('Z', '+00:00'))
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    print(int((datetime.now(timezone.utc) - last).total_seconds()))
except Exception:
    print(-1)
PY
    )

    if [ "$lock_age_seconds" -ge 0 ]; then
      log "   Lock age: ${lock_age_seconds}s (threshold: ${stale_threshold_seconds}s)."
      if [ "$lock_age_seconds" -gt "$stale_threshold_seconds" ]; then
        log "   🗑️  Lock is older than threshold; removing as stale."
        aws s3 rm "$lock_url" --region "$STATE_REGION" || true
        return 0
      fi
    fi
  fi

  log "   ⚠️  Lock appears fresh and from this host; leaving in place."
}

# Best-effort deletion of AWS resources left behind when the OpenTofu state is
# missing or corrupt. Resource names follow the conventions used by the
# ephemeral stack modules. Errors are logged and ignored so one stuck resource
# does not prevent cleaning the rest.
cleanup_orphaned_resources() {
  log "🧹 Cleaning up orphaned AWS resources for run: $RUN_ID"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-ue1-${RUN_ID}"

  # 1. AppSync API
  log "   Deleting AppSync API..."
  local appsync_id
  appsync_id=$(aws appsync list-graphql-apis --region "$region" --query "graphqlApis[?name=='kernelworx-api${suffix}'].apiId" --output text 2>/dev/null | head -n1)
  if [ -n "$appsync_id" ] && [ "$appsync_id" != "None" ]; then
    log "     Deleting AppSync API $appsync_id"
    aws appsync delete-graphql-api --api-id "$appsync_id" --region "$region" || true
  fi

  # 2. Cognito User Pool
  log "   Deleting Cognito user pool..."
  local user_pool_id
  user_pool_id=$(aws cognito-idp list-user-pools --max-results 60 --region "$region" --query "UserPools[?Name=='kernelworx-users${suffix}'].Id" --output text 2>/dev/null | head -n1)
  if [ -n "$user_pool_id" ] && [ "$user_pool_id" != "None" ]; then
    log "     Deleting user pool $user_pool_id"
    aws cognito-idp delete-user-pool --user-pool-id "$user_pool_id" --region "$region" || true
  fi

  # 3. Lambda functions
  log "   Deleting Lambda functions..."
  local func_names
  func_names=$(aws lambda list-functions --region "$region" --query "Functions[?ends_with(FunctionName,'${suffix}')].FunctionName" --output text 2>/dev/null)
  for func_name in $func_names; do
    log "     Deleting Lambda function $func_name"
    aws lambda delete-function --function-name "$func_name" --region "$region" || true
  done

  # 4. Lambda layer versions
  log "   Deleting Lambda layer versions..."
  local layer_name="kernelworx-deps${suffix}"
  local layer_versions
  layer_versions=$(aws lambda list-layer-versions --layer-name "$layer_name" --region "$region" --query 'LayerVersions[].Version' --output text 2>/dev/null)
  for version in $layer_versions; do
    log "     Deleting layer version $layer_name:$version"
    aws lambda delete-layer-version --layer-name "$layer_name" --version-number "$version" --region "$region" || true
  done

  # 5. IAM roles (inline policies and managed attachments are removed with the role)
  log "   Deleting IAM roles..."
  local role_names=(
    "kernelworx-lambda-exec${suffix}"
    "kernelworx-appsync${suffix}"
    "kernelworx-api${suffix}-logs"
    "kernelworx${suffix}-UserPoolsmsRole"
  )
  for role_name in "${role_names[@]}"; do
    if aws iam get-role --role-name "$role_name" --region "$region" >/dev/null 2>&1; then
      log "     Deleting IAM role $role_name"
      aws iam delete-role --role-name "$role_name" --region "$region" || true
    fi
  done

  # 6. S3 buckets (must be emptied first)
  log "   Deleting S3 buckets..."
  local bucket_names=(
    "kernelworx-static${suffix}"
    "kernelworx-exports${suffix}"
  )
  for bucket_name in "${bucket_names[@]}"; do
    if aws s3api head-bucket --bucket "$bucket_name" --region "$region" 2>/dev/null; then
      log "     Emptying and deleting bucket $bucket_name"
      aws s3 rm "s3://${bucket_name}" --recursive --region "$region" || true
      aws s3api delete-bucket --bucket "$bucket_name" --region "$region" || true
    fi
  done

  # 7. DynamoDB tables
  log "   Deleting DynamoDB tables..."
  local table_names=(
    "kernelworx-accounts${suffix}"
    "kernelworx-catalogs${suffix}"
    "kernelworx-profiles${suffix}"
    "kernelworx-campaigns${suffix}"
    "kernelworx-orders${suffix}"
    "kernelworx-shares${suffix}"
    "kernelworx-invites${suffix}"
    "kernelworx-shared-campaigns${suffix}"
  )
  for table_name in "${table_names[@]}"; do
    if aws dynamodb describe-table --table-name "$table_name" --region "$region" >/dev/null 2>&1; then
      log "     Deleting DynamoDB table $table_name"
      aws dynamodb delete-table --table-name "$table_name" --region "$region" || true
    fi
  done

  # 8. CloudWatch log groups
  log "   Deleting CloudWatch log groups..."
  cleanup_cloudwatch_log_groups

  # 9. State objects (including any leftover lock)
  log "   Deleting S3 state objects..."
  aws s3 rm "s3://${STATE_BUCKET}/${STATE_KEY}" --region "$STATE_REGION" || true
  aws s3 rm "s3://${STATE_BUCKET}/${STATE_KEY}.tflock" --region "$STATE_REGION" || true

  log ""
  log "✅ Orphan cleanup for $RUN_ID complete."
}

# Discover orphaned AWS resources left behind when state is missing/corrupt,
# import them into the ephemeral OpenTofu state one by one, then run
# `tofu destroy` so they are removed through Terraform. Each import is allowed
# to fail so partial orphan sets are still handled.
recover_orphans() {
  log "🔄 Recovering orphaned resources into state for run: $RUN_ID"
  log "   State: s3://$STATE_BUCKET/$STATE_KEY"
  log ""

  local region="${AWS_REGION:-us-east-1}"
  local suffix="-ue1-${RUN_ID}"

  # The Lambda layer data source needs a non-empty directory during init/plan.
  mkdir -p "$ROOT_DIR/.build/lambda-layer/python"
  echo "# placeholder" > "$ROOT_DIR/.build/lambda-layer/python/.placeholder"

  log "📦 Initializing OpenTofu backend..."
  tofu init -input=false \
    -backend-config="key=$STATE_KEY" \
    -backend-config="bucket=$STATE_BUCKET" \
    -backend-config="region=$STATE_REGION"

  # Helper to run tofu import safely
  import_resource() {
    local address="$1"
    local id="$2"
    if [ -z "$id" ] || [ "$id" = "None" ]; then
      log "   ⚠️  Skipping import of $address (no id found)"
      return 0
    fi
    log "   📥 Importing $address ($id)"
    tofu import -input=false -var="environment=$RUN_ID" "$address" "$id" || true
  }

  # DynamoDB tables
  log "   Importing DynamoDB tables..."
  for table in accounts catalogs profiles campaigns orders shares invites shared-campaigns; do
    table_name="kernelworx-${table}${suffix}"
    resource_name=$(echo "$table" | tr '-' '_')
    if aws dynamodb describe-table --table-name "$table_name" --region "$region" >/dev/null 2>&1; then
      import_resource "module.dynamodb.aws_dynamodb_table.${resource_name}" "$table_name"
    fi
  done

  # S3 buckets
  log "   Importing S3 buckets..."
  if aws s3api head-bucket --bucket "kernelworx-static${suffix}" --region "$region" 2>/dev/null; then
    import_resource "module.s3.aws_s3_bucket.static" "kernelworx-static${suffix}"
  fi
  if aws s3api head-bucket --bucket "kernelworx-exports${suffix}" --region "$region" 2>/dev/null; then
    import_resource "module.s3.aws_s3_bucket.exports" "kernelworx-exports${suffix}"
  fi

  # IAM roles
  log "   Importing IAM roles..."
  import_resource "module.iam.aws_iam_role.lambda_execution" "kernelworx-lambda-exec${suffix}"
  import_resource "module.iam.aws_iam_role.appsync_service" "kernelworx-appsync${suffix}"
  import_resource "module.appsync.aws_iam_role.appsync_logging" "kernelworx-api${suffix}-logs"
  import_resource "module.iam.aws_iam_role.cognito_sms" "kernelworx${suffix}-UserPoolsmsRole"

  # Cognito user pool, client, and prefix domain
  log "   Importing Cognito resources..."
  local user_pool_id
  user_pool_id=$(aws cognito-idp list-user-pools --max-results 60 --region "$region" --query "UserPools[?Name=='kernelworx-users${suffix}'].Id" --output text 2>/dev/null | head -n1)
  if [ -n "$user_pool_id" ] && [ "$user_pool_id" != "None" ]; then
    import_resource "module.cognito.aws_cognito_user_pool.main" "$user_pool_id"

    local client_id
    client_id=$(aws cognito-idp list-user-pool-clients --user-pool-id "$user_pool_id" --region "$region" --query 'UserPoolClients[0].ClientId' --output text 2>/dev/null | head -n1)
    if [ -n "$client_id" ] && [ "$client_id" != "None" ]; then
      import_resource "module.cognito.aws_cognito_user_pool_client.web" "${user_pool_id}/${client_id}"
    fi

    import_resource "module.cognito.aws_cognito_user_pool_domain.prefix[0]" "kernelworx${suffix}"
  fi

  # AppSync API
  log "   Importing AppSync API..."
  local appsync_id
  appsync_id=$(aws appsync list-graphql-apis --region "$region" --query "graphqlApis[?name=='kernelworx-api${suffix}'].apiId" --output text 2>/dev/null | head -n1)
  if [ -n "$appsync_id" ] && [ "$appsync_id" != "None" ]; then
    import_resource "module.appsync.aws_appsync_graphql_api.main" "$appsync_id"
    import_resource "module.appsync.aws_cloudwatch_log_group.appsync" "/aws/appsync/apis/${appsync_id}"
  fi

  # Lambda layer version
  log "   Importing Lambda layer version..."
  local layer_versions
  layer_versions=$(aws lambda list-layer-versions --layer-name "kernelworx-deps${suffix}" --region "$region" --query 'LayerVersions[].Version' --output text 2>/dev/null)
  for version in $layer_versions; do
    local layer_arn
    layer_arn=$(aws lambda get-layer-version --layer-name "kernelworx-deps${suffix}" --version-number "$version" --region "$region" --query 'LayerVersionArn' --output text 2>/dev/null)
    if [ -n "$layer_arn" ] && [ "$layer_arn" != "None" ]; then
      import_resource "module.lambda.aws_lambda_layer_version.shared" "$layer_arn"
      break
    fi
  done

  # Lambda functions
  log "   Importing Lambda functions..."
  local func_names
  func_names=$(aws lambda list-functions --region "$region" --query "Functions[?ends_with(FunctionName,'${suffix}')].FunctionName" --output text 2>/dev/null)
  for func_name in $func_names; do
    local base_name
    base_name=$(echo "$func_name" | sed "s/^kernelworx-//;s/${suffix}$//")
    case "$base_name" in
      post-auth|pre-signup)
        import_resource "module.lambda.aws_lambda_function.trigger_functions[\"${base_name}\"]" "$func_name"
        ;;
      *)
        import_resource "module.lambda.aws_lambda_function.main[\"${base_name}\"]" "$func_name"
        ;;
    esac
  done

  log "💥 Destroying recovered resources..."
  if tofu destroy -input=false -auto-approve -var="environment=$RUN_ID"; then
    log "🧹 Deleting state objects..."
    aws s3 rm "s3://$STATE_BUCKET/$STATE_KEY" --region "$STATE_REGION" || true
    aws s3 rm "s3://$STATE_BUCKET/${STATE_KEY}.tflock" --region "$STATE_REGION" || true

    # Clean up auto-created CloudWatch log groups too
    cleanup_cloudwatch_log_groups

    log ""
    log "✅ Orphan recovery and destroy for $RUN_ID complete."
  else
    log ""
    log "❌ OpenTofu destroy failed for $RUN_ID; state objects left in place for inspection."
    exit 1
  fi
}

case "$ACTION" in
  up)
    log "🚀 Bringing up ephemeral environment: $RUN_ID"
    log "   State: s3://$STATE_BUCKET/$STATE_KEY"
    log ""

    cleanup_stale_lock
    build_lambda_layer

    log "📦 Initializing OpenTofu backend..."
    tofu init -input=false \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_cloudwatch_log_groups
    cleanup_stale_lock

    log "📋 Planning and applying ephemeral stack..."
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
    cleanup_stale_lock

    # The Lambda layer only needs to exist during `up`. For `down` we just need
    # a non-empty directory so the archive_file data source does not fail while
    # OpenTofu is destroying resources from state.
    mkdir -p "$ROOT_DIR/.build/lambda-layer/python"
    echo "# placeholder" > "$ROOT_DIR/.build/lambda-layer/python/.placeholder"

    # Re-init is required in case the workspace was cleaned since the up run.
    tofu init -input=false \
      -backend-config="key=$STATE_KEY" \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=$STATE_REGION"

    cleanup_stale_lock

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

  cleanup-orphans)
    cleanup_orphaned_resources
    ;;

  recover-orphans)
    recover_orphans
    ;;

  *)
    log "Usage: $0 <up|env|down|cleanup-orphans|recover-orphans> <run-id>"
    exit 1
    ;;
esac
