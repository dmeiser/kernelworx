/**
 * Dynamic AWS Configuration Lookup
 * 
 * Looks up Cognito and AppSync configuration from AWS at runtime,
 * so we don't need hardcoded values in .env files.
 */

import { CognitoIdentityProviderClient, ListUserPoolClientsCommand } from '@aws-sdk/client-cognito-identity-provider';
import { AppSyncClient, ListGraphqlApisCommand } from '@aws-sdk/client-appsync';

export interface AwsConfig {
  userPoolId: string;
  userPoolClientId: string;
  appSyncEndpoint: string;
  region: string;
}

// Cache the config so we only look it up once
let cachedConfig: AwsConfig | null = null;

/**
 * Look up AWS configuration dynamically from AWS resources.
 * Caches result for subsequent calls.
 */
export async function getAwsConfig(): Promise<AwsConfig> {
  if (cachedConfig) {
    return cachedConfig;
  }

  const region = process.env.TEST_REGION || 'us-east-1';

  // Use explicit env var override if set, otherwise look up from AWS
  let userPoolId: string;
  let userPoolClientId: string;

  if (process.env.TEST_USER_POOL_CLIENT_ID) {
    userPoolClientId = process.env.TEST_USER_POOL_CLIENT_ID;
    userPoolId = process.env.TEST_USER_POOL_ID || '';
    if (!userPoolId) {
      throw new Error('TEST_USER_POOL_CLIENT_ID is set but TEST_USER_POOL_ID is not');
    }
  } else {
    const cognitoConfig = await lookupCognitoConfigByPoolName(region, 'kernelworx');
    userPoolId = cognitoConfig.userPoolId;
    userPoolClientId = cognitoConfig.clientId;
  }
  const appSyncEndpoint = process.env.TEST_APPSYNC_ENDPOINT || await lookupAppSyncEndpoint(region, 'kernelworx');

  cachedConfig = {
    userPoolId,
    userPoolClientId,
    appSyncEndpoint,
    region,
  };

  console.log('✅ Integration test environment configured');
  console.log(`   AppSync: ${cachedConfig.appSyncEndpoint}`);
  console.log(`   User Pool: ${cachedConfig.userPoolId}`);

  return cachedConfig;
}

/**
 * Find Cognito user pool and client by pool name pattern
 */
async function lookupCognitoConfigByPoolName(region: string, namePattern: string): Promise<{ userPoolId: string; clientId: string }> {
  const { CognitoIdentityProviderClient: CognitoClient, ListUserPoolsCommand } = await import('@aws-sdk/client-cognito-identity-provider');
  
  const client = new CognitoClient({ region });
  const poolsResponse = await client.send(new ListUserPoolsCommand({ MaxResults: 20 }));
  
  // Find pool matching pattern
  const pool = poolsResponse.UserPools?.find(p => p.Name?.toLowerCase().includes(namePattern.toLowerCase()));
  if (!pool?.Id) {
    throw new Error(`Could not find user pool matching pattern: ${namePattern}`);
  }
  
  // Get first client for this pool
  const clientsResponse = await client.send(new ListUserPoolClientsCommand({
    UserPoolId: pool.Id,
    MaxResults: 1,
  }));
  
  const poolClient = clientsResponse.UserPoolClients?.[0];
  if (!poolClient?.ClientId) {
    throw new Error(`No clients found for user pool ${pool.Id}`);
  }
  
  return {
    userPoolId: pool.Id,
    clientId: poolClient.ClientId,
  };
}

/**
 * Look up AppSync endpoint by API name pattern
 */
async function lookupAppSyncEndpoint(region: string, namePattern: string): Promise<string> {
  const client = new AppSyncClient({ region });
  const response = await client.send(new ListGraphqlApisCommand({}));
  
  const api = response.graphqlApis?.find(a => a.name?.toLowerCase().includes(namePattern.toLowerCase()));
  if (!api?.uris?.GRAPHQL) {
    throw new Error(`Could not find AppSync API matching pattern: ${namePattern}`);
  }
  
  return api.uris.GRAPHQL;
}

/**
 * Reset cached config (useful for testing)
 */
export function resetAwsConfigCache(): void {
  cachedConfig = null;
}
