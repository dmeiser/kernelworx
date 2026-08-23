#!/bin/bash
# recover-deploy: import existing AWS resources for a run-id into OpenTofu state
# so that a subsequent `tofu apply` can succeed. Does NOT destroy anything.
# Usage: scripts/recover-deploy.sh <run-id>

set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <run-id>" >&2
  exit 1
fi

RUN_ID="$1"

# shellcheck source=/dev/null
source "$(cd "$(dirname "$0")" && pwd)/ephemeral-recover-common.sh"

load_env
cleanup_stale_lock "$RUN_ID"
init_backend "$RUN_ID"
import_ephemeral_resources "$RUN_ID"

echo ""
echo "✅ Import-only recovery for $RUN_ID complete. Run 'tofu apply' or the ephemeral test workflow next."
