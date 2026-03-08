/**
 * Runtime lookup of infrastructure outputs using AWS SDK.
 * 
 * This module provides dynamic resolution of AppSync endpoint and Cognito client ID
 * by querying AWS resources directly, eliminating the need to manually configure these
 * values in .env files.
 */

import {
  AppSyncClient,
  ListGraphqlApisCommand,
} from '@aws-sdk/client-appsync';
import {
  CognitoIdentityProviderClient,
  ListUserPoolsCommand,
  ListUserPoolClientsCommand,
} from '@aws-sdk/client-cognito-identity-provider';

/**
 * Extract environment name from E2E_BASE_URL.
 * 
 * Examples:
 *   "https://dev.kernelworx.app"  -> "dev"
 *   "https://prod.kernelworx.app" -> "prod"
 *   "http://localhost:5173"       -> "dev" (fallback)
 */
function parseEnvironmentFromUrl(baseUrl: string): string {
  try {
    const url = new URL(baseUrl);
    const hostname = url.hostname.toLowerCase();

    if (hostname === 'localhost' || hostname.endsWith('.localhost')) {
      return 'dev';
    }

    if (hostname === 'kernelworx.app' || hostname === 'www.kernelworx.app') {
      return 'prod';
    }

    const parts = url.hostname.split('.');
    // Multi-part hostname like "dev.kernelworx.app" -> first part is the env
    if (parts.length >= 3) {
      return parts[0];
    }
  } catch {
    // Invalid URL, fallback
  }
  return 'dev';
}

/**
 * Convert AWS region to abbreviation.
 * 
 * Examples:
 *   "us-east-1" -> "ue1"
 *   "eu-west-2" -> "ew2"
 */
function regionToAbbrev(region: string): string {
  return region
    .split('-')
    .filter((part) => part)
    .map((part) => part[0])
    .join('');
}

/**
 * Resolve AppSync API endpoint dynamically by querying AWS.
 * 
 * Resolution order:
 * 1. Explicit TEST_APPSYNC_ENDPOINT env var (if set)
 * 2. AWS AppSync API lookup by name convention: kernelworx-api-{region_abbrev}-{environment}
 * 3. null (caller should fail with helpful error)
 */
export async function resolveAppSyncEndpoint(): Promise<string | null> {
  // 1. Explicit override
  if (process.env.TEST_APPSYNC_ENDPOINT) {
    return process.env.TEST_APPSYNC_ENDPOINT;
  }

  // 2. Dynamic AWS lookup
  const baseUrl = process.env.E2E_BASE_URL || 'https://dev.kernelworx.app';
  const environment = parseEnvironmentFromUrl(baseUrl);
  const region = process.env.TEST_REGION || 'us-east-1';
  const regionAbbrev = regionToAbbrev(region);
  const expectedName = `kernelworx-api-${regionAbbrev}-${environment}`;

  try {
    const client = new AppSyncClient({ region });
    const command = new ListGraphqlApisCommand({ maxResults: 25 });
    const response = await client.send(command);

    const matchingApi = response.graphqlApis?.find((api) => api.name === expectedName);
    if (matchingApi?.uris?.GRAPHQL) {
      return matchingApi.uris.GRAPHQL;
    }
  } catch (error) {
    // AWS credentials not available or API not found
    console.error(`Could not query AWS AppSync APIs: ${error}`);
  }

  return null;
}

/**
 * Resolve Cognito User Pool Client ID dynamically by querying AWS.
 * 
 * Resolution order:
 * 1. Explicit TEST_USER_POOL_CLIENT_ID env var (if set)
 * 2. AWS Cognito User Pool lookup by name convention: kernelworx-users-{region_abbrev}-{environment}
 * 3. null (caller should fail with helpful error)
 */
export async function resolveUserPoolClientId(): Promise<string | null> {
  // 1. Explicit override
  if (process.env.TEST_USER_POOL_CLIENT_ID) {
    return process.env.TEST_USER_POOL_CLIENT_ID;
  }

  // 2. Dynamic AWS lookup (requires user pool ID first)
  const userPoolId = await resolveUserPoolId();
  if (!userPoolId) {
    return null;
  }

  try {
    const region = process.env.TEST_REGION || 'us-east-1';
    const client = new CognitoIdentityProviderClient({ region });
    const command = new ListUserPoolClientsCommand({
      UserPoolId: userPoolId,
      MaxResults: 60,
    });
    const response = await client.send(command);

    // Get the first (and typically only) app client
    const appClient = response.UserPoolClients?.[0];
    if (appClient?.ClientId) {
      return appClient.ClientId;
    }
  } catch (error) {
    console.error(`Could not query Cognito User Pool clients: ${error}`);
  }

  return null;
}

/**
 * Resolve Cognito User Pool ID dynamically by querying AWS.
 * 
 * Resolution order:
 * 1. Explicit TEST_USER_POOL_ID env var (if set)
 * 2. AWS Cognito User Pool lookup by name convention: kernelworx-users-{region_abbrev}-{environment}
 * 3. null (caller should fail with helpful error)
 */
export async function resolveUserPoolId(): Promise<string | null> {
  // 1. Explicit override
  if (process.env.TEST_USER_POOL_ID) {
    return process.env.TEST_USER_POOL_ID;
  }

  // 2. Dynamic AWS lookup
  const baseUrl = process.env.E2E_BASE_URL || 'https://dev.kernelworx.app';
  const environment = parseEnvironmentFromUrl(baseUrl);
  const region = process.env.TEST_REGION || 'us-east-1';
  const regionAbbrev = regionToAbbrev(region);
  const expectedName = `kernelworx-users-${regionAbbrev}-${environment}`;

  try {
    const client = new CognitoIdentityProviderClient({ region });
    const command = new ListUserPoolsCommand({ MaxResults: 60 });
    const response = await client.send(command);

    const matchingPool = response.UserPools?.find((pool) => pool.Name === expectedName);
    if (matchingPool?.Id) {
      return matchingPool.Id;
    }
  } catch (error) {
    console.error(`Could not query Cognito User Pools: ${error}`);
  }

  return null;
}
