#!/bin/bash
# Ensure AppSync reference-releasing updates land before the main apply destroys
# aws_appsync_function / aws_appsync_datasource resources.
#
# AWS rejects deleting an AppSync pipeline function that a resolver still
# references, and deleting a data source that a function or resolver still
# references. When a change removes such a resource from the configuration, the
# config edge that ordered the destroy after the referencing objects' updates is
# removed with it, and OpenTofu walks the destroy nodes first: the apply aborts
# before a single reference-releasing update runs. That is the #750 prod outage
# (13 consecutive failed deploys) and the earlier #298-#301 Lambda-to-JS
# migrations.
#
# The guard therefore derives its own targets from the plan instead of relying
# on a hand-maintained address list: it plans, collects every planned
# aws_appsync_function / aws_appsync_datasource deletion address, and runs
# `tofu apply -exclude=<addr>` for each. OpenTofu then applies everything EXCEPT
# those deferred destroys, so the reference-releasing updates land while the
# deletions remain for the caller's normal apply. Verified against OpenTofu
# 1.13.1: a resource re-pointed away from an excluded object in the new
# configuration is still applied, and unlike -target, -exclude never trips the
# "Moved resource instances excluded by targeting" refusal, so no target-widening
# retry is needed.
#
# Usage:
#   scripts/appsync-ensure-resolver-order.sh [-d <tofu-dir>] [-- <extra-tofu-args>...]
#
# Examples:
#   scripts/appsync-ensure-resolver-order.sh -d tofu/application/environments/prod
#
#   scripts/appsync-ensure-resolver-order.sh -d tofu/application/environments/ephemeral \
#     -- -var="environment=pr-123"

set -e
set -o pipefail

log() {
  echo "$@" >&2
}

usage() {
  log "Usage: $0 [-d <tofu-dir>] [-- <extra-tofu-args>...]"
  exit 1
}

TOFUDIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    -d)
      if [ -z "${2:-}" ]; then
        usage
      fi
      TOFUDIR="$2"
      shift 2
      ;;
    -t)
      # Retired deliberately: a hand-maintained target list is how the ordering
      # bug survived every previous fix. Fail loudly rather than ignore a stale
      # call site.
      log "❌ -t is no longer supported: the guard derives its exclusions from the plan."
      usage
      ;;
    --)
      shift
      break
      ;;
    -*)
      usage
      ;;
    *)
      break
      ;;
  esac
done

EXTRA_TOFU_ARGS=("$@")

if [ -z "$TOFUDIR" ]; then
  TOFUDIR="$(pwd)"
fi

cd "$TOFUDIR"

PLAN_FILE="tfplan.appsync-order.tmp"

cleanup() {
  rm -f "$PLAN_FILE"
}
trap cleanup EXIT

log "📋 Checking AppSync function/datasource deletion ordering in plan..."
tofu plan -input=false -out="$PLAN_FILE" "${EXTRA_TOFU_ARGS[@]}"

# The objects AWS refuses to delete while something still references them:
# resource_changes of both AppSync types whose actions contain "delete"
# (a replacement's delete is deferred the same way and lands in the main apply).
deletions=$(tofu show -json "$PLAN_FILE" | \
  jq -r '.resource_changes[]? | select((.type == "aws_appsync_function" or .type == "aws_appsync_datasource") and (.change.actions | index("delete"))) | .address')

if [ -z "$deletions" ]; then
  log "   No AppSync function/datasource deletions planned; resolver ordering guard not needed."
  exit 0
fi

EXCLUDE_ARGS=()
log "   Planned AppSync function/datasource deletions detected; deferring to the main apply:"
while IFS= read -r addr; do
  log "     - $addr"
  EXCLUDE_ARGS+=("-exclude=$addr")
done <<<"$deletions"

# Everything the reference-releasing apply will do, named from the same plan the
# exclusions came from, so the log states what was applied and what was deferred.
applied=$(tofu show -json "$PLAN_FILE" | \
  jq -r '[.resource_changes[]? | select(.change.actions | index("delete") | not) | select(.change.actions != ["no-op"]) | .address] | length')

log "🎯 Applying $applied planned change(s) with the deletions above excluded..."
if ! tofu apply -input=false -auto-approve "${EXCLUDE_ARGS[@]}" "${EXTRA_TOFU_ARGS[@]}"; then
  log "❌ Reference-releasing apply failed; aborting before the main apply touches anything."
  exit 1
fi

log "   Resolver ordering guard complete: reference-releasing updates applied, the deletions above remain for the main apply."
