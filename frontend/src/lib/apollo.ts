/**
 * Apollo Client configuration for AppSync GraphQL API
 *
 * Integrates with Cognito authentication to add JWT tokens to requests.
 */

import {
  ApolloClient,
  InMemoryCache,
  createHttpLink,
  ApolloLink,
  type DefaultContext,
  type Operation,
  type ErrorLike,
} from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { ErrorLink } from '@apollo/client/link/error';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import type { GraphQLFormattedError } from 'graphql';
import { fetchAuthSession } from 'aws-amplify/auth';

/**
 * HTTP link to AppSync endpoint
 */
const httpLink = createHttpLink({
  uri: import.meta.env.VITE_APPSYNC_ENDPOINT,
});

/**
 * Authentication link - adds Cognito JWT to Authorization header
 *
 * IMPORTANT: This link ensures a valid token exists before sending requests.
 * If no token is available, it throws an error to prevent unauthenticated
 * requests from reaching AppSync with empty ctx.identity.sub values.
 */
type AuthHeadersContext = DefaultContext & { headers?: Record<string, string> };

export const getAuthContext = async (_operation: Operation, prevContext: AuthHeadersContext) => {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();

  if (!token) {
    // Don't send the request without a valid token
    // This prevents race conditions where queries fire before auth is ready
    throw new Error('No valid auth token available');
  }

  return {
    headers: {
      ...prevContext.headers,
      Authorization: `Bearer ${token}`,
    },
  };
};

const authLink = setContext(
  getAuthContext as (
    request: unknown,
    previousContext: Record<string, unknown>,
  ) => Promise<{ headers: Record<string, string> }>,
);

/**
 * GraphQL error with extensions
 */
interface GraphQLErrorWithExtensions extends GraphQLFormattedError {
  extensions?: { errorCode?: string };
}

/**
 * Error handler used by the ErrorLink (extracted for testability)
 */
export const handleApolloError = ({ operation, error }: ErrorLink.ErrorHandlerOptions) => {
  // Check if this is a GraphQL error
  if (CombinedGraphQLErrors.is(error)) {
    error.errors.forEach((err: GraphQLFormattedError) => {
      const typedErr = err as GraphQLErrorWithExtensions;
      const { message, locations, path, extensions } = typedErr;
      const errorCode = extensions?.errorCode;

      console.error(`[GraphQL error]: Message: ${message}, Code: ${errorCode}, Location: ${locations}, Path: ${path}`);

      // Map errorCode to user-facing messages
      // These will be displayed via toast notifications in the UI
      const userMessage = mapErrorCodeToMessage(errorCode, message);

      // Emit custom event for UI to handle
      window.dispatchEvent(
        new CustomEvent('graphql-error', {
          detail: {
            errorCode,
            message: userMessage,
            operation: operation.operationName,
          },
        }),
      );
    });
  } else {
    // Network or other error
    const networkError = error as ErrorLike;
    console.error(`[Network/Error]: ${networkError.message}`);

    // Emit network error event
    window.dispatchEvent(
      new CustomEvent('graphql-error', {
        detail: {
          errorCode: 'NETWORK_ERROR',
          message: 'Network error. Please check your connection and try again.',
          operation: operation.operationName,
        },
      }),
    );
  }
};

/**
 * Error link - global error handling for GraphQL errors
 */
const errorLink = new ErrorLink(handleApolloError);

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

    // Invite/sharing errors
    INVITE_EXPIRED: 'This invite code has expired.',
    INVITE_NOT_FOUND: 'Invalid invite code.',
    ALREADY_SHARED: 'This profile is already shared with this user.',

    // Campaign/order errors
    CAMPAIGN_LOCKED: 'This campaign is locked and cannot be modified.',
    ORDER_ALREADY_DELETED: 'This order has already been deleted.',

    // Generic errors
    INTERNAL_ERROR: 'An internal error occurred. Please try again.',
    SERVICE_UNAVAILABLE: 'Service temporarily unavailable. Please try again later.',
  };

  return errorMessages[errorCode] || defaultMessage;
}

/**
 * Apollo Client instance
 */
export const apolloClient = new ApolloClient({
  link: ApolloLink.from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          // Merge strategies for list queries - these are invoked by Apollo internally
          listMyProfiles: {
            /* v8 ignore next 3 -- Apollo internal merge callback */
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listMyShares: {
            /* v8 ignore next 3 -- Apollo internal merge callback */
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listCampaignsByProfile: {
            /* v8 ignore next 3 -- Apollo internal merge callback */
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listOrdersByCampaign: {
            /* v8 ignore next 3 -- Apollo internal merge callback */
            merge(_existing, incoming) {
              return incoming;
            },
          },
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
      errorPolicy: 'all',
    },
    query: {
      fetchPolicy: 'cache-first',
      errorPolicy: 'all',
    },
    mutate: {
      errorPolicy: 'all',
    },
  },
});
