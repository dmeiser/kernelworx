import { ApolloClient, InMemoryCache, HttpLink, ApolloLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { RetryLink } from '@apollo/client/link/retry';
import { signInUser, AuthResult } from './cognitoAuth';
import { getAwsConfig } from './awsConfig';

/**
 * Retry transient transport failures between the CI runner and AppSync.
 *
 * CI occasionally fails a whole suite in `beforeAll` with undici's
 * `TypeError: fetch failed` (cause: `read ECONNRESET`) — a TCP connection
 * reset where no HTTP response was ever received. Without a retry that
 * single reset skips every test in the suite and fails the run.
 *
 * Only errors WITHOUT an HTTP status code are retried: a response was never
 * received, so re-sending the request is the standard recovery. HTTP-level
 * failures (4xx/5xx `ServerError`) and GraphQL errors returned in a 200
 * response are never retried here — mutations are not idempotent and
 * Apollo Client 4's RetryLink already passes GraphQL results through without
 * invoking this callback.
 */
const transportRetryLink = new RetryLink({
  attempts: (count, _operation, error) => {
    const receivedResponse =
      typeof (error as { statusCode?: number }).statusCode === 'number';
    if (!receivedResponse && count < 3) {
      console.warn(
        `⚠️  AppSync transport error (attempt ${count}/3), retrying: ${error.message}`
      );
      return true;
    }
    return false;
  },
  delay: { initial: 500, max: 3000, jitter: true },
});

interface AuthConfig {
  accessToken: string;
}

/**
 * Create an Apollo Client for the API_KEY auth mode — the anonymous buyer's mode.
 *
 * The public order surface (`publicGetOrderOffer`, `publicCreateOrder`,
 * `publicGetOrderReceipt`) carries `@aws_api_key`, and a Cognito caller is
 * refused on those fields (directive exclusivity, measured in the KW-PUBLIC-
 * ORDERS-SPIKE-1 spike). So the integration suite needs a client that sends
 * ONLY `x-api-key` and never an `Authorization` header — attaching a session
 * would change which auth mode AppSync resolves and make the test prove
 * nothing about the anonymous path.
 *
 * The key comes from `TEST_APPSYNC_API_KEY`, written by
 * `scripts/generate_integration_env.py` and exported by
 * `scripts/ephemeral-env.sh` (both omit it when the stack predates the
 * public-orders auth-mode change).
 */
export function createApiKeyClient(): ApolloClient<any> {
  const apiKey = process.env.TEST_APPSYNC_API_KEY;
  if (!apiKey) {
    throw new Error(
      'TEST_APPSYNC_API_KEY is not set; the stack has no API_KEY auth mode (see scripts/generate_integration_env.py)'
    );
  }

  const endpoint = process.env.TEST_APPSYNC_ENDPOINT!;
  const httpLink = new HttpLink({ uri: endpoint });
  const keyLink = setContext((_, { headers }) => ({
    headers: { ...headers, 'x-api-key': apiKey },
  }));

  return new ApolloClient({
    link: keyLink.concat(transportRetryLink).concat(httpLink),
    cache: new InMemoryCache(),
    defaultOptions: {
      query: { fetchPolicy: 'no-cache' },
      mutate: { fetchPolicy: 'no-cache' },
    },
  });
}

/**
 * Create an Apollo Client that sends NO credentials at all.
 *
 * Used to pin that the public fields are not open to the world: with neither a
 * Cognito token nor an API key, AppSync must refuse the call.
 */
export function createUnauthenticatedClient(): ApolloClient<any> {
  const httpLink = new HttpLink({ uri: process.env.TEST_APPSYNC_ENDPOINT! });
  return new ApolloClient({
    link: transportRetryLink.concat(httpLink),
    cache: new InMemoryCache(),
    defaultOptions: {
      query: { fetchPolicy: 'no-cache' },
      mutate: { fetchPolicy: 'no-cache' },
    },
  });
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

  // Sign in and get tokens + account ID. The owner admin has a TOTP device
  // (#336), so pass its secret to answer the SOFTWARE_TOKEN_MFA challenge.
  const authResult = await signInUser(
    email,
    password,
    userType === 'owner' ? process.env.TEST_OWNER_TOTP_SECRET : undefined,
  );

  // Create HTTP link
  const httpLink = new HttpLink({
    uri: endpoint,
  });

  // Add authentication header (AppSync Cognito auth expects the raw token)
  const authLink = setContext((_, { headers }) => {
    return {
      headers: {
        ...headers,
        Authorization: authResult.tokens.idToken,
      },
    };
  });

  // Create and return client (transport retries wrap the HTTP link so a
  // connection reset re-sends the request instead of killing the suite)
  const client = new ApolloClient({
    link: authLink.concat(transportRetryLink).concat(httpLink),
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


