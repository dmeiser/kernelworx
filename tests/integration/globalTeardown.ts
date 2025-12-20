/**
 * Global teardown for integration tests.
 * 
 * This file runs AFTER all test suites complete (or if tests are interrupted).
 * It cleans up any orphaned test data that wasn't deleted by individual tests.
 * 
 * Why this exists:
 * - When tests fail, their afterAll cleanup code may not run
 * - When tests are interrupted (Ctrl+C), cleanup doesn't happen
 * - Rate limits (e.g., 50 prefills max) can block future test runs
 */

import { DynamoDBClient, ScanCommand, DeleteItemCommand } from '@aws-sdk/client-dynamodb';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const dynamodb = new DynamoDBClient({ region: 'us-east-1' });

// Table names from environment or defaults
const PREFILLS_TABLE = process.env.PREFILLS_TABLE_NAME || 'kernelworx-campaign-prefills-ue1-dev';
const PROFILES_TABLE = process.env.PROFILES_TABLE_NAME || 'kernelworx-profiles-v2-ue1-dev';
const SEASONS_TABLE = process.env.SEASONS_TABLE_NAME || 'kernelworx-seasons-v2-ue1-dev';
const ORDERS_TABLE = process.env.ORDERS_TABLE_NAME || 'kernelworx-orders-v2-ue1-dev';
const CATALOGS_TABLE = process.env.CATALOGS_TABLE_NAME || 'kernelworx-catalogs-ue1-dev';
const SHARES_TABLE = process.env.SHARES_TABLE_NAME || 'kernelworx-shares-v2-ue1-dev';

// Test account IDs (from .env)
const TEST_ACCOUNT_IDS = [
  process.env.TEST_OWNER_ACCOUNT_ID,
  process.env.TEST_CONTRIBUTOR_ACCOUNT_ID,
  process.env.TEST_READONLY_ACCOUNT_ID,
].filter(Boolean) as string[];

async function cleanupCampaignPrefills(): Promise<number> {
  console.log('  Scanning campaign prefills table...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: PREFILLS_TABLE,
    ProjectionExpression: 'prefillCode, SK, createdBy',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const prefillCode = item.prefillCode?.S;
    const sk = item.SK?.S;
    const createdBy = item.createdBy?.S;
    
    // Only delete items created by test accounts
    if (prefillCode && sk && TEST_ACCOUNT_IDS.includes(createdBy || '')) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: PREFILLS_TABLE,
          Key: {
            prefillCode: { S: prefillCode },
            SK: { S: sk },
          },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete prefill ${prefillCode}:`, error);
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

async function cleanupTestSeasons(): Promise<number> {
  console.log('  Scanning seasons table for TEST- prefixed items...');
  
  const scanResult = await dynamodb.send(new ScanCommand({
    TableName: SEASONS_TABLE,
    FilterExpression: 'begins_with(seasonName, :prefix)',
    ExpressionAttributeValues: {
      ':prefix': { S: 'TEST-' },
    },
    ProjectionExpression: 'profileId, seasonId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const profileId = item.profileId?.S;
    const seasonId = item.seasonId?.S;
    if (profileId && seasonId) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: SEASONS_TABLE,
          Key: {
            profileId: { S: profileId },
            seasonId: { S: seasonId },
          },
        }));
        deleted++;
      } catch (error) {
        console.error(`  Failed to delete season ${seasonId}:`, error);
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
    ProjectionExpression: 'seasonId, orderId',
  }));
  
  const items = scanResult.Items || [];
  let deleted = 0;
  
  for (const item of items) {
    const seasonId = item.seasonId?.S;
    const orderId = item.orderId?.S;
    if (seasonId && orderId) {
      try {
        await dynamodb.send(new DeleteItemCommand({
          TableName: ORDERS_TABLE,
          Key: {
            seasonId: { S: seasonId },
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
    const ordersDeleted = await cleanupTestOrders();
    const seasonsDeleted = await cleanupTestSeasons();
    const sharesDeleted = await cleanupTestShares();
    const profilesDeleted = await cleanupTestProfiles();
    const catalogsDeleted = await cleanupTestCatalogs();
    const prefillsDeleted = await cleanupCampaignPrefills();
    
    console.log('✅ Global cleanup complete:');
    console.log(`   - Orders: ${ordersDeleted} deleted`);
    console.log(`   - Seasons: ${seasonsDeleted} deleted`);
    console.log(`   - Shares: ${sharesDeleted} deleted`);
    console.log(`   - Profiles: ${profilesDeleted} deleted`);
    console.log(`   - Catalogs: ${catalogsDeleted} deleted`);
    console.log(`   - Campaign Prefills: ${prefillsDeleted} deleted`);
  } catch (error) {
    console.error('❌ Global cleanup failed:', error);
    // Don't throw - we don't want cleanup failures to break CI
  }
}
