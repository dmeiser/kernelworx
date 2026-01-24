#!/bin/bash

# Delete all test managed catalogs (those created during test runs)

TABLE="kernelworx-catalogs-ue1-dev"
REGION="us-east-1"

echo "🔍 Scanning for all test catalogs in $TABLE..."

# Get all catalogs matching test pattern
aws dynamodb scan \
  --table-name "$TABLE" \
  --region "$REGION" \
  --filter-expression "begins_with(catalogName, :prefix)" \
  --expression-attribute-values "{\":prefix\":{\"S\":\"TEST-\"}}" \
  --output json > /tmp/test_catalogs.json

count=$(jq '.Items | length' /tmp/test_catalogs.json)
echo "Found $count test catalogs to delete"

if [ "$count" -eq 0 ]; then
  echo "✅ No test catalogs found"
  rm -f /tmp/test_catalogs.json
  exit 0
fi

# Perform deletions and show progress
echo "Deleting catalogs..."
deleted=0
jq -r '.Items[] | "\(.catalogId.S)|\(.catalogName.S)"' /tmp/test_catalogs.json | while IFS='|' read -r catalog_id name; do
  if [ -z "$catalog_id" ]; then
    continue
  fi
  
  # Delete the catalog item
  aws dynamodb delete-item \
    --table-name "$TABLE" \
    --region "$REGION" \
    --key "{\"catalogId\":{\"S\":\"$catalog_id\"}}" \
    > /dev/null 2>&1
  
  echo "  ✓ Deleted: $name"
done

# Verify deletion count
sleep 2
remaining=$(aws dynamodb scan \
  --table-name "$TABLE" \
  --region "$REGION" \
  --filter-expression "begins_with(catalogName, :prefix)" \
  --expression-attribute-values "{\":prefix\":{\"S\":\"TEST-\"}}" \
  --output json 2>&1 | jq '.Items | length')

actual_deleted=$((count - remaining))

echo ""
echo "✅ Deleted $actual_deleted test catalogs ($remaining remaining)"
rm -f /tmp/test_catalogs.json
