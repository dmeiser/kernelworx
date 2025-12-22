#!/bin/bash
# Refactor all integration tests to remove resource tracker and use direct cleanup

set -e

FILES=(
  "catalogQueries.integration.test.ts"
  "createCampaign.integration.test.ts"
  "orderOperations.integration.test.ts"
  "orderQueries.integration.test.ts"
  "profileOperations.integration.test.ts"
  "profileQueries.integration.test.ts"
  "profileSharing.integration.test.ts"
  "requestCampaignReport.integration.test.ts"
  "campaignOperations.integration.test.ts"
  "campaignQueries.integration.test.ts"
  "shareQueries.integration.test.ts"
)

cd resolvers

for file in "${FILES[@]}"; do
  echo "Processing $file..."
  
  # Backup
  cp "$file" "$file.backup"
  
  # Remove resource tracker imports and afterAll import
  sed -i "s/import { trackResource, cleanupAllTrackedResources } from '..\/setup\/resourceTracker';//" "$file"
  sed -i "s/, afterAll//" "$file"
  
  # Remove SUITE_ID constant
  sed -i "/^const SUITE_ID = /d" "$file"
  
  # Remove afterAll cleanup hook
  sed -i "/afterAll(async () => {/,/});/d" "$file"
  
  # Replace trackResource calls with cleanup mutations
  # Profile
  sed -i "s/trackResource(SUITE_ID, 'profile', \(profileId[0-9]*\));/await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: \1 } });/g" "$file"
  sed -i "s/trackResource(SUITE_ID, 'profile', profileId);/await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });/g" "$file"
  
  # Campaign
  sed -i "s/trackResource(SUITE_ID, 'campaign', \(campaignId[0-9]*\));/await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: \1 } });/g" "$file"
  sed -i "s/trackResource(SUITE_ID, 'campaign', campaignId);/await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });/g" "$file"
  
  # Order
  sed -i "s/trackResource(SUITE_ID, 'order', \(orderId[0-9]*\));/await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: \1 } });/g" "$file"
  sed -i "s/trackResource(SUITE_ID, 'order', orderId);/await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });/g" "$file"
  
  # Catalog
  sed -i "s/trackResource(SUITE_ID, 'catalog', \(catalogId[0-9]*\));/await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: \1 } });/g" "$file"
  sed -i "s/trackResource(SUITE_ID, 'catalog', catalogId);/await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });/g" "$file"
  
  # Share (uses revoke, not delete)
  sed -i "s/trackResource(SUITE_ID, 'share', { profileId, grantedToAccountId });/await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, grantedToAccountId } } });/g" "$file"
  
  echo "✓ $file refactored"
done

echo "All files refactored!"
