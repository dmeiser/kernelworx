/**
 * Centralized test resource tracker
 * 
 * Tracks all resources created during tests and ensures they're deleted in proper order.
 * Use this to avoid test data pollution and ensure clean state between test runs.
 * 
 * Usage:
 * 1. Call trackResource() whenever you create a resource (profile, campaigngn, order, etc.)
 * 2. Call cleanupAllTrackedResources() in afterAll hook
 * 3. Resources are deleted in reverse order of creation (newest first)
 * 4. Parent resources (profiles) are deleted last (after children)
 */

import { ApolloClient, gql } from '@apollo/client';
import { cleanupTestData } from './testData';

interface TrackedResource {
  type: 'profile' | 'campaigngn' | 'order' | 'catalog' | 'share' | 'invite';
  id: string; // shareId for shares, targetAccountId stored separately
  parentId?: string; // profileId for campaigngns/orders/shares/invites, null for profiles/catalogs
  client?: ApolloClient; // Client with permissions to delete this resource
  targetAccountId?: string; // Only for shares - needed for revokeShare mutation
}

// Global registry of tracked resources (per test file)
const resourceRegistry: Map<string, TrackedResource[]> = new Map();

/**
 * Get or create resource list for a test suite
 */
function getResourceList(suiteId: string): TrackedResource[] {
  if (!resourceRegistry.has(suiteId)) {
    resourceRegistry.set(suiteId, []);
  }
  return resourceRegistry.get(suiteId)!;
}

/**
 * Track a newly created resource
 * 
 * For shares: id should be shareId, targetAccountId should be provided as 5th param
 */
export function trackResource(
  suiteId: string,
  type: TrackedResource['type'],
  id: string,
  parentId?: string,
  client?: ApolloClient,
  targetAccountId?: string
): void {
  const resources = getResourceList(suiteId);
  resources.push({ type, id, parentId, client, targetAccountId });
  const details = type === 'share' && targetAccountId 
    ? ` (targetAccount: ${targetAccountId})` 
    : parentId ? ` (parent: ${parentId})` : '';
  console.log(`📝 Tracked ${type}: ${id}${details}`);
}

/**
 * Clean up all tracked resources for a test suite
 * Deletes in proper order: children first, then parents
 */
export async function cleanupAllTrackedResources(suiteId: string): Promise<void> {
  const resources = getResourceList(suiteId);
  
  if (resources.length === 0) {
    console.log('✅ No tracked resources to clean up');
    return;
  }

  console.log(`🧹 Cleaning up ${resources.length} tracked resources...`);

  // Group resources by parent
  const profiles = new Set<string>();
  const catalogs = new Set<string>();
  const childResources: TrackedResource[] = [];

  for (const resource of resources) {
    if (resource.type === 'profile') {
      profiles.add(resource.id);
    } else if (resource.type === 'catalog') {
      catalogs.add(resource.id);
    } else {
      childResources.push(resource);
    }
  }

  // Delete child resources first (orders, campaigngns, shares, invites)
  // Delete in reverse order (newest first)
  for (let i = childResources.length - 1; i >= 0; i--) {
    const resource = childResources[i];
    try {
      await deleteResource(resource);
      console.log(`✅ Deleted ${resource.type}: ${resource.id}`);
    } catch (error) {
      console.warn(`⚠️  Failed to delete ${resource.type} ${resource.id}:`, error);
    }
  }

  // Delete catalogs (no children)
  for (const catalogId of catalogs) {
    try {
      await deleteCatalog(catalogId, suiteId);
      console.log(`✅ Deleted catalog: ${catalogId}`);
    } catch (error) {
      console.warn(`⚠️  Failed to delete catalog ${catalogId}:`, error);
    }
  }

  // Delete profiles last (after all their children are gone)
  for (const profileId of profiles) {
    try {
      await deleteProfile(profileId, suiteId);
      console.log(`✅ Deleted profile: ${profileId}`);
    } catch (error) {
      console.warn(`⚠️  Failed to delete profile ${profileId}:`, error);
    }
  }

  // Clear the registry for this suite
  resourceRegistry.delete(suiteId);
  console.log('✅ All tracked resources cleaned up');
}

/**
 * Delete a single resource using GraphQL mutations
 */
async function deleteResource(resource: TrackedResource): Promise<void> {
  if (!resource.client) {
    throw new Error(`No client available to delete ${resource.type} ${resource.id}`);
  }

  const client = resource.client;

  switch (resource.type) {
    case 'order':
      await client.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId: resource.id },
      });
      break;

    case 'campaigngn':
      await client.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: resource.id },
      });
      break;

    case 'share':
      if (!resource.parentId) {
        throw new Error('Share requires parentId (profileId)');
      }
      if (!resource.targetAccountId) {
        throw new Error('Share requires targetAccountId for deletion');
      }
      await client.mutate({
        mutation: REVOKE_SHARE,
        variables: {
          input: {
            profileId: resource.parentId,
            targetAccountId: resource.targetAccountId,
          },
        },
      });
      break;

    case 'invite':
      console.log(`⏭️  Skipping invite deletion (auto-expires): ${resource.id}`);
      break;

    case 'catalog':
      await client.mutate({
        mutation: DELETE_CATALOG,
        variables: { catalogId: resource.id },
      });
      break;

    case 'profile':
      await client.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: resource.id },
      });
      break;

    default:
      console.warn(`⚠️  Unknown resource type: ${resource.type}`);
  }
}

/**
 * Delete a profile using GraphQL
 */
async function deleteProfile(profileId: string, suiteId: string): Promise<void> {
  const resources = getResourceList(suiteId);
  const profileResource = resources.find(r => r.type === 'profile' && r.id === profileId);
  
  if (!profileResource?.client) {
    console.warn(`⚠️  No client found for profile ${profileId}, skipping`);
    return;
  }

  await deleteResource(profileResource);
}

/**
 * Delete a catalog using GraphQL
 */
async function deleteCatalog(catalogId: string, suiteId: string): Promise<void> {
  const resources = getResourceList(suiteId);
  const catalogResource = resources.find(r => r.type === 'catalog' && r.id === catalogId);
  
  if (!catalogResource?.client) {
    console.warn(`⚠️  No client found for catalog ${catalogId}, skipping`);
    return;
  }

  await deleteResource(catalogResource);
}

// GraphQL Mutations for cleanup
const DELETE_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

/**
 * Get count of tracked resources (for debugging)
 */
export function getTrackedResourceCount(suiteId: string): number {
  return getResourceList(suiteId).length;
}
