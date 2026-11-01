/**
 * Apollo Client configuration for public AppSync GraphQL API
 *
 * Uses API key authentication for public orders and receipts.
 */

import {
  ApolloClient,
  InMemoryCache,
  createHttpLink,
  ApolloLink,
  type DefaultContext,
  type ErrorLike,
} from '@apollo/client';
import { ErrorLink } from '@apollo/client/link/error';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { setContext } from '@apollo/client/link/context';
import type { GraphQLFormattedError } from 'graphql';
import { extractErrorCode } from './errorCodes';
import type { GraphQLErrorExtensions } from './errorCodes';

/**
 * Shared error-code -> message mapping, re-exported so callers can import it
 * from either Apollo client module.
 */
export { mapErrorCodeToMessage } from './errorCodes';

/**
 * HTTP link to AppSync endpoint
 */
const httpLink = createHttpLink({
  // Same-origin: dev/prod serve /graphql through the site's CloudFront
  // distribution, so no absolute endpoint is configured. Ephemeral and local
  // `vite dev` builds set VITE_APPSYNC_ENDPOINT to the direct AppSync URL.
  uri: import.meta.env.VITE_APPSYNC_ENDPOINT ?? '/graphql',
});

/**
 * API key link - adds x-api-key header
 */
const apiKeyLink = setContext(async (_prevContext: DefaultContext) => {
  const apiKey = import.meta.env.VITE_APPSYNC_API_KEY;
  if (!apiKey) {
    throw new Error('VITE_APPSYNC_API_KEY is not defined');
  }
  return {
    headers: {
      ..._prevContext.headers,
      'x-api-key': apiKey,
    },
  };
});

/**
 * GraphQL error with extensions
 */
interface GraphQLErrorWithExtensions extends GraphQLFormattedError {
  extensions?: GraphQLErrorExtensions;
}

/**
 * Process GraphQL error
 */
const processGraphQLError = (err: GraphQLFormattedError): void => {
  const typedErr = err as GraphQLErrorWithExtensions;
  const { message, locations, path, extensions } = typedErr;
  const errorCode = extractErrorCode(extensions);

  if (import.meta.env.DEV) {
    console.error(`[GraphQL error]: Message: ${message}, Code: ${errorCode}, Location: ${locations}, Path: ${path}`);
  }
  // However, the public client is used in public pages, so we might not want to dispatch events that are handled by the app.
  // For now, we'll just log.
};

/**
 * Process network error
 */
const processNetworkError = (networkError: ErrorLike): void => {
  if (import.meta.env.DEV) {
    console.error(`[Network/Error]: ${networkError.message}`);
  }
};

/**
 * Error handler used by the ErrorLink (extracted for testability)
 */
export const handlePublicApolloError = ({ error }: ErrorLink.ErrorHandlerOptions) => {
  if (CombinedGraphQLErrors.is(error)) {
    error.errors.forEach((err) => processGraphQLError(err));
  } else {
    processNetworkError(error as ErrorLike);
  }
};

/**
 * Error link - global error handling for GraphQL errors
 */
const errorLink = new ErrorLink(handlePublicApolloError);

/**
 * Apollo Client instance for public use
 */
export const publicApolloClient = new ApolloClient({
  link: ApolloLink.from([errorLink, apiKeyLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          // We don't have specific merge strategies for public queries, but we can add if needed.
          // For now, we'll use the default.
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: {
      // Cache-first by default: the receipt read (publicGetOrderReceipt) is
      // immutable per token, so PublicReceiptPage can serve it from cache.
      // The token-bearing offer query opts into 'no-cache' itself (see
      // usePublicOrderOffer), because its pre-signed QR URLs expire after
      // 15 minutes.
      fetchPolicy: 'cache-first',
      errorPolicy: 'all',
    },
    query: {
      fetchPolicy: 'cache-first',
      errorPolicy: 'all',
    },
    mutate: {
      errorPolicy: 'none',
    },
  } as unknown as NonNullable<ConstructorParameters<typeof ApolloClient>[0]['defaultOptions']>,
});
