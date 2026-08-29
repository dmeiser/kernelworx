#!/bin/bash
# recover-destroy: restore missing S3 state from the latest version if needed,
# then destroy orphaned AWS resources for a run-id. Imports whatever still
# exists, then runs `tofu destroy`.
# Usage: scripts/recover-destroy.sh <run-id>

set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <run-id>" >&2
  exit 1
fi

RUN_ID="$1"

# shellcheck source=/dev/null
source "$(cd "$(dirname "$0")" && pwd)/ephemeral-recover-common.sh"

load_env
recover_state_if_missing "$RUN_ID"
cleanup_stale_lock "$RUN_ID"
init_backend "$RUN_ID"
import_ephemeral_resources "$RUN_ID"
empty_ephemeral_s3_buckets "$RUN_ID"

echo "💥 Destroying recovered resources..."
if tofu destroy -input=false -auto-approve -var="environment=$RUN_ID"; then
  delete_state_objects "$RUN_ID"
  cleanup_cloudwatch_log_groups_for_run "$RUN_ID"
  echo ""
  echo "✅ Orphan recovery and destroy for $RUN_ID complete."
else
  echo ""
  echo "❌ OpenTofu destroy failed for $RUN_ID; state objects left in place for inspection."
  exit 1
fi
