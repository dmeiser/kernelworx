#!/bin/bash
# Sync Route53 DNS records to CloudFlare
# Usage: ./sync-to-cloudflare.sh ZONE_ID ENVIRONMENT

set -e

ROUTE53_ZONE_ID="${1}"
ENVIRONMENT="${2:-prod}"

if [ -z "$ROUTE53_ZONE_ID" ]; then
    echo "Usage: $0 ROUTE53_ZONE_ID [ENVIRONMENT]"
    echo ""
    echo "Examples:"
    echo "  $0 Z0668256MJ44IP3FDZCD prod"
    echo "  $0 Z06676531ERI9P4KV2JRZ dev"
    exit 1
fi

# Require CloudFlare credentials
if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
    echo "❌ CLOUDFLARE_API_TOKEN not set"
    exit 1
fi

if [ -z "$CLOUDFLARE_ZONE_ID" ]; then
    echo "❌ CLOUDFLARE_ZONE_ID not set"
    exit 1
fi

echo "🔄 Syncing DNS records"
echo "   Route53 Zone: $ROUTE53_ZONE_ID"
echo "   CloudFlare Zone: $CLOUDFLARE_ZONE_ID"
echo "   Environment: $ENVIRONMENT"
echo ""

# Fetch all Route53 records
echo "📋 Fetching Route53 records..."
# shellcheck disable=SC2016  # JMESPath literal: the backticks are aws CLI syntax, not shell command substitution
RECORDS=$(aws route53 list-resource-record-sets \
    --hosted-zone-id "$ROUTE53_ZONE_ID" \
    --query 'ResourceRecordSets[?Type!=`NS` && Type!=`SOA`]' \
    --output json)

echo "✅ Retrieved $(echo "$RECORDS" | jq 'length') records"
echo ""
echo "📤 Syncing to CloudFlare..."

# Process each record
sync_failed=0
while IFS= read -r record; do
    name=$(echo "$record" | jq -r '.Name' | sed 's/\.$//')
    type=$(echo "$record" | jq -r '.Type')
    ttl=$(echo "$record" | jq -r '.TTL // 3600')

    # Get the record value
    if echo "$record" | jq -e '.AliasTarget' > /dev/null; then
        # This is an alias - skip for now (CloudFlare uses different CNAME approach)
        echo "  ⏭️  Skipping alias record: $name ($type)"
        continue
    fi

    content=$(echo "$record" | jq -r '.ResourceRecords[0].Value // empty')

    if [ -z "$content" ]; then
        echo "  ⏭️  Skipping empty record: $name ($type)"
        continue
    fi

    echo "  📝 Syncing: $name ($type) -> $content"

    # Build the JSON payload safely (properly escaped) with jq.
    payload=$(jq -n \
        --arg type "$type" \
        --arg name "$name" \
        --arg content "$content" \
        --argjson ttl "$ttl" \
        '{type: $type, name: $name, content: $content, ttl: $ttl, proxied: false}')

    # Create or update record in CloudFlare
    response=$(curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$payload") || {
        echo "  ⚠️  Failed to sync $name (HTTP request failed)" >&2
        sync_failed=1
        continue
    }

    if ! echo "$response" | jq -e '.success == true' > /dev/null 2>&1; then
        echo "  ⚠️  Failed to sync $name" >&2
        echo "$response" | jq -r '.errors[]?.message // "unknown error"' >&2 2>/dev/null || true
        sync_failed=1
        continue
    fi

    echo "  ✅ Synced: $name"
done < <(echo "$RECORDS" | jq -c '.[]')

echo ""
if [ "$sync_failed" -ne 0 ]; then
    echo "❌ DNS sync failed" >&2
    exit 1
fi
echo "✅ DNS sync complete!"
