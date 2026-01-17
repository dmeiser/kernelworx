#!/bin/bash

# Delete "Shared Public Catalog" test catalogs

TABLE="kernelworx-catalogs-ue1-dev"
REGION="us-east-1"

echo "🔍 Scanning for 'Shared Public Catalog' test catalogs in $TABLE..."

# Get all catalogs with name "Shared Public Catalog"
aws dynamodb scan \
  --table-name "$TABLE" \
  --region "$REGION" \
  --filter-expression "catalogName = :name" \
  --expression-attribute-values '{":name":{"S":"Shared Public Catalog"}}' \
  --output json > /tmp/shared_catalogs.json

count=$(jq '.Items | length' /tmp/shared_catalogs.json)
echo "Found $count 'Shared Public Catalog' catalogs to delete"

if [ "$count" -eq 0 ]; then
  echo "✅ No 'Shared Public Catalog' catalogs found"
  rm -f /tmp/shared_catalogs.json
  exit 0
fi

# Perform deletions and show progress
echo "Deleting catalogs..."
jq -r '.Items[] | "\(.catalogId.S)|\(.catalogName.S)"' /tmp/shared_catalogs.json | while IFS='|' read -r catalog_id name; do
  if [ -z "$catalog_id" ]; then
    continue
  fi
  
  # Delete the catalog item
  aws dynamodb delete-item \
    --table-name "$TABLE" \
    --region "$REGION" \
    --key "{\"catalogId\":{\"S\":\"$catalog_id\"}}" \
    > /dev/null 2>&1
  
  echo "  ✓ Deleted: $catalog_id"
done

# Verify deletion count
sleep 2
remaining=$(aws dynamodb scan \
  --table-name "$TABLE" \
  --region "$REGION" \
  --filter-expression "catalogName = :name" \
  --expression-attribute-values '{":name":{"S":"Shared Public Catalog"}}' \
  --output json 2>&1 | jq '.Items | length')

actual_deleted=$((count - remaining))

echo ""
echo "✅ Deleted $actual_deleted 'Shared Public Catalog' catalogs ($remaining remaining)"
rm -f /tmp/shared_catalogs.json
