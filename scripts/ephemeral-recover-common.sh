#!/bin/bash
# Common helpers for ephemeral environment recovery workflows.
# Sourced by recover-deploy.sh and recover-destroy.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DIR="$ROOT_DIR/tofu/application/environments/ephemeral"
STATE_BUCKET="kernelworx-tofu-state-us-east-1-dev"
STATE_REGION="us-east-1"

log() {
  echo "$@" >&2
}

load_env() {
  if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ROOT_DIR/.env"
    set +a
  fi

  if [ -z "$TF_VAR_encryption_passphrase" ]; then
    log "❌ TF_VAR_encryption_passphrase not set"
    exit 1
  fi
}

init_backend() {
  local run_id="$1"
  local state_key="application/ephemeral/${run_id}/terraform.tfstate"

  # The Lambda layer data source needs a non-empty directory during init/plan.
  mkdir -p "$ROOT_DIR/.build/lambda-layer/python"
  echo "# placeholder" > "$ROOT_DIR/.build/lambda-layer/python/.placeholder"

  log "📦 Initializing OpenTofu backend..."
  cd "$ENV_DIR"
  tofu init -input=false \
    -backend-config="key=$state_key" \
    -backend-config="bucket=$STATE_BUCKET" \
    -backend-config="region=$STATE_REGION"
}

import_resource() {
  local run_id="$1"
  local address="$2"
  local id="$3"
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    log "   ⚠️  Skipping import of $address (no id found)"
    return 0
  fi
  log "   📥 Importing $address ($id)"
  tofu import -input=false -var="environment=$run_id" "$address" "$id" || true
}

# Discover and import all known ephemeral resources for a run-id. Each import
# is allowed to fail so partial orphan sets are still handled.
import_ephemeral_resources() {
  local run_id="$1"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-ue1-${run_id}"

  log "🔄 Importing existing AWS resources for run: $run_id"

  # DynamoDB tables
  log "   Importing DynamoDB tables..."
  for table in accounts catalogs profiles campaigns orders shares invites shared-campaigns; do
    table_name="kernelworx-${table}${suffix}"
    resource_name=$(echo "$table" | tr '-' '_')
    if aws dynamodb describe-table --table-name "$table_name" --region "$region" >/dev/null 2>&1; then
      import_resource "$run_id" "module.dynamodb.aws_dynamodb_table.${resource_name}" "$table_name"
    fi
  done

  # S3 buckets
  log "   Importing S3 buckets..."
  if aws s3api head-bucket --bucket "kernelworx-static${suffix}" --region "$region" 2>/dev/null; then
    import_resource "$run_id" "module.s3.aws_s3_bucket.static" "kernelworx-static${suffix}"
  fi
  if aws s3api head-bucket --bucket "kernelworx-exports${suffix}" --region "$region" 2>/dev/null; then
    import_resource "$run_id" "module.s3.aws_s3_bucket.exports" "kernelworx-exports${suffix}"
  fi

  # IAM roles
  log "   Importing IAM roles..."
  import_resource "$run_id" "module.iam.aws_iam_role.lambda_execution" "kernelworx-lambda-exec${suffix}"
  import_resource "$run_id" "module.iam.aws_iam_role.appsync_service" "kernelworx-appsync${suffix}"
  import_resource "$run_id" "module.appsync.aws_iam_role.appsync_logging" "kernelworx-api${suffix}-logs"
  import_resource "$run_id" "module.iam.aws_iam_role.cognito_sms" "kernelworx${suffix}-UserPoolsmsRole"

  # Cognito user pool, client, and prefix domain
  log "   Importing Cognito resources..."
  local user_pool_id
  user_pool_id=$(aws cognito-idp list-user-pools --max-results 60 --region "$region" --query "UserPools[?Name=='kernelworx-users${suffix}'].Id" --output text 2>/dev/null | head -n1)
  if [ -n "$user_pool_id" ] && [ "$user_pool_id" != "None" ]; then
    import_resource "$run_id" "module.cognito.aws_cognito_user_pool.main" "$user_pool_id"

    local client_id
    client_id=$(aws cognito-idp list-user-pool-clients --user-pool-id "$user_pool_id" --region "$region" --query 'UserPoolClients[0].ClientId' --output text 2>/dev/null | head -n1)
    if [ -n "$client_id" ] && [ "$client_id" != "None" ]; then
      import_resource "$run_id" "module.cognito.aws_cognito_user_pool_client.web" "${user_pool_id}/${client_id}"
    fi

    import_resource "$run_id" "module.cognito.aws_cognito_user_pool_domain.prefix[0]" "kernelworx${suffix}"
  fi

  # AppSync API
  log "   Importing AppSync API..."
  local appsync_id
  appsync_id=$(aws appsync list-graphql-apis --region "$region" --query "graphqlApis[?name=='kernelworx-api${suffix}'].apiId" --output text 2>/dev/null | head -n1)
  if [ -n "$appsync_id" ] && [ "$appsync_id" != "None" ]; then
    import_resource "$run_id" "module.appsync.aws_appsync_graphql_api.main" "$appsync_id"
    import_resource "$run_id" "module.appsync.aws_cloudwatch_log_group.appsync" "/aws/appsync/apis/${appsync_id}"
  fi

  # Lambda layer version
  log "   Importing Lambda layer version..."
  local layer_versions
  layer_versions=$(aws lambda list-layer-versions --layer-name "kernelworx-deps${suffix}" --region "$region" --query 'LayerVersions[].Version' --output text 2>/dev/null)
  for version in $layer_versions; do
    local layer_arn
    layer_arn=$(aws lambda get-layer-version --layer-name "kernelworx-deps${suffix}" --version-number "$version" --region "$region" --query 'LayerVersionArn' --output text 2>/dev/null)
    if [ -n "$layer_arn" ] && [ "$layer_arn" != "None" ]; then
      import_resource "$run_id" "module.lambda.aws_lambda_layer_version.shared" "$layer_arn"
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
        import_resource "$run_id" "module.lambda.aws_lambda_function.trigger_functions[\"${base_name}\"]" "$func_name"
        import_resource "$run_id" "module.lambda.aws_cloudwatch_log_group.trigger_functions[\"${base_name}\"]" "/aws/lambda/${func_name}"
        ;;
      *)
        import_resource "$run_id" "module.lambda.aws_lambda_function.functions[\"${base_name}\"]" "$func_name"
        import_resource "$run_id" "module.lambda.aws_cloudwatch_log_group.functions[\"${base_name}\"]" "/aws/lambda/${func_name}"
        ;;
    esac
  done
}

cleanup_cloudwatch_log_groups_for_run() {
  local run_id="$1"
  log "🧹 Cleaning up CloudWatch log groups for run: $run_id"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-${run_id}"
  local log_groups

  log_groups=$(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/lambda/kernelworx-" \
    --region "$region" \
    --query 'logGroups[*].logGroupName' \
    --output text 2>/dev/null || true)

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

delete_state_objects() {
  local run_id="$1"
  local state_key="application/ephemeral/${run_id}/terraform.tfstate"
  log "🧹 Deleting S3 state objects..."
  aws s3 rm "s3://${STATE_BUCKET}/${state_key}" --region "$STATE_REGION" || true
  aws s3 rm "s3://${STATE_BUCKET}/${state_key}.tflock" --region "$STATE_REGION" || true
}
