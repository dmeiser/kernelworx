import { ApolloClient, gql } from '@apollo/client';
import { DynamoDBClient, DeleteItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';

const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });

// Multi-table configuration for the new schema design
// Profiles table V2 uses: PK=ownerAccountId, SK=profileId, GSI=profileId-index
// Campaigns table V2 uses: PK=profileId, SK=campaignId, GSI=campaignId-index
// Orders table V2 uses: PK=campaignId, SK=orderId, GSI=orderId-index
// Shares and Invites are now in separate dedicated tables
export const TABLE_NAMES = {
  profiles: process.env.PROFILES_TABLE_NAME || 'kernelworx-profiles-ue1-dev',
  shares: process.env.SHARES_TABLE_NAME || 'kernelworx-shares-ue1-dev',
  invites: process.env.INVITES_TABLE_NAME || 'kernelworx-invites-ue1-dev',
  campaigns: process.env.CAMPAIGNS_TABLE_NAME || 'kernelworx-campaigns-ue1-dev',
  orders: process.env.ORDERS_TABLE_NAME || 'kernelworx-orders-ue1-dev',
  catalogs: process.env.CATALOGS_TABLE_NAME || 'kernelworx-catalogs-ue1-dev',
  accounts: process.env.ACCOUNTS_TABLE_NAME || 'kernelworx-accounts-ue1-dev',
  sharedCampaigns: process.env.SHARED_CAMPAIGNS_TABLE_NAME || 'kernelworx-shared-campaigns-ue1-dev',
};

interface TestResource {
  profileId?: string;
  ownerAccountId?: string; // Required for profile cleanup with new schema
  campaignId?: string;
  orderId?: string;
  shareAccountId?: string;
  catalogIds?: string[];
}

/**
 * Clean up test data from DynamoDB.
 * Deletes resources in proper order to avoid orphaned data.
 * Uses the new multi-table schema design with separate shares/invites tables.
 * 
 * NEW SCHEMA (V2):
 * - Profiles: PK=ownerAccountId, SK=profileId
 * - Campaigns: PK=profileId, SK=campaignId (separate table with campaignId-index GSI)
 * - Orders: PK=campaignId, SK=orderId (separate table with orderId-index GSI)
 * - Shares: PK=profileId, SK=targetAccountId (separate table)
 * - Invites: PK=inviteCode (separate table with profileId-index GSI)
 */
export async function cleanupTestData(resources: TestResource): Promise<void> {
  const { profileId, ownerAccountId, campaignId, orderId, shareAccountId, catalogIds } = resources;

  try {
    // Delete orders from orders table V2 (query by orderId-index, delete with composite key)
    if (orderId) {
      await deleteOrderById(orderId);
    }

    // Delete campaigns from campaigns table V2 (query by campaignId-index, delete with composite key)
    if (campaignId) {
      await deleteCampaignById(campaignId);
    }

    // Delete shares from shares table (NEW: separate table)
    if (profileId && shareAccountId) {
      await deleteShare(profileId, shareAccountId);
    }

    // Delete invites from invites table (NEW: separate table)
    if (profileId) {
      await deleteInvitesByProfile(profileId);
    }

    // Delete catalogs from catalogs table
    if (catalogIds && catalogIds.length > 0) {
      for (const catalogId of catalogIds) {
        await deleteFromTable(TABLE_NAMES.catalogs, 'catalogId', catalogId);
      }
    }

    // Delete profile from profiles table (NEW: uses ownerAccountId/profileId keys)
    if (profileId && ownerAccountId) {
      await deleteProfile(ownerAccountId, profileId);
    }
  } catch (error) {
    console.error('Cleanup error:', error);
    // Don't throw - we want tests to continue even if cleanup fails
  }
}

/**
 * Delete a share from the shares table.
 * Shares table: PK=profileId, SK=targetAccountId
 */
async function deleteShare(profileId: string, targetAccountId: string): Promise<void> {
  // Normalize targetAccountId to not have ACCOUNT# prefix (shares table stores raw account ID)
  const normalizedAccountId = targetAccountId.startsWith('ACCOUNT#') 
    ? targetAccountId 
    : `ACCOUNT#${targetAccountId}`;
  
  const command = new DeleteItemCommand({
    TableName: TABLE_NAMES.shares,
    Key: {
      profileId: { S: profileId },
      targetAccountId: { S: normalizedAccountId },
    },
  });

  await dynamoClient.send(command);
}

/**
 * Delete all invites for a profile from the invites table.
 * Invites table: PK=inviteCode, GSI=profileId-index
 * Must query by profileId-index first, then delete each by inviteCode
 */
async function deleteInvitesByProfile(profileId: string): Promise<void> {
  const queryCommand = new QueryCommand({
    TableName: TABLE_NAMES.invites,
    IndexName: 'profileId-index',
    KeyConditionExpression: 'profileId = :pid',
    ExpressionAttributeValues: {
      ':pid': { S: profileId },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items) {
    for (const item of result.Items) {
      const inviteCode = item.inviteCode.S!;
      const deleteCommand = new DeleteItemCommand({
        TableName: TABLE_NAMES.invites,
        Key: {
          inviteCode: { S: inviteCode },
        },
      });
      await dynamoClient.send(deleteCommand);
    }
  }
}

/**
 * Delete a profile from the profiles table.
 * Profiles table V2: PK=ownerAccountId, SK=profileId
 */
async function deleteProfile(ownerAccountId: string, profileId: string): Promise<void> {
  const command = new DeleteItemCommand({
    TableName: TABLE_NAMES.profiles,
    Key: {
      ownerAccountId: { S: ownerAccountId },
      profileId: { S: profileId },
    },
  });

  await dynamoClient.send(command);
}

/**
 * Delete item from any table by its primary key.
 */
async function deleteFromTable(tableName: string, keyName: string, keyValue: string): Promise<void> {
  const command = new DeleteItemCommand({
    TableName: tableName,
    Key: {
      [keyName]: { S: keyValue },
    },
  });

  await dynamoClient.send(command);
}

/**
 * Delete an order from the orders table V2.
 * Orders table V2: PK=campaignId, SK=orderId, GSI=orderId-index
 * Must query by orderId-index first to get campaignId, then delete with composite key.
 */
async function deleteOrderById(orderId: string): Promise<void> {
  // Query orderId-index to get the campaignId (needed for composite key)
  const queryCommand = new QueryCommand({
    TableName: TABLE_NAMES.orders,
    IndexName: 'orderId-index',
    KeyConditionExpression: 'orderId = :oid',
    ExpressionAttributeValues: {
      ':oid': { S: orderId },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items && result.Items.length > 0) {
    const campaignId = result.Items[0].campaignId.S!;
    const deleteCommand = new DeleteItemCommand({
      TableName: TABLE_NAMES.orders,
      Key: {
        campaignId: { S: campaignId },
        orderId: { S: orderId },
      },
    });
    await dynamoClient.send(deleteCommand);
  }
}

/**
 * Delete a campaign from the campaigns table V2.
 * Campaigns table V2: PK=profileId, SK=campaignId, GSI=campaignId-index
 * Must query by campaignId-index first to get profileId, then delete with composite key.
 */
async function deleteCampaignById(campaignId: string): Promise<void> {
  // Query campaignId-index to get the profileId (needed for composite key)
  const queryCommand = new QueryCommand({
    TableName: TABLE_NAMES.campaigns,
    IndexName: 'campaignId-index',
    KeyConditionExpression: 'campaignId = :sid',
    ExpressionAttributeValues: {
      ':sid': { S: campaignId },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items && result.Items.length > 0) {
    const profileId = result.Items[0].profileId.S!;
    const deleteCommand = new DeleteItemCommand({
      TableName: TABLE_NAMES.campaigns,
      Key: {
        profileId: { S: profileId },
        campaignId: { S: campaignId },
      },
    });
    await dynamoClient.send(deleteCommand);
  }
}

/**
 * Delete test user accounts from DynamoDB.
 * 
 * IMPORTANT: Account records are created by the Cognito post-authentication
 * Lambda trigger when users authenticate. They are NOT created by test code.
 * We delete them here to satisfy the "empty table after tests" requirement,
 * but note they will be recreated on the next test run when users authenticate.
 * 
 * @param accountIds - Array of account IDs to delete (without ACCOUNT# prefix)
 */
export async function deleteTestAccounts(accountIds: string[]): Promise<void> {
  for (const accountId of accountIds) {
    // Accounts table uses accountId as PK, which includes ACCOUNT# prefix
    const pk = accountId.startsWith('ACCOUNT#') ? accountId : `ACCOUNT#${accountId}`;
    try {
      const command = new DeleteItemCommand({
        TableName: TABLE_NAMES.accounts,
        Key: {
          accountId: { S: pk },
        },
      });
      await dynamoClient.send(command);
      console.log(`Deleted account: ${pk}`);
    } catch (error) {
      console.warn(`Failed to delete account ${pk}:`, error);
    }
  }
}

/**
 * GraphQL mutation to delete profile (alternative to direct DynamoDB delete).
 */
export const DELETE_PROFILE = gql`
  mutation DeleteProfile($profileId: ID!) {
    deleteProfile(profileId: $profileId) {
      profileId
    }
  }
`;

/**
 * Delete test profile via GraphQL (requires appropriate permissions).
 */
export async function deleteTestProfile(
  client: ApolloClient,
  profileId: string
): Promise<void> {
  try {
    await client.mutate({
      mutation: DELETE_PROFILE,
      variables: { profileId },
    });
  } catch (error) {
    console.warn(`Failed to delete profile ${profileId}:`, error);
  }
}

/**
 * Create unique test data prefix to avoid collisions.
 */
export function getTestPrefix(): string {
  return `TEST-${Date.now()}`;
}

/**
 * Wait for GSI eventual consistency by polling until item appears in query results.
 * This is a workaround for Bug #21 (GSI eventual consistency).
 * 
 * @param queryFn - Function that executes the GSI query (returns array of items)
 * @param checkFn - Function that checks if expected item(s) are in results
 * @param maxAttempts - Maximum number of polling attempts (default: 20)
 * @param delayMs - Delay between attempts in milliseconds (default: 1000)
 * @returns The query result when item is found, or throws after max attempts
 */
export async function waitForGSIConsistency<T>(
  queryFn: () => Promise<T[]>,
  checkFn: (items: T[]) => boolean,
  maxAttempts: number = 20,
  delayMs: number = 1000
): Promise<T[]> {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const items = await queryFn();
    if (checkFn(items)) {
      console.log(`✅ GSI consistency achieved after ${attempt} attempts (${attempt * delayMs}ms)`);
      return items;
    }
    
    if (attempt < maxAttempts) {
      console.log(`⏳ GSI not consistent yet, attempt ${attempt}/${maxAttempts}, waiting ${delayMs}ms...`);
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }
  }
  
  throw new Error(`GSI consistency timeout after ${maxAttempts} attempts (${maxAttempts * delayMs}ms)`);
}
