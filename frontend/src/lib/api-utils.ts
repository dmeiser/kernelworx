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
  networkError?: Error | null;
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
    if (error.graphQLErrors && error.graphQLErrors.length > 0) {
      const firstError = error.graphQLErrors[0];
      return firstError.message || defaultMessage;
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
  return (
    error !== null &&
    typeof error === 'object' &&
    'graphQLErrors' in error &&
    Array.isArray((error as ApolloLikeError).graphQLErrors)
  );
}

/**
 * Extract error code from an Apollo error if available.
 *
 * @param error - The Apollo error object
 * @returns Error code string or undefined
 */
// eslint-disable-next-line complexity
export function getErrorCode(error: ApolloLikeError | unknown): string | undefined {
  if (!isApolloLikeError(error)) {
    return undefined;
  }

  const firstError = error.graphQLErrors?.[0];
  if (!firstError) {
    return undefined;
  }

  // Check extensions.errorCode (our custom error format)
  const extensions = firstError.extensions as Record<string, unknown> | undefined;
  if (extensions?.errorCode && typeof extensions.errorCode === 'string') {
    return extensions.errorCode;
  }

  // Check extensions.code (standard GraphQL error format)
  if (extensions?.code && typeof extensions.code === 'string') {
    return extensions.code;
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

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
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
