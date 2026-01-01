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

import { DynamoDBClient, ScanCommand, DeleteItemCommand } from '@aws-sdk/client-dynamodb';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const dynamodb = new DynamoDBClient({ region: 'us-east-1' });

// Table names from environment or defaults
const SHARED_CAMPAIGNS_TABLE = process.env.SHARED_CAMPAIGNS_TABLE_NAME || 'kernelworx-shared-campaigns-ue1-dev';
const PROFILES_TABLE = process.env.PROFILES_TABLE_NAME || 'kernelworx-profiles-v2-ue1-dev';
const CAMPAIGNS_TABLE = process.env.CAMPAIGNS_TABLE_NAME || 'kernelworx-campaigns-v2-ue1-dev';
const ORDERS_TABLE = process.env.ORDERS_TABLE_NAME || 'kernelworx-orders-v2-ue1-dev';
const CATALOGS_TABLE = process.env.CATALOGS_TABLE_NAME || 'kernelworx-catalogs-ue1-dev';
const SHARES_TABLE = process.env.SHARES_TABLE_NAME || 'kernelworx-shares-v2-ue1-dev';

// Test account IDs (from .env)
const TEST_ACCOUNT_IDS = [
  process.env.TEST_OWNER_ACCOUNT_ID,
  process.env.TEST_CONTRIBUTOR_ACCOUNT_ID,
  process.env.TEST_READONLY_ACCOUNT_ID,
].filter(Boolean) as string[];

async function cleanupSharedCampaigns(): Promise<number> {
  console.log('  Scanning campaign shared campaigns table...');
  
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
    if (sharedCampaignCode && sk && TEST_ACCOUNT_IDS.includes(createdBy || '')) {
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
  console.log('  Scanning profiles table for TEST- prefixed items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: PROFILES_TABLE,
    FilterExpression: 'begins_with(sellerName, :prefix)',
    ExpressionAttributeValues: {
      ':prefix': { S: 'TEST-' },
    },
    ProjectionExpression: 'profileId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const profileId = item.profileId?.S;
    if (profileId) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: PROFILES_TABLE,
          Key: { profileId: { S: profileId } },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete profile ${profileId}:`, error);
      }
    }
  }
  
  return deleted;
}

async function cleanupTestCatalogs(): Promise<number> {
  console.log('  Scanning catalogs table for TEST- prefixed items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: CATALOGS_TABLE,
    FilterExpression: 'begins_with(catalogName, :prefix)',
    ExpressionAttributeValues: {
      ':prefix': { S: 'TEST-' },
    },
    ProjectionExpression: 'catalogId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const catalogId = item.catalogId?.S;
    if (catalogId) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: CATALOGS_TABLE,
          Key: { catalogId: { S: catalogId } },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete catalog ${catalogId}:`, error);
      }
    }
  }
  
  return deleted;
}

async function cleanupTestCampaigns(): Promise<number> {
  console.log('  Scanning campaigns table for TEST- prefixed items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: CAMPAIGNS_TABLE,
    FilterExpression: 'begins_with(campaignName, :prefix)',
    ExpressionAttributeValues: {
      ':prefix': { S: 'TEST-' },
    },
    ProjectionExpression: 'profileId, campaignId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const profileId = item.profileId?.S;
    const campaignId = item.campaignId?.S;
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
        console.error(`  Failed to delete campaign ${campaignId}:`, error);
      }
    }
  }
  
  return deleted;
}

async function cleanupTestOrders(): Promise<number> {
  console.log('  Scanning orders table for TEST- prefixed items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: ORDERS_TABLE,
    FilterExpression: 'begins_with(customerName, :prefix)',
    ExpressionAttributeValues: {
      ':prefix': { S: 'TEST-' },
    },
    ProjectionExpression: 'campaignId, orderId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const campaignId = item.campaignId?.S;
    const orderId = item.orderId?.S;
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
        console.error(`  Failed to delete order ${orderId}:`, error);
      }
    }
  }
  
  return deleted;
}

async function cleanupTestShares(): Promise<number> {
  console.log('  Scanning shares table for test account items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: SHARES_TABLE,
    ProjectionExpression: 'profileId, shareId, createdByAccountId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const profileId = item.profileId?.S;
    const shareId = item.shareId?.S;
    const createdBy = item.createdByAccountId?.S;
    
    // Only delete items created by test accounts
    if (profileId && shareId && TEST_ACCOUNT_IDS.includes(createdBy || '')) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: SHARES_TABLE,
          Key: {
            profileId: { S: profileId },
            shareId: { S: shareId },
          },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete share ${shareId}:`, error);
      }
    }
  }
  
  return deleted;
}

export default async function globalTeardown(): Promise<void> {
  console.log('\n🧹 Running global test cleanup...');
  
  try {
    // Clean up in order of dependencies (child entities first)
    // NOTE: We delete SellerProfiles (Scouts) but NOT Account records or Cognito users
    const ordersDeleted = await cleanupTestOrders();
    const campaignsDeleted = await cleanupTestCampaigns();
    const sharesDeleted = await cleanupTestShares();
    const profilesDeleted = await cleanupTestProfiles();
    const catalogsDeleted = await cleanupTestCatalogs();
    const sharedCampaignsDeleted = await cleanupSharedCampaigns();
    
    console.log('✅ Global cleanup complete:');
    console.log(`   - Orders: ${ordersDeleted} deleted`);
    console.log(`   - Campaigns: ${campaignsDeleted} deleted`);
    console.log(`   - Shares: ${sharesDeleted} deleted`);
    console.log(`   - SellerProfiles: ${profilesDeleted} deleted`);
    console.log(`   - Catalogs: ${catalogsDeleted} deleted`);
    console.log(`   - Shared Campaigns: ${sharedCampaignsDeleted} deleted`);
    console.log('   - Account records: preserved (not deleted)');
    console.log('   - Cognito users: preserved (not deleted)');
  } catch (error) {
    console.error('❌ Global cleanup failed:', error);
    // Don't throw - we don't want cleanup failures to break CI
  }
}
