/**
 * Client-neutral GraphQL error utilities.
 *
 * Shared by the authenticated Apollo client (`apollo.ts`) and the public
 * API-key client (`publicApollo.ts`) so both map server error codes to
 * user-facing messages the same way.
 */

/**
 * Error code extensions attached by the backend (see `ErrorCode` in
 * `src/utils/errors.py`; `extensions.code` and `extensions.errorType` are
 * the legacy/AppSync JS-resolver spellings).
 */
export interface GraphQLErrorExtensions {
  errorCode?: string;
  code?: string;
  errorType?: string;
  [key: string]: unknown;
}

/**
 * Extract an error code from GraphQL error extensions.
 */
export const extractErrorCode = (
  extensions: GraphQLErrorExtensions | undefined,
): string | undefined => {
  if (!extensions) {
    return undefined;
  }
  return extensions.errorCode || extensions.code || extensions.errorType;
};

/**
 * Map GraphQL error codes to user-friendly messages.
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
}
