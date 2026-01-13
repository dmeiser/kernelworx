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

import { DynamoDBClient, ScanCommand, DeleteItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';
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
            // HARD DELETE - remove from DynamoDB entirely (not soft delete)
            await dynamodb.send(new DeleteItemCommand({
              TableName: CATALOGS_TABLE,
              Key: { catalogId: { S: catalogId } },
            }));
            deleted++;
          } catch (error) {
            console.error(`    Failed to delete catalog ${catalogName} (${catalogId}):`, error);
          }
        }
      }
    } catch (error) {
      console.error(`  Failed to query catalogs for account ${accountId}:`, error);
    }
  }
  
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

async function cleanupTestShares(profileIds: string[]): Promise<number> {
  console.log('  Querying shares table by test user profiles...');
  
  let deleted = 0;
  
  // Query shares for each test user profile (PK=profileId, SK=targetAccountId)
  for (const profileId of profileIds) {
    try {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: SHARES_TABLE,
        KeyConditionExpression: 'profileId = :profileId',
        ExpressionAttributeValues: {
          ':profileId': { S: profileId },
        },
        ProjectionExpression: 'profileId, targetAccountId',
      }));
      
      const items = queryResult.Items || [];
      
      for (const item of items) {
        const profileId = item.profileId?.S;
        const targetAccountId = item.targetAccountId?.S;
        
        if (profileId && targetAccountId) {
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
      console.error(`  Failed to query shares for profile ${profileId}:`, error);
    }
  }
  
  return deleted;
}

async function cleanupTestInvites(profileIds: string[]): Promise<number> {
  console.log('  Querying invites table by test user profiles...');
  
  let deleted = 0;
  
  // Query invites for each test user profile using profileId-index GSI
  for (const profileId of profileIds) {
    try {
      const queryResult = await dynamodb.send(new QueryCommand({
        TableName: INVITES_TABLE,
        IndexName: 'profileId-index',
        KeyConditionExpression: 'profileId = :profileId',
        ExpressionAttributeValues: {
          ':profileId': { S: profileId },
        },
        ProjectionExpression: 'inviteCode',
      }));
      
      const items = queryResult.Items || [];
      
      for (const item of items) {
        const inviteCode = item.inviteCode?.S;
        
        if (inviteCode) {
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
      console.error(`  Failed to query invites for profile ${profileId}:`, error);
    }
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
    const invitesDeleted = await cleanupTestInvites(profileIds);
    const sharesDeleted = await cleanupTestShares(profileIds);
    const campaignsDeleted = await cleanupTestCampaigns(profileIds);
    const catalogsDeleted = await cleanupTestCatalogs();
    const sharedCampaignsDeleted = await cleanupSharedCampaigns();
    const profilesDeleted = await cleanupTestProfiles();
    
    console.log('✅ Global cleanup complete:');
    console.log(`   - Orders: ${ordersDeleted} deleted`);
    console.log(`   - Invites: ${invitesDeleted} deleted`);
    console.log(`   - Shares: ${sharesDeleted} deleted`);
    console.log(`   - Campaigns: ${campaignsDeleted} deleted`);
    console.log(`   - Catalogs: ${catalogsDeleted} deleted`);
    console.log(`   - Shared Campaigns: ${sharedCampaignsDeleted} deleted`);
    console.log(`   - SellerProfiles: ${profilesDeleted} deleted`);
    console.log('   - Account records: preserved (not deleted)');
    console.log('   - Cognito users: preserved (not deleted)');
  } catch (error) {
    console.error('❌ Global cleanup failed:', error);
    // Don't throw - we don't want cleanup failures to break CI
  }
}
