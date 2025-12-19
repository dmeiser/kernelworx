/**
 * Dynamic AWS Configuration Lookup
 * 
 * Looks up Cognito and AppSync configuration from AWS at runtime,
 * so we don't need hardcoded values in .env files.
 */

import { CognitoIdentityProviderClient, ListUserPoolClientsCommand } from '@aws-sdk/client-cognito-identity-provider';
import { AppSyncClient, ListGraphqlApisCommand } from '@aws-sdk/client-appsync';
import { CloudFormationClient, DescribeStacksCommand } from '@aws-sdk/client-cloudformation';

export interface AwsConfig {
  userPoolId: string;
  userPoolClientId: string;
  appSyncEndpoint: string;
  region: string;
}

// Cache the config so we only look it up once
let cachedConfig: AwsConfig | null = null;

/**
 * Look up AWS configuration dynamically from CloudFormation stack outputs
 * and AWS resources. Caches result for subsequent calls.
 */
export async function getAwsConfig(): Promise<AwsConfig> {
  if (cachedConfig) {
    return cachedConfig;
  }

  const region = process.env.TEST_REGION || 'us-east-1';
  const stackName = process.env.TEST_STACK_NAME || 'kernelworx-ue1-dev';

  // Try to get config from CloudFormation stack first
  try {
    const cfClient = new CloudFormationClient({ region });
    const stackResponse = await cfClient.send(new DescribeStacksCommand({ StackName: stackName }));
    const stack = stackResponse.Stacks?.[0];
    
    if (stack?.Outputs) {
      // Parse Cognito info from the hosted UI URL output
      const hostedUiOutput = stack.Outputs.find(o => o.OutputKey === 'CognitoHostedUIUrl');
      if (hostedUiOutput?.OutputValue) {
        // URL format: https://login.dev.kernelworx.app.auth.us-east-1.amazoncognito.com/login?client_id=XXX&...
        const clientIdMatch = hostedUiOutput.OutputValue.match(/client_id=([^&]+)/);
        if (clientIdMatch) {
          const clientId = clientIdMatch[1];
          
          // Now we need to find the user pool ID. Look it up from Cognito.
          const cognitoConfig = await lookupCognitoConfig(region, clientId);
          const appSyncEndpoint = await lookupAppSyncEndpoint(region, 'kernelworx');
          
          cachedConfig = {
            userPoolId: cognitoConfig.userPoolId,
            userPoolClientId: clientId,
            appSyncEndpoint,
            region,
          };
          
          console.log('✅ Integration test environment configured');
          console.log(`   AppSync: ${cachedConfig.appSyncEndpoint}`);
          console.log(`   User Pool: ${cachedConfig.userPoolId}`);
          
          return cachedConfig;
        }
      }
    }
  } catch (error) {
    console.warn('Could not get config from CloudFormation, falling back to direct lookup:', error);
  }

  // Fallback: Look up resources directly
  const cognitoConfig = await lookupCognitoConfigByPoolName(region, 'kernelworx');
  const appSyncEndpoint = await lookupAppSyncEndpoint(region, 'kernelworx');

  cachedConfig = {
    userPoolId: cognitoConfig.userPoolId,
    userPoolClientId: cognitoConfig.clientId,
    appSyncEndpoint,
    region,
  };

  console.log('✅ Integration test environment configured');
  console.log(`   AppSync: ${cachedConfig.appSyncEndpoint}`);
  console.log(`   User Pool: ${cachedConfig.userPoolId}`);

  return cachedConfig;
}

/**
 * Find user pool ID given a client ID
 */
async function lookupCognitoConfig(region: string, clientId: string): Promise<{ userPoolId: string }> {
  const { CognitoIdentityProviderClient: CognitoClient, ListUserPoolsCommand } = await import('@aws-sdk/client-cognito-identity-provider');
  
  const client = new CognitoClient({ region });
  
  // List user pools and find which one has this client
  const poolsResponse = await client.send(new ListUserPoolsCommand({ MaxResults: 20 }));
  
  for (const pool of poolsResponse.UserPools || []) {
    if (!pool.Id) continue;
    
    const clientsResponse = await client.send(new ListUserPoolClientsCommand({
      UserPoolId: pool.Id,
      MaxResults: 10,
    }));
    
    const hasClient = clientsResponse.UserPoolClients?.some(c => c.ClientId === clientId);
    if (hasClient) {
      return { userPoolId: pool.Id };
    }
  }
  
  throw new Error(`Could not find user pool containing client ${clientId}`);
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
