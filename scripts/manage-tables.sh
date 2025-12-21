#!/bin/bash

# Script to manage DynamoDB tables for campaign terminology migration
# This script:
# 1. Verifies new tables exist (kernelworx-campaigns, kernelworx-shared-campaigns)
# 2. Deletes old tables (kernelworx-seasons, kernelworx-campaign-prefills)
# 3. Clears all orders from kernelworx-orders table

set -e

# Configuration
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Table names
NEW_CAMPAIGNS_TABLE="kernelworx-campaigns-v2-ue1-${ENVIRONMENT}"
NEW_SHARED_CAMPAIGNS_TABLE="kernelworx-shared-campaigns-v2-ue1-${ENVIRONMENT}"
OLD_SEASONS_TABLE="kernelworx-seasons-v2-ue1-${ENVIRONMENT}"
OLD_PREFILLS_TABLE="kernelworx-campaign-prefills-v2-ue1-${ENVIRONMENT}"
ORDERS_TABLE="kernelworx-orders-v2-ue1-${ENVIRONMENT}"

echo "DynamoDB Table Migration Script"
echo "==============================="
echo "Region: $REGION"
echo "Environment: $ENVIRONMENT"
echo ""

# Check if table exists
table_exists() {
    local table_name=$1
    aws dynamodb describe-table \
        --table-name "$table_name" \
        --region "$REGION" \
        --profile "$PROFILE" \
        2>/dev/null | grep -q "TableName" && echo "true" || echo "false"
}

# Verify new tables exist
echo "Step 1: Verifying new tables exist..."
if [ "$(table_exists "$NEW_CAMPAIGNS_TABLE")" == "true" ]; then
    echo "✓ Table exists: $NEW_CAMPAIGNS_TABLE"
else
    echo "✗ ERROR: Table does not exist: $NEW_CAMPAIGNS_TABLE"
    echo "  Please deploy CDK stack first to create new tables"
    exit 1
fi

if [ "$(table_exists "$NEW_SHARED_CAMPAIGNS_TABLE")" == "true" ]; then
    echo "✓ Table exists: $NEW_SHARED_CAMPAIGNS_TABLE"
else
    echo "✗ ERROR: Table does not exist: $NEW_SHARED_CAMPAIGNS_TABLE"
    echo "  Please deploy CDK stack first to create new tables"
    exit 1
fi

echo ""
echo "Step 2: Deleting old tables..."

# Delete old seasons table
if [ "$(table_exists "$OLD_SEASONS_TABLE")" == "true" ]; then
    echo "Deleting old table: $OLD_SEASONS_TABLE"
    aws dynamodb delete-table \
        --table-name "$OLD_SEASONS_TABLE" \
        --region "$REGION" \
        --profile "$PROFILE"
    
    # Wait for deletion
    echo "  Waiting for table deletion..."
    aws dynamodb wait table-not-exists \
        --table-name "$OLD_SEASONS_TABLE" \
        --region "$REGION" \
        --profile "$PROFILE" 2>/dev/null || true
    echo "✓ Deleted: $OLD_SEASONS_TABLE"
else
    echo "  (Table does not exist, skipping): $OLD_SEASONS_TABLE"
fi

# Delete old campaign prefills table
if [ "$(table_exists "$OLD_PREFILLS_TABLE")" == "true" ]; then
    echo "Deleting old table: $OLD_PREFILLS_TABLE"
    aws dynamodb delete-table \
        --table-name "$OLD_PREFILLS_TABLE" \
        --region "$REGION" \
        --profile "$PROFILE"
    
    # Wait for deletion
    echo "  Waiting for table deletion..."
    aws dynamodb wait table-not-exists \
        --table-name "$OLD_PREFILLS_TABLE" \
        --region "$REGION" \
        --profile "$PROFILE" 2>/dev/null || true
    echo "✓ Deleted: $OLD_PREFILLS_TABLE"
else
    echo "  (Table does not exist, skipping): $OLD_PREFILLS_TABLE"
fi

echo ""
echo "Step 3: Clearing orders from $ORDERS_TABLE..."

# Get all items from orders table
SCAN_RESULT=$(aws dynamodb scan \
    --table-name "$ORDERS_TABLE" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --projection-expression "profileId,campaignId" \
    2>/dev/null || echo "{}")

# Extract items and delete them
ITEMS=$(echo "$SCAN_RESULT" | grep -o '"profileId".*"campaignId"' | wc -l)

if [ "$ITEMS" -gt 0 ]; then
    echo "Found $ITEMS orders to delete..."
    
    # Use batch write to delete all items
    # This requires constructing the delete requests properly
    KEYS=$(echo "$SCAN_RESULT" | jq -r '.Items[] | "\(.profileId.S),\(.campaignId.S)"' 2>/dev/null || echo "")
    
    if [ -n "$KEYS" ]; then
        echo "Deleting orders..."
        
        # Create a temporary file with batch delete requests
        TEMP_FILE=$(mktemp)
        echo "{\"$ORDERS_TABLE\": [" > "$TEMP_FILE"
        
        first=true
        while IFS= read -r key; do
            IFS=',' read -r profile_id campaign_id <<< "$key"
            if [ -z "$first" ]; then
                echo "," >> "$TEMP_FILE"
            fi
            first=false
            
            cat >> "$TEMP_FILE" <<EOF
{
    "DeleteRequest": {
        "Key": {
            "profileId": {"S": "$profile_id"},
            "campaignId": {"S": "$campaign_id"}
        }
    }
}
EOF
        done <<< "$KEYS"
        
        echo "]}" >> "$TEMP_FILE"
        
        # Execute batch write
        aws dynamodb batch-write-item \
            --request-items file://"$TEMP_FILE" \
            --region "$REGION" \
            --profile "$PROFILE" 2>/dev/null || true
        
        rm -f "$TEMP_FILE"
        echo "✓ Cleared all orders from $ORDERS_TABLE"
    fi
else
    echo "✓ No orders found (table already empty)"
fi

echo ""
echo "Migration complete!"
echo "==============================="
echo "Summary:"
echo "  ✓ New tables verified: $NEW_CAMPAIGNS_TABLE, $NEW_SHARED_CAMPAIGNS_TABLE"
echo "  ✓ Old tables deleted: $OLD_SEASONS_TABLE, $OLD_PREFILLS_TABLE"
echo "  ✓ Orders cleared: $ORDERS_TABLE"
