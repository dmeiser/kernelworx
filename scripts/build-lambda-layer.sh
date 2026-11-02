#!/bin/bash
# Build the dependencies Lambda layer shared by all deploy paths.
#
# Usage:
#   scripts/build-lambda-layer.sh [layer_dir]
#
# LAYER_DIR may also be overridden via KERNELWORX_TEST_LAYER_DIR so unit tests
# can redirect the build output without polluting the worktree.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LAYER_DIR="${KERNELWORX_TEST_LAYER_DIR:-${1:-$ROOT_DIR/.build/lambda-layer}}"
LAYER_REQ="$LAYER_DIR/requirements.txt"

echo "📦 Building Lambda layer dependencies..."
rm -rf "$LAYER_DIR"
mkdir -p "$LAYER_DIR/python"

(cd "$ROOT_DIR" && uv export --no-dev --format requirements.txt --no-hashes > "$LAYER_REQ")
(cd "$ROOT_DIR" && uv pip install --requirement "$LAYER_REQ" --target "$LAYER_DIR/python")
