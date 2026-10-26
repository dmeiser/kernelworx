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
echo "$RECORDS" | jq -c '.[]' | while read -r record; do
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
    
    # Create or update record in CloudFlare
    curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"type\": \"$type\",
            \"name\": \"$name\",
            \"content\": \"$content\",
            \"ttl\": $ttl,
            \"proxied\": false
        }" > /dev/null || echo "  ⚠️  Failed to sync $name"
done

echo ""
echo "✅ DNS sync complete!"
