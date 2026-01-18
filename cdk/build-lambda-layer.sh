#!/bin/bash
# Build Lambda Layer for Python dependencies
# This reduces Lambda function deployment size by extracting common dependencies

set -e

echo "🔨 Building Lambda Layer..."

# Navigate to CDK directory
cd "$(dirname "$0")"

# Create layer directory structure
LAYER_DIR="lambda-layer/python"
rm -rf lambda-layer
mkdir -p "$LAYER_DIR"

# Install dependencies into the layer
# Lambda expects Python packages in python/ subdirectory
echo "📦 Installing Python dependencies..."
pip install \
    aioboto3 \
    boto3 \
    openpyxl \
    defusedxml \
    -t "$LAYER_DIR" \
    --upgrade \
    --quiet

# Remove unnecessary files to reduce size
echo "🧹 Cleaning up unnecessary files..."
find "$LAYER_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_DIR" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$LAYER_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true

LAYER_SIZE=$(du -sh lambda-layer | cut -f1)
echo "✅ Lambda layer built successfully (Size: $LAYER_SIZE)"
echo "   Location: lambda-layer/"
