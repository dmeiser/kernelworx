import { ApolloClient, InMemoryCache, HttpLink, ApolloLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { signInUser, AuthResult } from './cognitoAuth';
import { getAwsConfig } from './awsConfig';

interface AuthConfig {
  accessToken: string;
}

export interface AuthenticatedClientResult {
  client: ApolloClient<any>;
  accountId: string;
  email: string;
}

/**
 * Create an authenticated Apollo Client for a specific user type.
 * 
 * @param userType - 'owner', 'contributor', or 'readonly'
 * @returns Apollo Client and user info (accountId, email)
 */
export async function createAuthenticatedClient(
  userType: 'owner' | 'contributor' | 'readonly'
): Promise<AuthenticatedClientResult> {
  // Get endpoint dynamically from AWS
  const config = await getAwsConfig();
  const endpoint = config.appSyncEndpoint;

  // Get credentials for specified user type
  let email: string;
  let password: string;

  switch (userType) {
    case 'owner':
      email = process.env.TEST_OWNER_EMAIL!;
      password = process.env.TEST_OWNER_PASSWORD!;
      break;
    case 'contributor':
      email = process.env.TEST_CONTRIBUTOR_EMAIL!;
      password = process.env.TEST_CONTRIBUTOR_PASSWORD!;
      break;
    case 'readonly':
      email = process.env.TEST_READONLY_EMAIL!;
      password = process.env.TEST_READONLY_PASSWORD!;
      break;
  }

  if (!email || !password) {
    throw new Error(`Credentials not set for ${userType} user`);
  }

  // Sign in and get tokens + account ID
  const authResult = await signInUser(email, password);

  // Create HTTP link
  const httpLink = new HttpLink({
    uri: endpoint,
  });

  // Add authentication header
  const authLink = setContext((_, { headers }) => {
    return {
      headers: {
        ...headers,
        authorization: `Bearer ${authResult.tokens.idToken}`,
      },
    };
  });

  // Create and return client
  const client = new ApolloClient({
    link: authLink.concat(httpLink),
    cache: new InMemoryCache(),
    defaultOptions: {
      query: { fetchPolicy: 'no-cache' },
      mutate: { fetchPolicy: 'no-cache' },
    },
  });

  return {
    client,
    accountId: authResult.accountId,
    email: authResult.email,
  };
}


