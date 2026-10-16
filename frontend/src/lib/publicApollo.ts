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
import { setContext } from "@apollo/client/link/context";
import type { GraphQLFormattedError } from 'graphql';

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
const apiKeyLink = setContext(
  async (_prevContext: DefaultContext) => {
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
  },
);

/**
 * GraphQL error with extensions
 */
interface GraphQLErrorWithExtensions extends GraphQLFormattedError {
  extensions?: { errorCode?: string; code?: string; errorType?: string };
};

/**
 * Extract error code from extensions
 */
const extractErrorCode = (extensions: GraphQLErrorWithExtensions['extensions']): string | undefined => {
  if (!extensions) {
    return undefined;
  }
  return extensions.errorCode || extensions.code || extensions.errorType;
};

/**
 * Map GraphQL error codes to user-friendly messages
 */
export function mapErrorCodeToMessage(errorCode: string | undefined, defaultMessage: string): string {
  if (!errorCode) return defaultMessage;

  const errorMessages: Record<string, string> = {
    // Authorization errors
    FORBIDDEN: 'You do not have permission to perform this action.',
    UNAUTHORIZED: 'Please sign in to continue.',

    // Validation errors
    VALIDATION_ERROR: 'Please check your input and try again.',
    INVALID_INPUT: 'Invalid input provided.',

    // Not found errors
    NOT_FOUND: 'The requested resource was not found.',
    PROFILE_NOT_FOUND: 'Profile not found.',
    CAMPAIGN_NOT_FOUND: 'Campaign not found.',
    ORDER_NOT_FOUND: 'Order not found.',

    // Conflict errors
    ALREADY_EXISTS: 'This item already exists.',
    DUPLICATE_ENTRY: 'A duplicate entry was detected.',
    RESOURCE_BUSY: 'This operation could not be completed right now. Please try again.',
    CONFLICT: 'The operation conflicts with the current state. Please refresh and try again.',

    // Invite/sharing errors
    INVITE_EXPIRED: 'This invite code has expired.',
    INVITE_NOT_FOUND: 'Invalid invite code.',
    ALREADY_SHARED: 'This profile is already shared with this user.',

    // Campaign/order errors
    PUBLIC_ORDER_LIMIT_EXCEEDED: 'This campaign has reached its public order limit.',
    CAMPAIGN_LOCKED: 'This campaign is locked and cannot be modified.',
    ORDER_ALREADY_DELETED: 'This order has already been deleted.',

    // Generic errors
    INTERNAL_ERROR: 'An internal error occurred. Please try again.',
    SERVICE_UNAVAILABLE: 'Service temporarily unavailable. Please try again later.',
  };

  return errorMessages[errorCode] || defaultMessage;
};

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
      fetchPolicy: 'no-cache', // No caching as per design for token-bearing queries, but we are not using tokens. However, to be safe, we set no-cache.
      errorPolicy: 'all',
    },
    query: {
      fetchPolicy: 'no-cache',
      errorPolicy: 'all',
    },
    mutate: {
      errorPolicy: 'none',
    },
  } as unknown as NonNullable<ConstructorParameters<typeof ApolloClient>[0]['defaultOptions']>,
});
