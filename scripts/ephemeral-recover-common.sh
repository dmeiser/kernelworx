#!/bin/bash
# Common helpers for ephemeral environment recovery workflows.
# Sourced by ephemeral-env.sh, recover-deploy.sh, and recover-destroy.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DIR="$ROOT_DIR/tofu/application/environments/ephemeral"
STATE_BUCKET="${STATE_BUCKET:-kernelworx-tofu-state-us-east-1-dev}"
STATE_REGION="${STATE_REGION:-us-east-1}"

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
  if ! tofu import -input=false -var="environment=$run_id" "$address" "$id"; then
    log "   ⚠️  Import of $address ($id) failed; continuing."
  fi
  return 0
}

# Empty S3 buckets (including all versions and delete markers) before teardown/destroy
# so that `tofu destroy` or bucket deletion does not fail with BucketNotEmpty.
empty_ephemeral_s3_buckets() {
  local run_id="$1"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-ue1-${run_id}"

  log "🧹 Emptying S3 buckets for run: $run_id"
  for bucket_type in static exports; do
    local bucket_name="kernelworx-${bucket_type}${suffix}"
    if aws s3api head-bucket --bucket "$bucket_name" --region "$region" 2>/dev/null; then
      log "   Emptying bucket: $bucket_name"
      python3 - "$bucket_name" "$region" <<'PY' || true
import json
import subprocess
import sys

bucket = sys.argv[1]
region = sys.argv[2]

key_marker = None
version_id_marker = None

while True:
    cmd = ["aws", "s3api", "list-object-versions", "--bucket", bucket, "--region", region, "--output", "json"]
    if key_marker:
        cmd += ["--key-marker", key_marker]
    if version_id_marker:
        cmd += ["--version-id-marker", version_id_marker]

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not res.stdout:
        break
    try:
        data = json.loads(res.stdout)
    except Exception:
        break

    objects_to_delete = []
    for v in data.get("Versions", []):
        key = v.get("Key")
        vid = v.get("VersionId")
        if key:
            entry = {"Key": key}
            if vid and vid != "null":
                entry["VersionId"] = vid
            objects_to_delete.append(entry)
    for m in data.get("DeleteMarkers", []):
        key = m.get("Key")
        vid = m.get("VersionId")
        if key:
            entry = {"Key": key}
            if vid and vid != "null":
                entry["VersionId"] = vid
            objects_to_delete.append(entry)

    if objects_to_delete:
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i:i+1000]
            del_payload = json.dumps({"Objects": batch, "Quiet": True})
            subprocess.run(
                ["aws", "s3api", "delete-objects", "--bucket", bucket, "--delete", del_payload, "--region", region],
                capture_output=True, text=True, check=False
            )

    if not data.get("IsTruncated"):
        break

    key_marker = data.get("NextKeyMarker")
    version_id_marker = data.get("NextVersionIdMarker")
    if not key_marker:
        break

# Fallback cleanup for unversioned objects
subprocess.run(
    ["aws", "s3", "rm", f"s3://{bucket}", "--recursive", "--region", region],
    capture_output=True, text=True, check=False
)
PY
    fi
  done
}

# If the state object has been deleted (e.g. by a previous failed teardown run
# that removed state before destroy succeeded), restore the latest S3 version
# so the next `tofu` operation (import, plan/apply, or destroy) can run against
# the real resource state.
recover_state_if_missing() {
  local run_id="$1"
  local state_key="application/ephemeral/${run_id}/terraform.tfstate"
  local state_url="s3://${STATE_BUCKET}/${state_key}"

  log "📦 Checking state object: $state_url"
  if aws s3api head-object --bucket "$STATE_BUCKET" --key "$state_key" --region "$STATE_REGION" >/dev/null 2>&1; then
    log "   State object exists."
    return 0
  fi

  log "   State object is missing; searching S3 versions for recoverable state..."
  local latest_version
  latest_version=$(aws s3api list-object-versions \
    --bucket "$STATE_BUCKET" \
    --prefix "$state_key" \
    --region "$STATE_REGION" \
    --query "sort_by(Versions[?Key=='${state_key}'], &LastModified)[-1].VersionId" \
    --output text 2>/dev/null | head -n1)

  if [ -z "$latest_version" ] || [ "$latest_version" = "None" ]; then
    log "   ⚠️  No previous state version found; continuing with empty state."
    return 0
  fi

  log "   🔄 Restoring state from version $latest_version"
  aws s3api copy-object \
    --bucket "$STATE_BUCKET" \
    --key "$state_key" \
    --copy-source "${STATE_BUCKET}/${state_key}?versionId=${latest_version}" \
    --region "$STATE_REGION"
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

  # S3 bucket sub-resources (versioning, encryption, public access, lifecycle, CORS).
  log "   Importing S3 bucket sub-resources..."
  import_resource "$run_id" "module.s3.aws_s3_bucket_versioning.static" "kernelworx-static${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_server_side_encryption_configuration.static" "kernelworx-static${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_public_access_block.static" "kernelworx-static${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_versioning.exports" "kernelworx-exports${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_server_side_encryption_configuration.exports" "kernelworx-exports${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_public_access_block.exports" "kernelworx-exports${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_lifecycle_configuration.exports" "kernelworx-exports${suffix}"
  import_resource "$run_id" "module.s3.aws_s3_bucket_cors_configuration.exports" "kernelworx-exports${suffix}"

  # IAM roles
  log "   Importing IAM roles..."
  local lambda_exec_role="kernelworx-lambda-exec${suffix}"
  local lambda_admin_exec_role="kernelworx-lambda-admin-exec${suffix}"
  local appsync_role="kernelworx-appsync${suffix}"
  local cognito_sms_role="kernelworx${suffix}-UserPoolsmsRole"
  local appsync_logging_role="kernelworx-api${suffix}-logs"

  import_resource "$run_id" "module.iam.aws_iam_role.lambda_execution" "$lambda_exec_role"
  import_resource "$run_id" "module.iam.aws_iam_role.lambda_admin_execution" "$lambda_admin_exec_role"
  import_resource "$run_id" "module.iam.aws_iam_role.appsync_service" "$appsync_role"
  import_resource "$run_id" "module.appsync.aws_iam_role.appsync_logging" "$appsync_logging_role"
  import_resource "$run_id" "module.iam.aws_iam_role.cognito_sms" "$cognito_sms_role"

  # IAM policy attachments and inline policies. These must be in state so that
  # `tofu destroy` can detach/delete them before removing the parent roles.
  log "   Importing IAM policies..."
  import_resource "$run_id" "module.iam.aws_iam_role_policy_attachment.lambda_basic" "${lambda_exec_role}/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_dynamodb" "${lambda_exec_role}:dynamodb-access"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_s3" "${lambda_exec_role}:s3-access"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_cloudfront" "${lambda_exec_role}:cloudfront-invalidation"

  import_resource "$run_id" "module.iam.aws_iam_role_policy_attachment.lambda_admin_basic" "${lambda_admin_exec_role}/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_admin_dynamodb" "${lambda_admin_exec_role}:dynamodb-access"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_admin_s3" "${lambda_admin_exec_role}:s3-access"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.lambda_admin_cloudfront" "${lambda_admin_exec_role}:cloudfront-invalidation"

  import_resource "$run_id" "module.iam.aws_iam_role_policy.cognito_sms" "${cognito_sms_role}:sns-publish"
  import_resource "$run_id" "module.appsync.aws_iam_role_policy.appsync_logging" "${appsync_logging_role}:appsync-logging"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.appsync_dynamodb" "${appsync_role}:dynamodb-access"
  import_resource "$run_id" "module.iam.aws_iam_role_policy.appsync_lambda" "${appsync_role}:lambda-invoke"

  # Cognito user pool, client, and prefix domain
  log "   Importing Cognito resources..."
  local user_pool_id=""
  local cognito_next_token=""
  while true; do
    local cognito_args=()
    cognito_args+=(--region "$region" --output json)
    if [ -n "$cognito_next_token" ]; then
      cognito_args+=(--starting-token "$cognito_next_token")
    fi

    local cognito_page
    cognito_page=$(aws cognito-idp list-user-pools "${cognito_args[@]}" 2>/dev/null || true)
    if [ -z "$cognito_page" ]; then
      break
    fi

    user_pool_id=$(echo "$cognito_page" | python3 -c "import sys, json; d=json.load(sys.stdin); pools=[p for p in d.get('UserPools', []) if p.get('Name')=='kernelworx-users${suffix}']; print(pools[0]['Id'] if pools else '')" 2>/dev/null || true)
    if [ -n "$user_pool_id" ]; then
      break
    fi

    cognito_next_token=$(echo "$cognito_page" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('NextToken', ''))" 2>/dev/null || true)
    [ -z "$cognito_next_token" ] && break
  done
  if [ -n "$user_pool_id" ] && [ "$user_pool_id" != "None" ]; then
    import_resource "$run_id" "module.cognito.aws_cognito_user_pool.main" "$user_pool_id"

    local client_id
    client_id=$(aws cognito-idp list-user-pool-clients --user-pool-id "$user_pool_id" --region "$region" --query "UserPoolClients[?ClientName=='KernelWorx-Web'].ClientId | [0]" --output text 2>/dev/null | head -n1 || true)
    if [ -n "$client_id" ] && [ "$client_id" != "None" ]; then
      import_resource "$run_id" "module.cognito.aws_cognito_user_pool_client.web" "${user_pool_id}/${client_id}"
    fi

    import_resource "$run_id" "module.cognito.aws_cognito_user_pool_domain.prefix[0]" "kernelworx${suffix}"

    # Cognito Lambda trigger permissions. These are state-tracked and must be
    # imported so the following apply does not try to recreate them.
    local pre_signup_name="kernelworx-pre-signup${suffix}"
    local post_auth_name="kernelworx-post-auth${suffix}"
    if aws lambda get-function --function-name "$pre_signup_name" --region "$region" >/dev/null 2>&1; then
      import_resource "$run_id" "module.cognito.aws_lambda_permission.cognito_pre_signup[0]" "AllowCognitoInvokePreSignup/${pre_signup_name}"
    fi
    if aws lambda get-function --function-name "$post_auth_name" --region "$region" >/dev/null 2>&1; then
      import_resource "$run_id" "module.cognito.aws_lambda_permission.cognito_post_auth[0]" "AllowCognitoInvokePostAuth/${post_auth_name}"
      import_resource "$run_id" "module.cognito.aws_lambda_permission.cognito_post_confirmation[0]" "AllowCognitoInvokePostConfirmation/${post_auth_name}"
    fi

    # Cognito inline policy attached to the Lambda admin execution role.
    import_resource "$run_id" "module.cognito.aws_iam_role_policy.lambda_cognito_admin" "${lambda_admin_exec_role}:cognito-admin"
  fi

  # AppSync API
  log "   Importing AppSync API..."
  local appsync_id=""
  local api_next_token=""
  while true; do
    local api_args=()
    api_args+=(--region "$region" --output json)
    if [ -n "$api_next_token" ]; then
      api_args+=(--starting-token "$api_next_token")
    fi

    local api_page
    api_page=$(aws appsync list-graphql-apis "${api_args[@]}" 2>/dev/null || true)
    if [ -z "$api_page" ]; then
      break
    fi

    appsync_id=$(echo "$api_page" | python3 -c "import sys, json; d=json.load(sys.stdin); apis=[a for a in d.get('graphqlApis', []) if a.get('name')=='kernelworx-api${suffix}']; print(apis[0]['apiId'] if apis else '')" 2>/dev/null || true)
    if [ -n "$appsync_id" ]; then
      break
    fi

    api_next_token=$(echo "$api_page" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('nextToken', ''))" 2>/dev/null || true)
    [ -z "$api_next_token" ] && break
  done
  if [ -n "$appsync_id" ] && [ "$appsync_id" != "None" ]; then
    import_resource "$run_id" "module.appsync.aws_appsync_graphql_api.main" "$appsync_id"
    import_resource "$run_id" "module.appsync.aws_cloudwatch_log_group.appsync" "/aws/appsync/apis/${appsync_id}"

    # AppSync data layer (datasources, functions, resolvers).
    import_ephemeral_appsync_resources "$run_id" "$appsync_id"
  fi

  # Lambda layer version
  log "   Importing Lambda layer version..."
  local layer_versions
  layer_versions=$(aws lambda list-layer-versions --layer-name "kernelworx-deps${suffix}" --region "$region" --query 'LayerVersions[].Version' --output text 2>/dev/null || true)
  for version in $layer_versions; do
    local layer_arn
    layer_arn=$(aws lambda get-layer-version --layer-name "kernelworx-deps${suffix}" --version-number "$version" --region "$region" --query 'LayerVersionArn' --output text 2>/dev/null || true)
    if [ -n "$layer_arn" ] && [ "$layer_arn" != "None" ]; then
      import_resource "$run_id" "module.lambda.aws_lambda_layer_version.shared" "$layer_arn"
      break
    fi
  done

  # Lambda functions
  log "   Importing Lambda functions..."
  local func_names=""
  local next_marker=""
  while true; do
    local args=()
    args+=(--region "$region" --output json)
    if [ -n "$next_marker" ]; then
      args+=(--starting-token "$next_marker")
    fi

    local page
    page=$(aws lambda list-functions "${args[@]}" 2>/dev/null || true)
    if [ -z "$page" ]; then
      break
    fi

    local names
    names=$(echo "$page" | python3 -c "import sys, json; d=json.load(sys.stdin); print('\n'.join(f['FunctionName'] for f in d.get('Functions', []) if f['FunctionName'].endswith('${suffix}')))" 2>/dev/null || true)
    if [ -n "$names" ]; then
      if [ -n "$func_names" ]; then
        func_names="$func_names
$names"
      else
        func_names="$names"
      fi
    fi

    next_marker=$(echo "$page" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('NextMarker', ''))" 2>/dev/null || true)
    [ -z "$next_marker" ] && break
  done
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

# Import AppSync datasources, functions, and resolvers for an already-discovered API.
# The Terraform resource names are parsed from the appsync module so imports stay in
# sync with configuration changes without maintaining a hand-written lookup table.
import_ephemeral_appsync_resources() {
  local run_id="$1"
  local appsync_id="$2"
  local region="${AWS_REGION:-us-east-1}"
  local env_suffix="_${run_id//-/_}"
  local module_dir="$ROOT_DIR/tofu/application/modules/appsync"

  if [ -z "$appsync_id" ] || [ "$appsync_id" = "None" ]; then
    return 0
  fi

  log "   Importing AppSync datasources, functions, and resolvers..."

  python3 - "$module_dir" "$appsync_id" "$env_suffix" "$region" "$run_id" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

module_dir = Path(sys.argv[1])
appsync_id = sys.argv[2]
env_suffix = sys.argv[3]
region = sys.argv[4]
run_id = sys.argv[5]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _import(address, resource_id):
    print(f"   📥 Importing {address} ({resource_id})", file=sys.stderr)
    subprocess.run(
        ["tofu", "import", "-input=false", f"-var=environment={run_id}", address, resource_id],
        check=False,
    )


def _parse_blocks(content, resource_type):
    pattern = re.compile(r'resource\s+"' + resource_type + r'"\s+"([^"]+)"\s*\{', re.DOTALL)
    blocks = {}
    for match in pattern.finditer(content):
        name = match.group(1)
        start = match.end() - 1
        depth = 0
        i = start
        while i < len(content):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks[name] = content[start : i + 1]
                    break
            i += 1
    return blocks


def _attr(block, key):
    match = re.search(r"\b" + key + r'\s*=\s*"([^"]+)"', block)
    return match.group(1) if match else None


content = "".join(f.read_text() + "\n" for f in sorted(module_dir.glob("*.tf")))

# Datasources: AWS name -> Terraform resource name.
ds_blocks = _parse_blocks(content, "aws_appsync_datasource")
ds_map = {name: _attr(block, "name") for name, block in ds_blocks.items()}
result = _run(
    ["aws", "appsync", "list-data-sources", "--api-id", appsync_id, "--region", region, "--output", "json"]
)
if result.returncode == 0 and result.stdout:
    for ds in json.loads(result.stdout).get("dataSources", []):
        aws_name = ds.get("name")
        for rname, cfg_name in ds_map.items():
            if cfg_name == aws_name:
                _import(f"module.appsync.aws_appsync_datasource.{rname}", f"{appsync_id}-{aws_name}")
                break

# Functions: AWS function name includes the environment suffix.
fn_blocks = _parse_blocks(content, "aws_appsync_function")
fn_map = {}
for name, block in fn_blocks.items():
    raw = _attr(block, "name")
    if raw:
        fn_map[name] = raw.replace("${local.env_suffix}", env_suffix)
result = _run(
    ["aws", "appsync", "list-functions", "--api-id", appsync_id, "--region", region, "--output", "json"]
)
if result.returncode == 0 and result.stdout:
    for fn in json.loads(result.stdout).get("functions", []):
        aws_name = fn.get("name")
        fn_id = fn.get("functionId")
        for rname, cfg_name in fn_map.items():
            if cfg_name == aws_name:
                _import(f"module.appsync.aws_appsync_function.{rname}", f"{appsync_id}-{fn_id}")
                break

# Resolvers: keyed by type + field.
res_blocks = _parse_blocks(content, "aws_appsync_resolver")
res_map = {}
for name, block in res_blocks.items():
    rtype = _attr(block, "type")
    field = _attr(block, "field")
    if rtype and field:
        res_map[name] = (rtype, field)
for rtype in {t for t, _ in res_map.values()}:
    result = _run(
        ["aws", "appsync", "list-resolvers", "--api-id", appsync_id, "--type-name", rtype,
         "--region", region, "--output", "json"]
    )
    if result.returncode != 0 or not result.stdout:
        continue
    for r in json.loads(result.stdout).get("resolvers", []):
        rt = r.get("typeName")
        field = r.get("fieldName")
        for rname, (ctype, cfield) in res_map.items():
            if ctype == rt and cfield == field:
                _import(f"module.appsync.aws_appsync_resolver.{rname}", f"{appsync_id}-{rt}-{field}")
                break
PY
}

cleanup_cloudwatch_log_groups_for_run() {
  local run_id="$1"
  log "🧹 Cleaning up CloudWatch log groups for run: $run_id"
  local region="${AWS_REGION:-us-east-1}"
  local suffix="-${run_id}"
  local log_groups=""
  local log_next_token=""

  while true; do
    local log_args=()
    log_args+=(--log-group-name-prefix "/aws/lambda/kernelworx-" --region "$region" --output json)
    if [ -n "$log_next_token" ]; then
      log_args+=(--starting-token "$log_next_token")
    fi

    local log_page
    log_page=$(aws logs describe-log-groups "${log_args[@]}" 2>/dev/null || true)
    if [ -z "$log_page" ] || [ "$log_page" = "None" ]; then
      break
    fi

    local names
    names=$(echo "$log_page" | python3 -c "import sys, json; d=json.load(sys.stdin); print('\n'.join(lg.get('logGroupName', '') for lg in d.get('logGroups', [])))")
    if [ -n "$names" ]; then
      if [ -n "$log_groups" ]; then
        log_groups="$log_groups
$names"
      else
        log_groups="$names"
      fi
    fi

    log_next_token=$(echo "$log_page" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('nextToken', ''))")
    [ -z "$log_next_token" ] && break
  done

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

# Remove a stale S3 lockfile left behind by a crashed or cancelled run.
# OpenTofu's S3 backend uses a .tflock object when use_lockfile=true.
# A lock is considered stale only when it is older than
# EPHEMERAL_LOCK_STALE_SECONDS (default 10 minutes). Hostname is logged for
# diagnostics but is NOT used as a deletion signal: a different hostname may
# still belong to an active CI runner holding a fresh lock, so we avoid
# deleting locks held by currently running jobs.
cleanup_stale_lock() {
  local run_id="$1"
  local state_key="application/ephemeral/${run_id}/terraform.tfstate"
  local lock_key="${state_key}.tflock"
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

  if [ -n "$lock_host" ]; then
    log "   Lock host: $lock_host (this host: $this_host)."
  fi

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

  log "   ⚠️  Lock appears fresh; leaving in place."
}
