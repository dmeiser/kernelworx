/**
 * Apollo Client for the public order pages (/o/..., /r/...).
 *
 * These routes are anonymous by design: the share/receipt token in the URL is
 * the authorization, and the AppSync API key is only a transport credential
 * that unlocks the three `@aws_api_key` root fields. Two measured facts about
 * that auth mode shape this client:
 *
 * 1. AppSync's auth directives are an EXCLUSIVE allow-list. A request that
 *    carries an `Authorization` header (a signed-in seller previewing their own
 *    share link) is REFUSED outright on a key-only field, so this client must
 *    never attach the Amplify session. It deliberately does not import
 *    `aws-amplify/auth` at all - the main client's fail-closed auth link stays
 *    on the authenticated client only.
 * 2. AppSync throttles API-key traffic in its own bucket and answers a throttle
 *    with HTTP 429 whose body is
 *    `{"errors":[{"errorType":"LimitExceededException","message":"Rate limit exceeded"}]}`
 *    and NO `Retry-After` header, so the backoff below is self-driven.
 *
 * Token-bearing queries are never cached: the cache key would hold a capability
 * token in browser memory for no benefit (each page reads it exactly once).
 */

import { ApolloClient, ApolloLink, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { RetryLink } from '@apollo/client/link/retry';
import { ServerError } from '@apollo/client/errors';

/** Header AppSync reads for the API_KEY auth mode. */
export const API_KEY_HEADER = 'x-api-key';

/** errorType AppSync puts in the 429 body; there is no Retry-After header to read. */
export const RATE_LIMIT_ERROR_TYPE = 'LimitExceededException';

/** HTTP status of an AppSync API-key throttle. */
export const RATE_LIMIT_STATUS = 429;

/** Extra attempts after the first request before the throttle is surfaced. */
export const RATE_LIMIT_MAX_ATTEMPTS = 4;

/** First backoff delay; the RetryLink doubles each subsequent delay. */
export const RATE_LIMIT_INITIAL_DELAY_MS = 500;

/** Ceiling for a single backoff delay. */
export const RATE_LIMIT_MAX_DELAY_MS = 4000;

/**
 * Headers for a public request: the API key only. Never an `Authorization`
 * header - a stray session token makes AppSync reject the call.
 */
export function publicRequestHeaders(): Record<string, string> {
  const apiKey: string | undefined = import.meta.env.VITE_APPSYNC_API_KEY;
  return apiKey ? { [API_KEY_HEADER]: apiKey } : {};
}

/**
 * True when a failure is the AppSync API-key throttle. The 429 carries no
 * Retry-After, so the caller supplies its own backoff.
 */
export function isRateLimited(error: unknown): boolean {
  if (ServerError.is(error)) {
    return error.statusCode === RATE_LIMIT_STATUS || error.bodyText.includes(RATE_LIMIT_ERROR_TYPE);
  }
  return error instanceof Error && error.message.includes('Rate limit exceeded');
}

/** Retry link for the self-driven 429 backoff (no server retry hint exists). */
export function createRateLimitRetryLink(): RetryLink {
  return new RetryLink({
    attempts: {
      max: RATE_LIMIT_MAX_ATTEMPTS,
      retryIf: (error) => isRateLimited(error),
    },
    delay: {
      initial: RATE_LIMIT_INITIAL_DELAY_MS,
      max: RATE_LIMIT_MAX_DELAY_MS,
      jitter: false,
    },
  });
}

/** Attaches `x-api-key` and nothing else. */
export function createApiKeyLink() {
  return setContext(async (_operation: unknown, previousContext: Record<string, unknown>) => ({
    ...previousContext,
    headers: { ...(previousContext.headers as Record<string, string> | undefined), ...publicRequestHeaders() },
  }));
}

/**
 * Build a public client. Exported separately from the singleton so tests can
 * construct one against a local endpoint without touching module state.
 */
export function createPublicApolloClient(): ApolloClient {
  const httpLink = createHttpLink({
    // Same-origin like the main client: dev/prod serve /graphql through the
    // site's CloudFront distribution, whose Managed-AllViewerExceptHostHeader
    // origin-request policy forwards x-api-key. Ephemeral and `vite dev` point
    // VITE_APPSYNC_ENDPOINT at the direct AppSync hostname.
    uri: import.meta.env.VITE_APPSYNC_ENDPOINT ?? '/graphql',
  });

  return new ApolloClient({
    link: ApolloLink.from([createRateLimitRetryLink(), createApiKeyLink(), httpLink]),
    cache: new InMemoryCache(),
    defaultOptions: {
      query: { fetchPolicy: 'no-cache', errorPolicy: 'all' },
      watchQuery: { fetchPolicy: 'no-cache', errorPolicy: 'all' },
      mutate: { errorPolicy: 'none' },
      // Same cast the main client uses: Apollo v4 wants per-client default
      // options declared in the type system, and this partial object satisfies
      // the runtime contract without that declaration.
    } as unknown as NonNullable<ConstructorParameters<typeof ApolloClient>[0]['defaultOptions']>,
  });
}

/** The client the public routes are wrapped in (see App.tsx). */
export const publicApolloClient = createPublicApolloClient();
