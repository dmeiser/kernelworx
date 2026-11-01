/**
 * API client utilities for GraphQL operations.
 *
 * Provides common patterns for error handling, loading states,
 * and response processing used across the application.
 */

import type { GraphQLFormattedError } from 'graphql';

/**
 * Error type compatible with Apollo Client errors.
 * Apollo Client v4 removed ApolloLikeError export, so we define our own compatible type.
 */
export interface ApolloLikeError extends Error {
  graphQLErrors?: ReadonlyArray<GraphQLFormattedError>;
  /** Apollo Client v4 (`CombinedGraphQLErrors`) carries the same list as `errors`. */
  errors?: ReadonlyArray<GraphQLFormattedError>;
  networkError?: Error | null;
}

/**
 * The GraphQL error list carried by an Apollo error, in either generation's
 * shape: Apollo Client v4 wraps them in `CombinedGraphQLErrors.errors`; v3's
 * `ApolloError` exposed `graphQLErrors`. The app runs v4, so reading only the
 * v3 field never matches a real runtime error and every error-code-based
 * decision silently degrades to "unknown".
 */
function graphqlErrorsOf(error: ApolloLikeError): ReadonlyArray<GraphQLFormattedError> {
  if (Array.isArray(error.errors) && error.errors.length > 0) {
    return error.errors;
  }
  return Array.isArray(error.graphQLErrors) ? error.graphQLErrors : [];
}

/**
 * Result type for operations that can fail.
 */
export type Result<T, E = string> = { ok: true; data: T } | { ok: false; error: E };

/**
 * Create a success result.
 */
export function ok<T>(data: T): Result<T, never> {
  return { ok: true, data };
}

/**
 * Create an error result.
 */
export function err<E>(error: E): Result<never, E> {
  return { ok: false, error };
}

/**
 * Extract a user-friendly error message from an Apollo error.
 *
 * @param error - The Apollo error object
 * @param defaultMessage - Fallback message if no specific error found
 * @returns User-friendly error message
 */
// eslint-disable-next-line complexity
export function getErrorMessage(
  error: ApolloLikeError | Error | unknown,
  defaultMessage = 'An error occurred',
): string {
  if (!error) {
    return defaultMessage;
  }

  // Handle ApolloLikeError
  if (isApolloLikeError(error)) {
    // Check for GraphQL errors first
    const gqlErrors = graphqlErrorsOf(error);
    if (gqlErrors.length > 0) {
      return gqlErrors[0].message || defaultMessage;
    }

    // Check for network errors
    if (error.networkError) {
      return 'Network error. Please check your connection and try again.';
    }

    // Use the error message
    if (error.message) {
      // Filter out technical Apollo messages
      if (error.message.includes('Network request failed')) {
        return 'Network error. Please check your connection and try again.';
      }
      return error.message;
    }
  }

  // Handle standard Error
  if (error instanceof Error) {
    return error.message || defaultMessage;
  }

  // Handle string
  if (typeof error === 'string') {
    return error;
  }

  return defaultMessage;
}

/**
 * Type guard to check if an error is an ApolloLikeError.
 */
export function isApolloLikeError(error: unknown): error is ApolloLikeError {
  if (error === null || typeof error !== 'object') {
    return false;
  }
  const candidate = error as ApolloLikeError;
  return Array.isArray(candidate.errors) || Array.isArray(candidate.graphQLErrors);
}

/**
 * Extract error code from an Apollo error if available.
 *
 * Reads, in priority order:
 * 1. `errorInfo.errorCode` — AppSync's JS resolver `util.error(message, type,
 *    data, errorInfo)` returns the 4th argument as a TOP-LEVEL `errorInfo`
 *    field on each GraphQL error (NOT inside `extensions`); the Lambda
 *    passthrough/unit resolvers pass `{ errorCode }` there.
 * 2. Top-level `errorType` — where `util.error(message, type)` puts the type,
 *    and where AppSync's own auth layer puts `Unauthorized`.
 * 3. `extensions.errorCode` / `extensions.code` / `extensions.errorType` —
 *    the generic GraphQL convention, kept as defense in depth.
 *
 * AppSync does NOT populate `extensions` for resolver-emitted errors, so a
 * reader that only looks there returns `undefined` for every real backend
 * error and every code-based UX decision degrades to "unknown".
 *
 * @param error - The Apollo error object
 * @returns Error code string or undefined
 */
// eslint-disable-next-line complexity
export function getErrorCode(error: ApolloLikeError | unknown): string | undefined {
  if (!isApolloLikeError(error)) {
    return undefined;
  }

  const firstError = graphqlErrorsOf(error)[0] as
    | (GraphQLFormattedError & {
        errorType?: unknown;
        errorInfo?: { errorCode?: unknown } | null;
      })
    | undefined;
  if (!firstError) {
    return undefined;
  }

  // errorInfo.errorCode: the structured code the Lambda passthrough/unit
  // resolvers emit via util.error's 4th (errorInfo) argument.
  const structured = firstError.errorInfo?.errorCode;
  if (typeof structured === 'string') {
    return structured;
  }

  // Top-level errorType: util.error(message, type) puts the type here, and so
  // does AppSync's own auth layer ("Unauthorized").
  if (typeof firstError.errorType === 'string') {
    return firstError.errorType;
  }

  // extensions: the generic GraphQL convention, kept as defense in depth.
  const extensions = firstError.extensions as Record<string, unknown> | undefined;
  if (extensions) {
    for (const key of ['errorCode', 'code', 'errorType'] as const) {
      const value = extensions[key];
      if (typeof value === 'string') {
        return value;
      }
    }
  }

  return undefined;
}

/**
 * Check if an error indicates the user needs to re-authenticate.
 *
 * @param error - The Apollo error object
 * @returns True if the user should be redirected to login
 */
export function isAuthError(error: ApolloLikeError | unknown): boolean {
  const code = getErrorCode(error);
  return code === 'UNAUTHORIZED' || code === 'UNAUTHENTICATED';
}

/**
 * Check if an error indicates a permission/authorization issue.
 *
 * @param error - The Apollo error object
 * @returns True if the user lacks permission
 */
export function isForbiddenError(error: ApolloLikeError | unknown): boolean {
  const code = getErrorCode(error);
  return code === 'FORBIDDEN';
}

/**
 * Check if an error indicates the resource was not found.
 *
 * @param error - The Apollo error object
 * @returns True if the resource doesn't exist
 */
export function isNotFoundError(error: ApolloLikeError | unknown): boolean {
  const code = getErrorCode(error);
  return (
    code === 'NOT_FOUND' || code === 'PROFILE_NOT_FOUND' || code === 'CAMPAIGN_NOT_FOUND' || code === 'ORDER_NOT_FOUND'
  );
}

/**
 * Check if an error indicates a validation failure.
 *
 * @param error - The Apollo error object
 * @returns True if the input failed validation
 */
export function isValidationError(error: ApolloLikeError | unknown): boolean {
  const code = getErrorCode(error);
  return code === 'VALIDATION_ERROR' || code === 'INVALID_INPUT';
}

/**
 * Public checkout error mapping (SEC-11).
 *
 * The public order pages are anonymous: they carry no session, and the person
 * reading the message may be an attacker probing the link. Two failures have to
 * be closed at once — an unmapped code falling back to the raw server message
 * (which can quote a DynamoDB or AWS SDK fault verbatim), and a crafted
 * `INVALID_INPUT` message being thrown away for a generic string, which is what
 * makes the server's field-level contact rules useless to a buyer. So: the
 * backend's own `INVALID_INPUT` wording is preserved (it is written by our
 * resolvers, and re-checked for infrastructure leakage), every other code gets
 * a curated buyer-facing sentence, and anything unrecognized gets the generic
 * one. The raw message is never the default.
 */

/** Shown for any submission failure the public path cannot name safely. */
export const PUBLIC_CHECKOUT_GENERIC_ERROR = 'Something went wrong while placing your order. Please try again.';

/** Shown when the request never got a server answer. */
export const PUBLIC_CHECKOUT_NETWORK_ERROR = 'We could not reach the server. Check your connection and try again.';

/**
 * Codes whose server message is a buyer-facing sentence the backend wrote on
 * purpose. `VALIDATION_ERROR` is deliberately absent: it is emitted by input
 * coercion layers, not by our resolvers, so its text is not ours to vouch for.
 */
const PUBLIC_PRESERVED_MESSAGE_CODES = new Set(['INVALID_INPUT']);

/** Curated wording for the codes the public checkout path can legitimately hit. */
const PUBLIC_CHECKOUT_ERROR_MESSAGES: Record<string, string> = {
  NOT_FOUND: 'This order link is no longer available.',
  CAMPAIGN_NOT_FOUND: 'This order link is no longer available.',
  ORDER_NOT_FOUND: 'This order link is no longer available.',
  FORBIDDEN: 'This order link is no longer available.',
  UNAUTHORIZED: 'This order link is no longer available.',
  UNAUTHENTICATED: 'This order link is no longer available.',
  PUBLIC_ORDER_LIMIT_EXCEEDED: 'This campaign has reached its public order limit.',
  RESOURCE_BUSY: 'The order could not be placed right now. Please try again.',
  CONFLICT: 'The order could not be placed right now. Please try again.',
  ConflictException: 'The order could not be placed right now. Please try again.',
  SERVICE_UNAVAILABLE: 'The service is temporarily unavailable. Please try again later.',
};

/**
 * Wording that betrays the stack rather than the order: SDK exception names,
 * service endpoints, throttling verdicts. Even a code we preserve the message
 * for can carry one of these if a fault was re-wrapped as `INVALID_INPUT`.
 */
const INFRASTRUCTURE_MESSAGE_PATTERN =
  /dynamodb|conditionalcheck|resourceinuse|throttl|accessdenied|amazonaws|\.amazon\.|internal server error|an error occurred \(|cannot deserialize|unmarshalling|stack trace|traceback/i;

/** Whether a server message is safe to show a buyer verbatim. */
export function isBuyerFacingMessage(message: string): boolean {
  const trimmed = message.trim();
  if (!trimmed || trimmed.length > 500) return false;
  return !INFRASTRUCTURE_MESSAGE_PATTERN.test(trimmed);
}

/** Whether the failure is a transport one — no server answer at all. */
function isNetworkFailure(error: unknown): boolean {
  if (isApolloLikeError(error) && error.networkError) return true;
  return error instanceof Error && /network request failed|failed to fetch/i.test(error.message);
}

/** Whether this error's own wording is the one to show. */
function preserveServerMessage(code: string | undefined, message: string): boolean {
  return code !== undefined && PUBLIC_PRESERVED_MESSAGE_CODES.has(code) && isBuyerFacingMessage(message);
}

/**
 * Map a public-checkout submission failure to a message safe to render for an
 * anonymous buyer.
 */
export function mapPublicSubmissionErrorMessage(error: unknown): string {
  if (isNetworkFailure(error)) return PUBLIC_CHECKOUT_NETWORK_ERROR;
  const code = getErrorCode(error);
  const message = getErrorMessage(error, '');
  if (preserveServerMessage(code, message)) return message.trim();
  return (code !== undefined ? PUBLIC_CHECKOUT_ERROR_MESSAGES[code] : undefined) ?? PUBLIC_CHECKOUT_GENERIC_ERROR;
}

/**
 * Format a date string for display.
 * Returns empty string for null/undefined values.
 *
 * @param dateString - ISO date string
 * @param format - Output format: 'short', 'long', or 'iso'
 * @returns Formatted date string
 */
// eslint-disable-next-line complexity
export function formatDate(dateString: string | null | undefined, format: 'short' | 'long' | 'iso' = 'short'): string {
  if (!dateString) {
    return '';
  }

  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) {
      return '';
    }

    switch (format) {
      case 'iso':
        return date.toISOString().split('T')[0];
      case 'long':
        return date.toLocaleDateString('en-US', {
          weekday: 'long',
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        });
      case 'short':
      default:
        return date.toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
    }
  } catch {
    return '';
  }
}

/**
 * Currency formatters are built once per currency and reused: `Intl.NumberFormat`
 * construction is comparatively expensive, and list rendering calls the
 * formatter per row per render.
 */
const currencyFormatters = new Map<string, Intl.NumberFormat>();

function currencyFormatterFor(currency: string): Intl.NumberFormat {
  const existing = currencyFormatters.get(currency);
  if (existing) {
    return existing;
  }
  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  currencyFormatters.set(currency, formatter);
  return formatter;
}

/**
 * Format a currency value for display.
 *
 * @param amount - Numeric amount
 * @param currency - Currency code (default: USD)
 * @returns Formatted currency string
 */
export function formatCurrency(amount: number | null | undefined, currency = 'USD'): string {
  if (amount === null || amount === undefined) {
    return '$0.00';
  }

  return currencyFormatterFor(currency).format(amount);
}

/**
 * Format a phone number for display.
 *
 * @param phone - Raw phone number string
 * @returns Formatted phone number or the original string when unrecognizable
 */
export function formatPhoneNumber(phone: string | undefined): string {
  if (!phone) {
    return '—';
  }

  const digits = phone.replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) {
    return `(${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7, 11)}`;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6, 10)}`;
  }
  return phone;
}

/**
 * Safely parse a numeric value from unknown input.
 *
 * @param value - Input value (may be string, number, or undefined)
 * @param defaultValue - Default if parsing fails
 * @returns Parsed number or default
 */
// eslint-disable-next-line complexity
export function parseNumber(value: unknown, defaultValue = 0): number {
  if (typeof value === 'number' && !isNaN(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const parsed = parseFloat(value);
    if (!isNaN(parsed)) {
      return parsed;
    }
  }

  return defaultValue;
}

/**
 * Safely parse an integer value from unknown input.
 *
 * @param value - Input value (may be string, number, or undefined)
 * @param defaultValue - Default if parsing fails
 * @returns Parsed integer or default
 */
// eslint-disable-next-line complexity
export function parseInt(value: unknown, defaultValue = 0): number {
  if (typeof value === 'number' && !isNaN(value)) {
    return Math.floor(value);
  }

  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    if (!isNaN(parsed)) {
      return parsed;
    }
  }

  return defaultValue;
}
