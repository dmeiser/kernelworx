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
} from "@apollo/client";
import { setContext } from "@apollo/client/link/context";
import { ErrorLink } from "@apollo/client/link/error";
import { CombinedGraphQLErrors } from "@apollo/client/errors";
import { fetchAuthSession } from "aws-amplify/auth";

/**
 * HTTP link to AppSync endpoint
 */
const httpLink = createHttpLink({
  uri: import.meta.env.VITE_APPSYNC_ENDPOINT,
});

/**
 * Authentication link - adds Cognito JWT to Authorization header
 */
const authLink = setContext(async (_, { headers }) => {
  try {
    const session = await fetchAuthSession();
    const token = session.tokens?.idToken?.toString();

    return {
      headers: {
        ...headers,
        Authorization: token ? `Bearer ${token}` : "",
      },
    };
  } catch (error) {
    console.error("Failed to fetch auth session for GraphQL request:", error);
    return { headers };
  }
});

/**
 * Error link - global error handling for GraphQL errors
 */
const errorLink = new ErrorLink(({ error, operation }) => {
  if (CombinedGraphQLErrors.is(error)) {
    error.errors.forEach((err) => {
      const { message, locations, path, extensions } = err;
      const errorCode = extensions?.errorCode as string | undefined;

      console.error(
        `[GraphQL error]: Message: ${message}, Code: ${errorCode}, Location: ${locations}, Path: ${path}`,
      );

      // Map errorCode to user-facing messages
      // These will be displayed via toast notifications in the UI
      const userMessage = mapErrorCodeToMessage(errorCode, message);

      // Emit custom event for UI to handle
      window.dispatchEvent(
        new CustomEvent("graphql-error", {
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
    console.error(`[Network/Error]: ${error.message}`);

    // Emit network error event
    window.dispatchEvent(
      new CustomEvent("graphql-error", {
        detail: {
          errorCode: "NETWORK_ERROR",
          message: "Network error. Please check your connection and try again.",
          operation: operation.operationName,
        },
      }),
    );
  }
});

/**
 * Map GraphQL error codes to user-friendly messages
 */
function mapErrorCodeToMessage(
  errorCode: string | undefined,
  defaultMessage: string,
): string {
  if (!errorCode) return defaultMessage;

  const errorMessages: Record<string, string> = {
    // Authorization errors
    FORBIDDEN: "You do not have permission to perform this action.",
    UNAUTHORIZED: "Please sign in to continue.",

    // Validation errors
    VALIDATION_ERROR: "Please check your input and try again.",
    INVALID_INPUT: "Invalid input provided.",

    // Not found errors
    NOT_FOUND: "The requested resource was not found.",
    PROFILE_NOT_FOUND: "Profile not found.",
    SEASON_NOT_FOUND: "Season not found.",
    ORDER_NOT_FOUND: "Order not found.",

    // Conflict errors
    ALREADY_EXISTS: "This item already exists.",
    DUPLICATE_ENTRY: "A duplicate entry was detected.",

    // Invite/sharing errors
    INVITE_EXPIRED: "This invite code has expired.",
    INVITE_NOT_FOUND: "Invalid invite code.",
    ALREADY_SHARED: "This profile is already shared with this user.",

    // Season/order errors
    SEASON_LOCKED: "This season is locked and cannot be modified.",
    ORDER_ALREADY_DELETED: "This order has already been deleted.",

    // Generic errors
    INTERNAL_ERROR: "An internal error occurred. Please try again.",
    SERVICE_UNAVAILABLE:
      "Service temporarily unavailable. Please try again later.",
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
          // Merge strategies for list queries
          listMyProfiles: {
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listSharedProfiles: {
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listSeasonsByProfile: {
            merge(_existing, incoming) {
              return incoming;
            },
          },
          listOrdersBySeason: {
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
      fetchPolicy: "cache-and-network",
      errorPolicy: "all",
    },
    query: {
      fetchPolicy: "network-only",
      errorPolicy: "all",
    },
    mutate: {
      errorPolicy: "all",
    },
  },
});
