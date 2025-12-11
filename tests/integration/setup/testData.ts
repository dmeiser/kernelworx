import { ApolloClient, gql } from '@apollo/client';
import { DynamoDBClient, DeleteItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';

const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
const tableName = process.env.TABLE_NAME || 'PsmApp-dev';

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
 */
export async function cleanupTestData(resources: TestResource): Promise<void> {
  const { profileId, seasonId, orderId, shareAccountId, catalogIds } = resources;

  try {
    // Delete shares first
    if (profileId && shareAccountId) {
      await deleteItem(profileId, `SHARE#${shareAccountId}`);
    }

    // Delete orders
    if (profileId && orderId) {
      await deleteItem(profileId, orderId);
    }

    // Delete invites (query for all invites on profile)
    if (profileId) {
      await deleteInvites(profileId);
    }

    // Delete seasons
    if (profileId && seasonId) {
      await deleteItem(profileId, seasonId);
    }

    // Delete catalogs
    if (catalogIds && catalogIds.length > 0) {
      for (const catalogId of catalogIds) {
        await deleteCatalog(catalogId);
      }
    }

    // Delete profile metadata
    if (profileId) {
      await deleteItem(profileId, 'METADATA');
    }
  } catch (error) {
    console.error('Cleanup error:', error);
    // Don't throw - we want tests to continue even if cleanup fails
  }
}

/**
 * Delete all invites for a profile (they have random codes).
 */
async function deleteInvites(profileId: string): Promise<void> {
  const queryCommand = new QueryCommand({
    TableName: tableName,
    KeyConditionExpression: 'PK = :pk AND begins_with(SK, :sk)',
    ExpressionAttributeValues: {
      ':pk': { S: profileId },
      ':sk': { S: 'INVITE#' },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items) {
    for (const item of result.Items) {
      const sk = item.SK.S!;
      await deleteItem(profileId, sk);
    }
  }
}

/**
 * Delete catalog and its products from DynamoDB.
 */
async function deleteCatalog(catalogId: string): Promise<void> {
  // Catalogs use PK=CATALOG#{catalogId}, SK=METADATA
  await deleteItem(catalogId, 'METADATA');
  
  // Also delete all products (they use SK=PRODUCT#{productId})
  const queryCommand = new QueryCommand({
    TableName: tableName,
    KeyConditionExpression: 'PK = :pk AND begins_with(SK, :sk)',
    ExpressionAttributeValues: {
      ':pk': { S: catalogId },
      ':sk': { S: 'PRODUCT#' },
    },
  });

  const result = await dynamoClient.send(queryCommand);
  
  if (result.Items) {
    for (const item of result.Items) {
      const sk = item.SK.S!;
      await deleteItem(catalogId, sk);
    }
  }
}

/**
 * Delete single item from DynamoDB.
 */
async function deleteItem(pk: string, sk: string): Promise<void> {
  const command = new DeleteItemCommand({
    TableName: tableName,
    Key: {
      PK: { S: pk },
      SK: { S: sk },
    },
  });

  await dynamoClient.send(command);
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
