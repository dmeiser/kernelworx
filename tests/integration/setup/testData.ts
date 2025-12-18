import { ApolloClient, gql } from '@apollo/client';
import { DynamoDBClient, DeleteItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';

const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });

// Multi-table configuration for the new schema design
export const TABLE_NAMES = {
  profiles: process.env.PROFILES_TABLE_NAME || 'kernelworx-profiles-ue1-dev',
  seasons: process.env.SEASONS_TABLE_NAME || 'kernelworx-seasons-ue1-dev',
  orders: process.env.ORDERS_TABLE_NAME || 'kernelworx-orders-ue1-dev',
  catalogs: process.env.CATALOGS_TABLE_NAME || 'kernelworx-catalogs-ue1-dev',
  accounts: process.env.ACCOUNTS_TABLE_NAME || 'kernelworx-accounts-ue1-dev',
};

// Legacy single-table name (deprecated, kept for backward compatibility)
const tableName = process.env.TABLE_NAME || 'kernelworx-app-dev';

interface TestResource {
  profileId?: string;
  seasonId?: string;
  orderId?: string;
  shareAccountId?: string;
  catalogIds?: string[];
}

/**
 * Clean up test data from DynamoDB.
 * Deletes resources in proper order to avoid orphaned data.
 * Uses the new multi-table schema design.
 */
export async function cleanupTestData(resources: TestResource): Promise<void> {
  const { profileId, seasonId, orderId, shareAccountId, catalogIds } = resources;

  try {
    // Delete orders from orders table
    if (orderId) {
      await deleteFromTable(TABLE_NAMES.orders, 'orderId', orderId);
    }

    // Delete seasons from seasons table
    if (seasonId) {
      await deleteFromTable(TABLE_NAMES.seasons, 'seasonId', seasonId);
    }

    // Delete shares from profiles table (recordType = SHARE#ACCOUNT#<accountId>)
    if (profileId && shareAccountId) {
      const recordType = shareAccountId.startsWith('ACCOUNT#') 
        ? `SHARE#${shareAccountId}` 
        : `SHARE#ACCOUNT#${shareAccountId}`;
      await deleteProfileRecord(profileId, recordType);
    }

    // Delete invites from profiles table (recordType = INVITE#xxx)
    if (profileId) {
      await deleteInvites(profileId);
    }

    // Delete catalogs from catalogs table
    if (catalogIds && catalogIds.length > 0) {
      for (const catalogId of catalogIds) {
        await deleteFromTable(TABLE_NAMES.catalogs, 'catalogId', catalogId);
      }
    }

    // Delete profile metadata from profiles table
    if (profileId) {
      await deleteProfileRecord(profileId, 'METADATA');
    }
  } catch (error) {
    console.error('Cleanup error:', error);
    // Don't throw - we want tests to continue even if cleanup fails
  }
}

/**
 * Delete all invites for a profile from the profiles table.
 * Invites have recordType = INVITE#<code>
 */
async function deleteInvites(profileId: string): Promise<void> {
  const queryCommand = new QueryCommand({
    TableName: TABLE_NAMES.profiles,
    KeyConditionExpression: 'profileId = :pid AND begins_with(recordType, :rt)',
    ExpressionAttributeValues: {
      ':pid': { S: profileId },
      ':rt': { S: 'INVITE#' },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items) {
    for (const item of result.Items) {
      const recordType = item.recordType.S!;
      await deleteProfileRecord(profileId, recordType);
    }
  }
}

/**
 * Delete a record from the profiles table.
 */
async function deleteProfileRecord(profileId: string, recordType: string): Promise<void> {
  const command = new DeleteItemCommand({
    TableName: TABLE_NAMES.profiles,
    Key: {
      profileId: { S: profileId },
      recordType: { S: recordType },
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
