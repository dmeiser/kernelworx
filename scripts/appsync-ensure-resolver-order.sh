#!/bin/bash
# Ensure AppSync resolver pipeline updates are applied before functions they
# reference are destroyed.
#
# This works around a long-standing AWS provider ordering issue where AppSync
# rejects deleting pipeline functions that are still referenced by a resolver.
# When a plan would destroy aws_appsync_function resources, this script runs a
# targeted apply for the affected pipeline resolver(s) first, so the resolver
# drops its references to the old functions before the full apply deletes them.
#
# Usage:
#   scripts/appsync-ensure-resolver-order.sh [-d <tofu-dir>] [-t <resolver-target>]... [-- <extra-tofu-args>...]
#
# Examples:
#   scripts/appsync-ensure-resolver-order.sh -d tofu/application/environments/prod \
#     -t module.appsync.aws_appsync_resolver.create_order
#
#   scripts/appsync-ensure-resolver-order.sh -t module.appsync.aws_appsync_resolver.create_order \
#     -- -var="environment=pr-123"

set -e
set -o pipefail

log() {
  echo "$@" >&2
}

usage() {
  log "Usage: $0 [-d <tofu-dir>] [-t <resolver-target>]... [-- <extra-tofu-args>...]"
  exit 1
}

TOFUDIR=""
TARGETS=()

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
      if [ -z "${2:-}" ]; then
        usage
      fi
      TARGETS+=("$2")
      shift 2
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

if [ ${#TARGETS[@]} -eq 0 ]; then
  log "ℹ️  No resolver targets specified; nothing to do."
  exit 0
fi

cd "$TOFUDIR"

PLAN_FILE="tfplan.appsync-order.tmp"

cleanup() {
  rm -f "$PLAN_FILE"
}
trap cleanup EXIT

log "📋 Checking AppSync function deletion ordering in plan..."
tofu plan -input=false -out="$PLAN_FILE" "${EXTRA_TOFU_ARGS[@]}"

# Check whether the plan would destroy any aws_appsync_function resources.
# The jq query selects resource_changes where type is aws_appsync_function and
# the actions array contains "delete".
deletions=$(tofu show -json "$PLAN_FILE" | \
  jq -r '.resource_changes[]? | select(.type == "aws_appsync_function" and (.change.actions | index("delete"))) | .address')

if [ -z "$deletions" ]; then
  log "   No AppSync function deletions planned; resolver ordering guard not needed."
  exit 0
fi

log "   Planned AppSync function deletions detected:"
echo "$deletions" | while IFS= read -r addr; do
  log "     - $addr"
done

# Print the -target addresses OpenTofu suggests after a targeted apply fails
# with "Moved resource instances excluded by targeting". Returns non-zero when
# that error is absent so callers never retry on unrelated failures.
extract_moved_targets() {
  local err
  err="$(cat)"
  if ! grep -q "Moved resource instances excluded by targeting" <<<"$err"; then
    return 1
  fi
  # The (\\.|[^"])* body tolerates backslash-escaped quotes in index keys,
  # e.g. trigger_functions[\"pre-signup\"].
  grep -oE -- '-target="(\\.|[^"])*"' <<<"$err" | sed -e 's/^-target="//' -e 's/"$//' -e 's/\\"/"/g' | sort -u
}

# Run a targeted apply for one resolver, widening the target set if OpenTofu
# refuses because moved resource instances are excluded by targeting. Such
# moves stay pending in environments whose state predates a `moved`-block
# deployment, and each retry may surface further required targets, so retry
# with the union of the known and suggested targets, bounded.
apply_resolver_target() {
  local target="$1"
  local apply_targets=("$target")
  local attempt=0
  local max_retries=3
  local apply_err suggested t s found
  while true; do
    local apply_args=()
    for t in "${apply_targets[@]}"; do
      apply_args+=("-target=$t")
    done
    if apply_err=$(tofu apply -input=false -auto-approve "${apply_args[@]}" "${EXTRA_TOFU_ARGS[@]}" 2>&1); then
      return 0
    fi
    printf '%s\n' "$apply_err" >&2
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$max_retries" ] || ! suggested=$(extract_moved_targets <<<"$apply_err") || [ -z "$suggested" ]; then
      return 1
    fi
    log "   Moved resource instances excluded by targeting; retrying with additional targets:"
    while IFS= read -r s; do
      found=0
      for t in "${apply_targets[@]}"; do
        if [ "$t" = "$s" ]; then
          found=1
          break
        fi
      done
      if [ "$found" -eq 0 ]; then
        log "     + $s"
        apply_targets+=("$s")
      fi
    done <<<"$suggested"
  done
}

for target in "${TARGETS[@]}"; do
  log "🎯 Applying resolver target first: $target"
  apply_resolver_target "$target"
done

log "   Resolver ordering guard complete."
