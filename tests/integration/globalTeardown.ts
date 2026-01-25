/**
 * Global teardown for integration tests.
 * 
 * This file runs AFTER all test suites complete (or if tests are interrupted).
 * It cleans up any orphaned test data that wasn't deleted by individual tests.
 * 
 * Why this exists:
 * - When tests fail, their afterAll cleanup code may not run
 * - When tests are interrupted (Ctrl+C), cleanup doesn't happen
 * - Rate limits (e.g., 50 shared campaigns max) can block future test runs
 */

import { DynamoDBClient, ScanCommand, DeleteItemCommand, QueryCommand, GetItemCommand } from '@aws-sdk/client-dynamodb';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const dynamodb = new DynamoDBClient({ region: 'us-east-1' });

// Table names from environment or defaults
const SHARED_CAMPAIGNS_TABLE = process.env.SHARED_CAMPAIGNS_TABLE_NAME || 'kernelworx-shared-campaigns-ue1-dev';
const PROFILES_TABLE = process.env.PROFILES_TABLE_NAME || 'kernelworx-profiles-ue1-dev';
const CAMPAIGNS_TABLE = process.env.CAMPAIGNS_TABLE_NAME || 'kernelworx-campaigns-ue1-dev';
const ORDERS_TABLE = process.env.ORDERS_TABLE_NAME || 'kernelworx-orders-ue1-dev';
const CATALOGS_TABLE = process.env.CATALOGS_TABLE_NAME || 'kernelworx-catalogs-ue1-dev';
const SHARES_TABLE = process.env.SHARES_TABLE_NAME || 'kernelworx-shares-ue1-dev';
const INVITES_TABLE = process.env.INVITES_TABLE_NAME || 'kernelworx-invites-ue1-dev';
const ACCOUNTS_TABLE = process.env.ACCOUNTS_TABLE_NAME || 'kernelworx-accounts-ue1-dev';

// Test user emails (from .env)
const TEST_USER_EMAILS = [
  process.env.TEST_OWNER_EMAIL,
  process.env.TEST_CONTRIBUTOR_EMAIL,
  process.env.TEST_READONLY_EMAIL,
].filter(Boolean) as string[];

// Cache for test account IDs (populated on first use)
let TEST_ACCOUNT_IDS: string[] = [];

/**
 * Get account IDs for test users by looking up their emails.
 * Results are cached to avoid repeated queries.
 */
async function getTestAccountIds(): Promise<string[]> {
  if (TEST_ACCOUNT_IDS.length > 0) {
    return TEST_ACCOUNT_IDS;
  }

  for (const email of TEST_USER_EMAILS) {
    try {
      const result = await dynamodb.send(new QueryCommand({
        TableName: ACCOUNTS_TABLE,
        IndexName: 'email-index',
        KeyConditionExpression: 'email = :email',
        ExpressionAttributeValues: {
          ':email': { S: email },
        },
        ProjectionExpression: 'accountId',
      }));

      const accountId = result.Items?.[0]?.accountId?.S;
      if (accountId) {
        TEST_ACCOUNT_IDS.push(accountId);
      }
    } catch (error) {
      console.error(`  Failed to lookup account for ${email}:`, error);
    }
  }

  return TEST_ACCOUNT_IDS;
}

async function cleanupSharedCampaigns(): Promise<number> {
  console.log('  Scanning campaign shared campaigns table...');
  
  const testAccountIds = await getTestAccountIds();
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: SHARED_CAMPAIGNS_TABLE,
    ProjectionExpression: 'sharedCampaignCode, SK, createdBy',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const sharedCampaignCode = item.sharedCampaignCode?.S;
    const sk = item.SK?.S;
    const createdBy = item.createdBy?.S;
    
    // Only delete items created by test accounts
    if (sharedCampaignCode && sk && testAccountIds.includes(createdBy || '')) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: SHARED_CAMPAIGNS_TABLE,
          Key: {
            sharedCampaignCode: { S: sharedCampaignCode },
            SK: { S: sk },
          },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete shared campaign ${sharedCampaignCode}:`, error);
      }
    }
  }
  
  return deleted;
}

async function cleanupTestProfiles(): Promise<number> {
  console.log('  Querying profiles table by test user ownership...');
  
  const testAccountIds = await getTestAccountIds();
  let deleted = 0;
  
  // Query profiles for each test account (V2 schema: PK=ownerAccountId, SK=profileId)
  for (const accountId of testAccountIds) {
    try {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: PROFILES_TABLE,
        KeyConditionExpression: 'ownerAccountId = :ownerAccountId',
        ExpressionAttributeValues: {
          ':ownerAccountId': { S: accountId },
        },
        ProjectionExpression: 'ownerAccountId, profileId, sellerName',
      }));
      
      const items = queryResult.Items || [];
      console.log(`    Found ${items.length} profile(s) for account ${accountId}`);
      
      for (const item of items) {
        const ownerAccountId = item.ownerAccountId?.S;
        const profileId = item.profileId?.S;
        const sellerName = item.sellerName?.S;
        
        if (ownerAccountId && profileId) {
          try {
            await dynamodb.send(new DeleteItemCommand({
              TableName: PROFILES_TABLE,
              Key: {
                ownerAccountId: { S: ownerAccountId },
                profileId: { S: profileId },
              },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete profile ${sellerName} (${profileId}):`, error);
          }
        }
      }
    } catch (error) {
      console.error(`  Failed to query profiles for account ${accountId}:`, error);
    }
  }
  
  return deleted;
}

async function cleanupTestCatalogs(): Promise<number> {
  console.log('  Querying catalogs table by test user ownership...');
  
  const testAccountIds = await getTestAccountIds();
  let deleted = 0;
  
  // Query catalogs for each test account using ownerAccountId-index GSI
  for (const accountId of testAccountIds) {
    try {
      console.log(`    Querying catalogs for account: ${accountId}`);
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: CATALOGS_TABLE,
        IndexName: 'ownerAccountId-index',
        KeyConditionExpression: 'ownerAccountId = :ownerAccountId',
        ExpressionAttributeValues: {
          ':ownerAccountId': { S: accountId },
        },
        ProjectionExpression: 'catalogId, catalogName, isDeleted',
      }));
      
      const items = queryResult.Items || [];
      console.log(`    Found ${items.length} catalog(s) for account ${accountId}`);
      
      for (const item of items) {
        const catalogId = item.catalogId?.S;
        const catalogName = item.catalogName?.S;
        if (catalogId) {
          try {
            console.log(`      Deleting catalog: ${catalogName} (${catalogId})`);
            // HARD DELETE - remove from DynamoDB entirely (not soft delete)
            await dynamodb.send(new DeleteItemCommand({
              TableName: CATALOGS_TABLE,
              Key: { catalogId: { S: catalogId } },
            }));
            deleted++;
            console.log(`      ✓ Deleted catalog: ${catalogName}`);
          } catch (error) {
            console.error(`    Failed to delete catalog ${catalogName} (${catalogId}):`, error);
          }
        }
      }
    } catch (error) {
      console.error(`  Failed to query catalogs for account ${accountId}:`, error);
    }
  }
  
  console.log(`  Total catalogs deleted: ${deleted}`);
  return deleted;
}

async function cleanupTestCampaigns(profileIds: string[]): Promise<number> {
  console.log('  Querying campaigns table by test user profiles...');
  
  let deleted = 0;
  
  // Query campaigns for each test user profile (PK=profileId)
  for (const profileId of profileIds) {
    try {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: CAMPAIGNS_TABLE,
        KeyConditionExpression: 'profileId = :profileId',
        ExpressionAttributeValues: {
          ':profileId': { S: profileId },
        },
        ProjectionExpression: 'profileId, campaignId, campaignName',
      }));
      
      const items = queryResult.Items || [];
      
      for (const item of items) {
        const profileId = item.profileId?.S;
        const campaignId = item.campaignId?.S;
        const campaignName = item.campaignName?.S;
        
        if (profileId && campaignId) {
          try {
            await dynamodb.send(new DeleteItemCommand({
              TableName: CAMPAIGNS_TABLE,
              Key: {
                profileId: { S: profileId },
                campaignId: { S: campaignId },
              },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete campaign ${campaignName} (${campaignId}):`, error);
          }
        }
      }
    } catch (error) {
      console.error(`  Failed to query campaigns for profile ${profileId}:`, error);
    }
  }
  
  return deleted;
}

async function cleanupTestOrders(campaignIds: string[]): Promise<number> {
  console.log('  Querying orders table by test user campaigns...');
  
  let deleted = 0;
  
  // Query orders for each test user campaign (PK=campaignId)
  for (const campaignId of campaignIds) {
    try {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: ORDERS_TABLE,
        KeyConditionExpression: 'campaignId = :campaignId',
        ExpressionAttributeValues: {
          ':campaignId': { S: campaignId },
        },
        ProjectionExpression: 'campaignId, orderId, customerName',
      }));
      
      const items = queryResult.Items || [];
      
      for (const item of items) {
        const campaignId = item.campaignId?.S;
        const orderId = item.orderId?.S;
        const customerName = item.customerName?.S;
        
        if (campaignId && orderId) {
          try {
            await dynamodb.send(new DeleteItemCommand({
              TableName: ORDERS_TABLE,
              Key: {
                campaignId: { S: campaignId },
                orderId: { S: orderId },
              },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete order ${customerName} (${orderId}):`, error);
          }
        }
      }
    } catch (error) {
      console.error(`  Failed to query orders for campaign ${campaignId}:`, error);
    }
  }
  
  return deleted;
}

async function cleanupTestShares(profileIds: string[], testAccountIds: string[]): Promise<number> {
  console.log('  Scanning shares table for test account involvement...');
  
  let deleted = 0;
  const testAccountSet = new Set(testAccountIds);
  
  try {
    // Scan all shares and delete if ANY account ID is a test account
    const scanResult = await dynamodb.send(new ScanCommand({
      TableName: SHARES_TABLE,
      ProjectionExpression: 'profileId, targetAccountId, ownerAccountId, createdByAccountId',
    }));
    
    const items = scanResult.Items || [];
    console.log(`    Found ${items.length} total share(s)`);
    
    for (const item of items) {
      const profileId = item.profileId?.S;
      const targetAccountId = item.targetAccountId?.S;
      const ownerAccountId = item.ownerAccountId?.S;
      const createdByAccountId = item.createdByAccountId?.S;
      
      if (!profileId || !targetAccountId) continue;
      
      // Delete if ANY of these accounts is a test account
      const isTestRelated = 
        testAccountSet.has(targetAccountId) ||
        (ownerAccountId && testAccountSet.has(ownerAccountId)) ||
        (createdByAccountId && testAccountSet.has(createdByAccountId));
      
      if (isTestRelated) {
        try {
          await dynamodb.send(new DeleteItemCommand({
            TableName: SHARES_TABLE,
            Key: {
              profileId: { S: profileId },
              targetAccountId: { S: targetAccountId },
            },
          }));
          deleted++;
        } catch (error) {
          console.error(`    Failed to delete share ${profileId}/${targetAccountId}:`, error);
        }
      }
    }
  } catch (error) {
    console.error(`  Failed to scan shares:`, error);
  }
  
  return deleted;
}

async function cleanupTestInvites(profileIds: string[], testAccountIds: string[]): Promise<number> {
  console.log('  Scanning invites table for test account involvement...');
  
  let deleted = 0;
  const testAccountSet = new Set(testAccountIds);
  const testProfileIdsWithPrefix = new Set(profileIds.map(id => `PROFILE#${id}`));
  
  try {
    // Scan all invites and delete if profile belongs to test account
    const scanResult = await dynamodb.send(new ScanCommand({
      TableName: INVITES_TABLE,
      ProjectionExpression: 'inviteCode, profileId',
    }));
    
    const items = scanResult.Items || [];
    console.log(`    Found ${items.length} total invite(s)`);
    
    for (const item of items) {
      const inviteCode = item.inviteCode?.S;
      const profileIdWithPrefix = item.profileId?.S;
      
      if (!inviteCode || !profileIdWithPrefix) continue;
      
      // Delete if profile is owned by test account
      if (testProfileIdsWithPrefix.has(profileIdWithPrefix)) {
        try {
          await dynamodb.send(new DeleteItemCommand({
            TableName: INVITES_TABLE,
            Key: {
              inviteCode: { S: inviteCode },
            },
          }));
          deleted++;
        } catch (error) {
          console.error(`    Failed to delete invite ${inviteCode}:`, error);
        }
      }
    }
  } catch (error) {
    console.error(`  Failed to scan invites:`, error);
  }
  
  return deleted;
}

/**
 * Clean up orphaned shares (shares referencing non-existent TEST profiles)
 * Only deletes shares for profiles that were owned by test accounts
 */
async function cleanupOrphanedShares(testProfileIds: string[]): Promise<number> {
  console.log('  Checking for orphaned shares from deleted test profiles...');
  let deleted = 0;
  
  // Build set of test profile IDs with PROFILE# prefix
  const testProfileIdsWithPrefix = new Set(testProfileIds.map(id => `PROFILE#${id}`));
  
  try {
    // Only query shares for test profiles that were collected
    for (const profileIdWithPrefix of testProfileIdsWithPrefix) {
      try {
        const queryResult = await dynamodb.send(new QueryCommand({
          TableName: SHARES_TABLE,
          KeyConditionExpression: 'profileId = :profileId',
          ExpressionAttributeValues: {
            ':profileId': { S: profileIdWithPrefix },
          },
          ProjectionExpression: 'profileId, targetAccountId',
        }));
        
        const shares = queryResult.Items || [];
        
        // If we found shares, the profile was already deleted but shares remain
        for (const share of shares) {
          const targetAccountId = share.targetAccountId?.S;
          
          if (profileIdWithPrefix && targetAccountId) {
            console.log(`    Deleting orphaned share: ${profileIdWithPrefix} → ${targetAccountId}`);
            await dynamodb.send(new DeleteItemCommand({
              TableName: SHARES_TABLE,
              Key: {
                profileId: { S: profileIdWithPrefix },
                targetAccountId: { S: targetAccountId },
              },
            }));
            deleted++;
          }
        }
      } catch (error) {
        console.error(`    Failed to check/delete shares for ${profileIdWithPrefix}:`, error);
      }
    }
  } catch (error) {
    console.error('  Failed to query orphaned shares:', error);
  }
  
  console.log(`    Deleted ${deleted} orphaned test share(s)`);
  return deleted;
}

/**
 * Clean up ALL orphaned shares (shares where profile or account doesn't exist).
 * 
 * A share is orphaned if:
 * 1. The profileId doesn't exist in the profiles table
 * 2. The targetAccountId doesn't exist in the accounts table
 * 3. The createdBy accountId doesn't exist in the accounts table (if present)
 * 
 * @param dryRun If true, only reports what would be deleted without actually deleting
 * @param maxDeletions Maximum number of shares to delete in one run (safety limit)
 */
async function cleanupAllOrphanedShares(dryRun: boolean = true, maxDeletions: number = 100): Promise<number> {
  console.log(`  ${dryRun ? '[DRY RUN]' : ''} Scanning ALL shares for orphaned records...`);
  let deleted = 0;
  let checked = 0;
  
  try {
    // Step 1: Load all valid profileIds
    console.log('    Loading all profiles...');
    const validProfileIds = new Set<string>();
    const profilesScanResult = await dynamodb.send(new ScanCommand({
      TableName: PROFILES_TABLE,
      ProjectionExpression: 'profileId',
    }));
    for (const profile of profilesScanResult.Items || []) {
      const profileId = profile.profileId?.S;  // This includes PROFILE# prefix
      if (profileId) {
        validProfileIds.add(profileId);
      }
    }
    console.log(`    Found ${validProfileIds.size} valid profile(s)`);
    
    // Step 2: Load all valid accountIds
    console.log('    Loading all accounts...');
    const validAccountIds = new Set<string>();
    const accountsScanResult = await dynamodb.send(new ScanCommand({
      TableName: ACCOUNTS_TABLE,
      ProjectionExpression: 'accountId',
    }));
    for (const account of accountsScanResult.Items || []) {
      const accountId = account.accountId?.S;  // This includes ACCOUNT# prefix
      if (accountId) {
        validAccountIds.add(accountId);
      }
    }
    console.log(`    Found ${validAccountIds.size} valid account(s)`);
    
    // Step 3: Scan all shares and check validity
    const sharesScanResult = await dynamodb.send(new ScanCommand({
      TableName: SHARES_TABLE,
      ProjectionExpression: 'profileId, targetAccountId, createdBy',
    }));
    
    const shares = sharesScanResult.Items || [];
    console.log(`    Found ${shares.length} total share(s) to validate`);
    
    for (const share of shares) {
      const profileIdWithPrefix = share.profileId?.S;  // This includes PROFILE# prefix
      const targetAccountId = share.targetAccountId?.S;  // This includes ACCOUNT# prefix
      const createdBy = share.createdBy?.S;
      
      if (!profileIdWithPrefix || !targetAccountId) continue;
      
      checked++;
      
      // Check if share is orphaned - NO LONGER strip prefixes!
      let isOrphaned = false;
      let reason = '';
      
      if (!validProfileIds.has(profileIdWithPrefix)) {
        isOrphaned = true;
        reason = 'profile not found';
      } else if (!validAccountIds.has(targetAccountId)) {
        isOrphaned = true;
        reason = `target account ${targetAccountId} not found`;
      } else if (createdBy && !validAccountIds.has(createdBy)) {
        isOrphaned = true;
        reason = `creator account ${createdBy} not found`;
      }
      
      if (isOrphaned) {
        console.log(`    ${dryRun ? 'WOULD DELETE' : 'DELETING'} orphaned share: ${profileIdWithPrefix} → ${targetAccountId} (${reason})`);
        
        if (!dryRun && deleted < maxDeletions) {
          try {
            await dynamodb.send(new DeleteItemCommand({
              TableName: SHARES_TABLE,
              Key: {
                profileId: { S: profileIdWithPrefix },
                targetAccountId: { S: targetAccountId },
              },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete share ${profileIdWithPrefix}/${targetAccountId}:`, error);
          }
        } else if (dryRun) {
          deleted++; // Count what would be deleted
        }
        
        if (deleted >= maxDeletions) {
          console.log(`    ⚠️  Reached max deletions limit (${maxDeletions}), stopping`);
          break;
        }
      }
    }
    
    console.log(`    Checked ${checked} share(s), ${dryRun ? 'would delete' : 'deleted'} ${deleted}`);
  } catch (error) {
    console.error('  Failed to scan shares:', error);
  }
  
  return deleted;
}

/**
 * Clean up orphaned orders (orders referencing non-existent campaigns)
 */
async function cleanupOrphanedOrders(): Promise<number> {
  console.log('  Scanning for orphaned orders...');
  let deleted = 0;
  
  try {
    // First, get all campaigns to build a set of valid campaignIds
    const validCampaignIds = new Set<string>();
    const campaignsResult = await dynamodb.send(new ScanCommand({
      TableName: CAMPAIGNS_TABLE,
      ProjectionExpression: 'campaignId',
    }));
    
    for (const campaign of campaignsResult.Items || []) {
      const campaignId = campaign.campaignId?.S;
      if (campaignId) {
        validCampaignIds.add(campaignId);
      }
    }
    
    console.log(`    Found ${validCampaignIds.size} valid campaign(s)`);
    
    // Scan all orders
    const scanResult = await dynamodb.send(new ScanCommand({
      TableName: ORDERS_TABLE,
      ProjectionExpression: 'campaignId, orderId',
    }));
    
    const orders = scanResult.Items || [];
    console.log(`    Found ${orders.length} total order(s)`);
    
    // Check each order to see if campaign exists
    for (const order of orders) {
      const campaignId = order.campaignId?.S;
      const orderId = order.orderId?.S;
      
      if (!campaignId || !orderId) continue;
      
      if (!validCampaignIds.has(campaignId)) {
        // Campaign doesn't exist - orphaned order!
        console.log(`    Deleting orphaned order: ${orderId} (campaign ${campaignId})`);
        try {
          await dynamodb.send(new DeleteItemCommand({
            TableName: ORDERS_TABLE,
            Key: {
              campaignId: { S: campaignId },
              orderId: { S: orderId },
            },
          }));
          deleted++;
        } catch (error) {
          console.error(`    Failed to delete order ${orderId}:`, error);
        }
      }
    }
  } catch (error) {
    console.error('  Failed to scan orders:', error);
  }
  
  return deleted;
}

/**
 * Clean up orphaned invites (invites referencing non-existent TEST profiles)
 * Only deletes invites for profiles that were owned by test accounts
 */
async function cleanupOrphanedInvites(testProfileIds: string[]): Promise<number> {
  console.log('  Checking for orphaned invites from deleted test profiles...');
  let deleted = 0;
  
  // Build set of test profile IDs with PROFILE# prefix
  const testProfileIdsWithPrefix = new Set(testProfileIds.map(id => `PROFILE#${id}`));
  
  try {
    // Only query invites for test profiles using the profileId-index GSI
    for (const profileIdWithPrefix of testProfileIdsWithPrefix) {
      try {
        const queryResult = await dynamodb.send(new QueryCommand({
          TableName: INVITES_TABLE,
          IndexName: 'profileId-index',
          KeyConditionExpression: 'profileId = :profileId',
          ExpressionAttributeValues: {
            ':profileId': { S: profileIdWithPrefix },
          },
          ProjectionExpression: 'inviteCode',
        }));
        
        const invites = queryResult.Items || [];
        
        // If we found invites, the profile was already deleted but invites remain
        for (const invite of invites) {
          const inviteCode = invite.inviteCode?.S;
          
          if (inviteCode) {
            console.log(`    Deleting orphaned invite: ${inviteCode} (profile ${profileIdWithPrefix} not found)`);
            try {
              await dynamodb.send(new DeleteItemCommand({
                TableName: INVITES_TABLE,
                Key: {
                  inviteCode: { S: inviteCode },
                },
              }));
              deleted++;
            } catch (error) {
              console.error(`    Failed to delete invite ${inviteCode}:`, error);
            }
          }
        }
      } catch (error) {
        console.error(`    Failed to query invites for ${profileIdWithPrefix}:`, error);
      }
    }
  } catch (error) {
    console.error('  Failed to query orphaned invites:', error);
  }
  
  console.log(`    Deleted ${deleted} orphaned test invite(s)`);
  return deleted;
}

/**
 * Clean up ALL orphaned invites (invites where profile or owner account doesn't exist).
 * 
 * An invite is orphaned if:
 * 1. The profileId doesn't exist in the profiles table
 * 2. The ownerAccountId (of the profile) doesn't exist in the accounts table
 * 
 * @param dryRun If true, only reports what would be deleted without actually deleting
 * @param maxDeletions Maximum number of invites to delete in one run (safety limit)
 */
async function cleanupAllOrphanedInvites(dryRun: boolean = true, maxDeletions: number = 100): Promise<number> {
  console.log(`  ${dryRun ? '[DRY RUN]' : ''} Scanning ALL invites for orphaned records...`);
  let deleted = 0;
  let checked = 0;
  
  try {
    // Step 1: Load all valid profileIds with their ownerAccountIds
    console.log('    Loading all profiles...');
    const profileToOwner = new Map<string, string>();
    const profilesScanResult = await dynamodb.send(new ScanCommand({
      TableName: PROFILES_TABLE,
      ProjectionExpression: 'profileId, ownerAccountId',
    }));
    for (const profile of profilesScanResult.Items || []) {
      const profileId = profile.profileId?.S;  // This includes PROFILE# prefix
      const ownerAccountId = profile.ownerAccountId?.S;  // This includes ACCOUNT# prefix
      if (profileId && ownerAccountId) {
        profileToOwner.set(profileId, ownerAccountId);
      }
    }
    console.log(`    Found ${profileToOwner.size} valid profile(s)`);
    
    // Step 2: Load all valid accountIds
    console.log('    Loading all accounts...');
    const validAccountIds = new Set<string>();
    const accountsScanResult = await dynamodb.send(new ScanCommand({
      TableName: ACCOUNTS_TABLE,
      ProjectionExpression: 'accountId',
    }));
    for (const account of accountsScanResult.Items || []) {
      const accountId = account.accountId?.S;  // This includes ACCOUNT# prefix
      if (accountId) {
        validAccountIds.add(accountId);
      }
    }
    console.log(`    Found ${validAccountIds.size} valid account(s)`);
    
    // Step 3: Scan all invites and check validity
    const invitesScanResult = await dynamodb.send(new ScanCommand({
      TableName: INVITES_TABLE,
      ProjectionExpression: 'inviteCode, profileId',
    }));
    
    const invites = invitesScanResult.Items || [];
    console.log(`    Found ${invites.length} total invite(s) to validate`);
    
    for (const invite of invites) {
      const inviteCode = invite.inviteCode?.S;
      const profileIdWithPrefix = invite.profileId?.S;  // This includes PROFILE# prefix
      
      if (!inviteCode || !profileIdWithPrefix) continue;
      
      checked++;
      
      // Check if invite is orphaned - NO LONGER strip prefix!
      let isOrphaned = false;
      let reason = '';
      
      const ownerAccountId = profileToOwner.get(profileIdWithPrefix);
      
      if (!ownerAccountId) {
        // Profile doesn't exist
        isOrphaned = true;
        reason = `profile ${profileIdWithPrefix} not found`;
      } else if (!validAccountIds.has(ownerAccountId)) {
        // Owner account doesn't exist
        isOrphaned = true;
        reason = `owner account ${ownerAccountId} not found`;
      }
      
      if (isOrphaned) {
        console.log(`    ${dryRun ? 'WOULD DELETE' : 'DELETING'} orphaned invite: ${inviteCode} (${reason})`);
        
        if (!dryRun && deleted < maxDeletions) {
          try {
            await dynamodb.send(new DeleteItemCommand({
              TableName: INVITES_TABLE,
              Key: {
                inviteCode: { S: inviteCode },
              },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete invite ${inviteCode}:`, error);
          }
        } else if (dryRun) {
          deleted++; // Count what would be deleted
        }
        
        if (deleted >= maxDeletions) {
          console.log(`    ⚠️  Reached max deletions limit (${maxDeletions}), stopping`);
          break;
        }
      }
    }
    
    console.log(`    Checked ${checked} invite(s), ${dryRun ? 'would delete' : 'deleted'} ${deleted}`);
  } catch (error) {
    console.error('  Failed to scan invites:', error);
  }
  
  return deleted;
}

/**
 * Clean up empty campaigns (campaigns with no orders)
 */
async function cleanupEmptyCampaigns(): Promise<number> {
  console.log('  Scanning for empty campaigns...');
  let deleted = 0;
  
  try {
    // Scan all campaigns
    const scanResult = await dynamodb.send(new ScanCommand({
      TableName: CAMPAIGNS_TABLE,
      ProjectionExpression: 'campaignId, profileId',
    }));
    
    const campaigns = scanResult.Items || [];
    console.log(`    Found ${campaigns.length} total campaign(s)`);
    
    // Check each campaign for orders
    for (const campaign of campaigns) {
      const campaignId = campaign.campaignId?.S;
      const profileId = campaign.profileId?.S;
      
      if (!campaignId || !profileId) continue;
      
      // Query orders for this campaign
      try {
        const ordersResult = await dynamodb.send(new QueryCommand({
          TableName: ORDERS_TABLE,
          KeyConditionExpression: 'campaignId = :campaignId',
          ExpressionAttributeValues: {
            ':campaignId': { S: campaignId },
          },
          ProjectionExpression: 'orderId',
          Limit: 1, // Just check if any exist
        }));
        
        if (!ordersResult.Items || ordersResult.Items.length === 0) {
          // No orders - empty campaign!
          console.log(`    Deleting empty campaign: ${campaignId}`);
          await dynamodb.send(new DeleteItemCommand({
            TableName: CAMPAIGNS_TABLE,
            Key: {
              profileId: { S: profileId },
              campaignId: { S: campaignId },
            },
          }));
          deleted++;
        }
      } catch (error) {
        console.error(`    Failed to check/delete campaign ${campaignId}:`, error);
      }
    }
  } catch (error) {
    console.error('  Failed to scan campaigns:', error);
  }
  
  return deleted;
}

export default async function globalTeardown(): Promise<void> {
  console.log('\n🧹 Running global test cleanup...');
  
  try {
    // Step 1: Get test account IDs
    const testAccountIds = await getTestAccountIds();
    console.log(`  Found ${testAccountIds.length} test account(s)`);
    
    if (testAccountIds.length === 0) {
      console.log('⚠️  No test accounts found, skipping cleanup');
      return;
    }
    
    // Step 2: Collect all profile IDs owned by test accounts
    console.log('  Collecting test user profiles...');
    const profileIds: string[] = [];
    for (const accountId of testAccountIds) {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: PROFILES_TABLE,
        KeyConditionExpression: 'ownerAccountId = :ownerAccountId',
        ExpressionAttributeValues: {
          ':ownerAccountId': { S: accountId },
        },
        ProjectionExpression: 'profileId',
      }));
      const items = queryResult.Items || [];
      profileIds.push(...items.map(item => item.profileId?.S).filter(Boolean) as string[]);
    }
    console.log(`    Found ${profileIds.length} profile(s)`);
    
    // Step 3: Collect all campaign IDs from test user profiles
    console.log('  Collecting test user campaigns...');
    const campaignIds: string[] = [];
    for (const profileId of profileIds) {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: CAMPAIGNS_TABLE,
        KeyConditionExpression: 'profileId = :profileId',
        ExpressionAttributeValues: {
          ':profileId': { S: profileId },
        },
        ProjectionExpression: 'campaignId',
      }));
      const items = queryResult.Items || [];
      campaignIds.push(...items.map(item => item.campaignId?.S).filter(Boolean) as string[]);
    }
    console.log(`    Found ${campaignIds.length} campaign(s)`);
    
    // Step 4: Clean up in order of dependencies (child entities first)
    // NOTE: We delete SellerProfiles (Scouts) but NOT Account records or Cognito users
    const ordersDeleted = await cleanupTestOrders(campaignIds);
    const invitesDeleted = await cleanupTestInvites(profileIds, testAccountIds);
    const sharesDeleted = await cleanupTestShares(profileIds, testAccountIds);
    const campaignsDeleted = await cleanupTestCampaigns(profileIds);
    const catalogsDeleted = await cleanupTestCatalogs();
    const sharedCampaignsDeleted = await cleanupSharedCampaigns();
    const profilesDeleted = await cleanupTestProfiles();
    
    // Step 5: Clean up orphaned records (data integrity issues) - ONLY for test profiles
    console.log('\n  Cleaning up orphaned test data...');
    const orphanedSharesDeleted = await cleanupOrphanedShares(profileIds);
    const orphanedOrdersDeleted = await cleanupOrphanedOrders();
    const orphanedInvitesDeleted = await cleanupOrphanedInvites(profileIds);
    const emptyCampaignsDeleted = await cleanupEmptyCampaigns();
    
    // Step 6: Clean up ALL orphaned shares and invites (DRY RUN by default)
    // Set DRY_RUN=false environment variable to actually delete
    const dryRun = process.env.DRY_RUN !== 'false';
    const maxDeletions = parseInt(process.env.MAX_DELETIONS || '100', 10);
    
    console.log('\n  Cleaning up ALL orphaned data (not just test data)...');
    if (dryRun) {
      console.log('  ⚠️  DRY RUN MODE - No actual deletions will occur');
      console.log('  ℹ️  Set DRY_RUN=false to actually delete orphaned data');
    }
    const allOrphanedSharesDeleted = await cleanupAllOrphanedShares(dryRun, maxDeletions);
    const allOrphanedInvitesDeleted = await cleanupAllOrphanedInvites(dryRun, maxDeletions);
    
    console.log('✅ Global cleanup complete:');
    console.log(`   - Orders: ${ordersDeleted} deleted`);
    console.log(`   - Invites: ${invitesDeleted} deleted`);
    console.log(`   - Shares: ${sharesDeleted} deleted`);
    console.log(`   - Campaigns: ${campaignsDeleted} deleted`);
    console.log(`   - Catalogs: ${catalogsDeleted} deleted`);
    console.log(`   - Shared Campaigns: ${sharedCampaignsDeleted} deleted`);
    console.log(`   - SellerProfiles: ${profilesDeleted} deleted`);
    console.log(`   - Orphaned Shares (test): ${orphanedSharesDeleted} deleted`);
    console.log(`   - Orphaned Orders: ${orphanedOrdersDeleted} deleted`);
    console.log(`   - Orphaned Invites (test): ${orphanedInvitesDeleted} deleted`);
    console.log(`   - Empty Campaigns: ${emptyCampaignsDeleted} deleted`);
    console.log(`   - Orphaned Shares (all): ${allOrphanedSharesDeleted} ${dryRun ? 'would be' : ''} deleted`);
    console.log(`   - Orphaned Invites (all): ${allOrphanedInvitesDeleted} ${dryRun ? 'would be' : ''} deleted`);
    console.log('   - Account records: preserved (not deleted)');
    console.log('   - Cognito users: preserved (not deleted)');
  } catch (error) {
    console.error('❌ Global cleanup failed:', error);
    // Don't throw - we don't want cleanup failures to break CI
  }
}
