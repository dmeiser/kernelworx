/**
 * Tests for API client utilities.
 */
import { describe, it, expect } from 'vitest';
import type { GraphQLFormattedError } from 'graphql';
import type { ApolloLikeError } from './api-utils';
import {
  ok,
  err,
  getErrorMessage,
  isApolloLikeError,
  getErrorCode,
  isAuthError,
  isForbiddenError,
  isNotFoundError,
  isValidationError,
  formatDate,
  formatCurrency,
  formatPhoneNumber,
  parseNumber,
  parseInt,
} from './api-utils';

// Helper to create mock Apollo errors
function createApolloError(
  message: string,
  graphQLErrors: ReadonlyArray<GraphQLFormattedError> = [],
  networkError: Error | null = null,
): ApolloLikeError {
  return {
    message,
    graphQLErrors,
    networkError,
    name: 'ApolloError',
  } as ApolloLikeError;
}

describe('Result type utilities', () => {
  describe('ok', () => {
    it('should create a success result', () => {
      const result = ok('test data');
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.data).toBe('test data');
      }
    });

    it('should work with objects', () => {
      const data = { id: 1, name: 'test' };
      const result = ok(data);
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.data).toEqual(data);
      }
    });
  });

  describe('err', () => {
    it('should create an error result', () => {
      const result = err('error message');
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error).toBe('error message');
      }
    });

    it('should work with custom error types', () => {
      const result = err({ code: 'NOT_FOUND', message: 'Item not found' });
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error).toEqual({ code: 'NOT_FOUND', message: 'Item not found' });
      }
    });
  });
});

describe('isApolloLikeError', () => {
  it('should return true for valid Apollo errors', () => {
    const error = createApolloError('Test error');
    expect(isApolloLikeError(error)).toBe(true);
  });

  it('should return false for null', () => {
    expect(isApolloLikeError(null)).toBe(false);
  });

  it('should return false for undefined', () => {
    expect(isApolloLikeError(undefined)).toBe(false);
  });

  it('should return false for plain Error', () => {
    expect(isApolloLikeError(new Error('test'))).toBe(false);
  });

  it('should return false for string', () => {
    expect(isApolloLikeError('error string')).toBe(false);
  });

  it('should return false for object without graphQLErrors array', () => {
    expect(isApolloLikeError({ graphQLErrors: 'not an array' })).toBe(false);
  });
});

describe('getErrorMessage', () => {
  it('should return GraphQL error message', () => {
    const error = createApolloError('Apollo error', [
      {
        message: 'Profile not found',
        locations: [],
        path: ['getProfile'],
        extensions: {},
      },
    ]);
    expect(getErrorMessage(error)).toBe('Profile not found');
  });

  it('should return network error message for network errors', () => {
    const error = createApolloError('Network error occurred', [], new Error('Network failed'));
    expect(getErrorMessage(error)).toBe('Network error. Please check your connection and try again.');
  });

  it('should handle Network request failed message', () => {
    const error = createApolloError('Network request failed');
    expect(getErrorMessage(error)).toBe('Network error. Please check your connection and try again.');
  });

  it('should return error.message for Apollo errors without GraphQL errors', () => {
    const error = createApolloError('Generic Apollo error');
    expect(getErrorMessage(error)).toBe('Generic Apollo error');
  });

  it('should return message from standard Error', () => {
    const error = new Error('Standard error message');
    expect(getErrorMessage(error)).toBe('Standard error message');
  });

  it('should return string error directly', () => {
    expect(getErrorMessage('String error')).toBe('String error');
  });

  it('should return default message for null', () => {
    expect(getErrorMessage(null)).toBe('An error occurred');
  });

  it('should return default message for undefined', () => {
    expect(getErrorMessage(undefined)).toBe('An error occurred');
  });

  it('should use custom default message', () => {
    expect(getErrorMessage(null, 'Custom default')).toBe('Custom default');
  });

  it('should return default for unknown object types', () => {
    expect(getErrorMessage({ foo: 'bar' })).toBe('An error occurred');
  });

  it('should return default for empty GraphQL errors array', () => {
    const error = createApolloError('Fallback message', []);
    expect(getErrorMessage(error)).toBe('Fallback message');
  });
});

describe('getErrorCode', () => {
  it('should extract errorCode from extensions', () => {
    const error = createApolloError('Error', [
      {
        message: 'Not found',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'NOT_FOUND' },
      },
    ]);
    expect(getErrorCode(error)).toBe('NOT_FOUND');
  });

  it('should extract code from extensions as fallback', () => {
    const error = createApolloError('Error', [
      {
        message: 'Unauthorized',
        locations: [],
        path: ['mutation'],
        extensions: { code: 'UNAUTHORIZED' },
      },
    ]);
    expect(getErrorCode(error)).toBe('UNAUTHORIZED');
  });

  it('should return undefined for non-Apollo errors', () => {
    expect(getErrorCode(new Error('test'))).toBeUndefined();
  });

  it('should return undefined for null', () => {
    expect(getErrorCode(null)).toBeUndefined();
  });

  it('should return undefined when no GraphQL errors', () => {
    const error = createApolloError('Error');
    expect(getErrorCode(error)).toBeUndefined();
  });

  it('should return undefined when extensions has no error code', () => {
    const error = createApolloError('Error', [
      {
        message: 'Error',
        locations: [],
        path: ['query'],
        extensions: { otherField: 'value' },
      },
    ]);
    expect(getErrorCode(error)).toBeUndefined();
  });

  it('should handle non-string errorCode', () => {
    const error = createApolloError('Error', [
      {
        message: 'Error',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 123 },
      },
    ]);
    expect(getErrorCode(error)).toBeUndefined();
  });

  it('should handle non-string code', () => {
    const error = createApolloError('Error', [
      {
        message: 'Error',
        locations: [],
        path: ['query'],
        extensions: { code: { nested: true } },
      },
    ]);
    expect(getErrorCode(error)).toBeUndefined();
  });
});

describe('isAuthError', () => {
  it('should return true for UNAUTHORIZED code', () => {
    const error = createApolloError('Unauthorized', [
      {
        message: 'Unauthorized',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'UNAUTHORIZED' },
      },
    ]);
    expect(isAuthError(error)).toBe(true);
  });

  it('should return true for UNAUTHENTICATED code', () => {
    const error = createApolloError('Unauthenticated', [
      {
        message: 'Unauthenticated',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'UNAUTHENTICATED' },
      },
    ]);
    expect(isAuthError(error)).toBe(true);
  });

  it('should return false for other errors', () => {
    const error = createApolloError('Error', [
      {
        message: 'Error',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'NOT_FOUND' },
      },
    ]);
    expect(isAuthError(error)).toBe(false);
  });
});

describe('isForbiddenError', () => {
  it('should return true for FORBIDDEN code', () => {
    const error = createApolloError('Forbidden', [
      {
        message: 'Forbidden',
        locations: [],
        path: ['mutation'],
        extensions: { errorCode: 'FORBIDDEN' },
      },
    ]);
    expect(isForbiddenError(error)).toBe(true);
  });

  it('should return false for other errors', () => {
    const error = createApolloError('Error', [
      {
        message: 'Error',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'UNAUTHORIZED' },
      },
    ]);
    expect(isForbiddenError(error)).toBe(false);
  });
});

describe('isNotFoundError', () => {
  it('should return true for NOT_FOUND code', () => {
    const error = createApolloError('Not found', [
      {
        message: 'Not found',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'NOT_FOUND' },
      },
    ]);
    expect(isNotFoundError(error)).toBe(true);
  });

  it('should return true for PROFILE_NOT_FOUND code', () => {
    const error = createApolloError('Profile not found', [
      {
        message: 'Profile not found',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'PROFILE_NOT_FOUND' },
      },
    ]);
    expect(isNotFoundError(error)).toBe(true);
  });

  it('should return true for CAMPAIGN_NOT_FOUND code', () => {
    const error = createApolloError('Campaign not found', [
      {
        message: 'Campaign not found',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'CAMPAIGN_NOT_FOUND' },
      },
    ]);
    expect(isNotFoundError(error)).toBe(true);
  });

  it('should return true for ORDER_NOT_FOUND code', () => {
    const error = createApolloError('Order not found', [
      {
        message: 'Order not found',
        locations: [],
        path: ['query'],
        extensions: { errorCode: 'ORDER_NOT_FOUND' },
      },
    ]);
    expect(isNotFoundError(error)).toBe(true);
  });

  it('should return false for other errors', () => {
    expect(isNotFoundError(new Error('test'))).toBe(false);
  });
});

describe('isValidationError', () => {
  it('should return true for VALIDATION_ERROR code', () => {
    const error = createApolloError('Validation failed', [
      {
        message: 'Validation failed',
        locations: [],
        path: ['mutation'],
        extensions: { errorCode: 'VALIDATION_ERROR' },
      },
    ]);
    expect(isValidationError(error)).toBe(true);
  });

  it('should return true for INVALID_INPUT code', () => {
    const error = createApolloError('Invalid input', [
      {
        message: 'Invalid input',
        locations: [],
        path: ['mutation'],
        extensions: { errorCode: 'INVALID_INPUT' },
      },
    ]);
    expect(isValidationError(error)).toBe(true);
  });

  it('should return false for other errors', () => {
    expect(isValidationError(new Error('test'))).toBe(false);
  });
});

describe('formatDate', () => {
  it('should format date in short format by default', () => {
    // Use a date with time to avoid timezone issues
    const result = formatDate('2025-01-15T12:00:00Z');
    // Just check it contains a valid formatted date pattern
    expect(result).toMatch(/\w+ \d+, 2025/);
  });

  it('should format date in long format', () => {
    const result = formatDate('2025-01-15T12:00:00Z', 'long');
    // Check for long format pattern
    expect(result).toMatch(/\w+, \w+ \d+, 2025/);
  });

  it('should format date in ISO format', () => {
    const result = formatDate('2025-01-15T10:30:00Z', 'iso');
    expect(result).toBe('2025-01-15');
  });

  it('should return empty string for null', () => {
    expect(formatDate(null)).toBe('');
  });

  it('should return empty string for undefined', () => {
    expect(formatDate(undefined)).toBe('');
  });

  it('should return empty string for empty string', () => {
    expect(formatDate('')).toBe('');
  });

  it('should return empty string for invalid date', () => {
    expect(formatDate('not-a-date')).toBe('');
  });
});

describe('formatCurrency', () => {
  it('should format currency with default USD', () => {
    expect(formatCurrency(99.99)).toBe('$99.99');
  });

  it('should format whole numbers with cents', () => {
    expect(formatCurrency(100)).toBe('$100.00');
  });

  it('should format large numbers with commas', () => {
    expect(formatCurrency(1234567.89)).toBe('$1,234,567.89');
  });

  it('should return $0.00 for null', () => {
    expect(formatCurrency(null)).toBe('$0.00');
  });

  it('should return $0.00 for undefined', () => {
    expect(formatCurrency(undefined)).toBe('$0.00');
  });

  it('should format zero correctly', () => {
    expect(formatCurrency(0)).toBe('$0.00');
  });

  it('should format negative numbers', () => {
    expect(formatCurrency(-50.5)).toBe('-$50.50');
  });
});

describe('formatPhoneNumber', () => {
  it('should format a 10-digit US number', () => {
    expect(formatPhoneNumber('5551234567')).toBe('(555) 123-4567');
  });

  it('should format an 11-digit US number starting with 1', () => {
    expect(formatPhoneNumber('15551234567')).toBe('(555) 123-4567');
  });

  it('should leave unrecognized numbers unchanged', () => {
    expect(formatPhoneNumber('12345')).toBe('12345');
  });

  it('should return em-dash for empty/undefined input', () => {
    expect(formatPhoneNumber('')).toBe('—');
    expect(formatPhoneNumber(undefined)).toBe('—');
  });
});

describe('parseNumber', () => {
  it('should return number directly', () => {
    expect(parseNumber(42)).toBe(42);
  });

  it('should parse string to number', () => {
    expect(parseNumber('123.45')).toBe(123.45);
  });

  it('should return default for null', () => {
    expect(parseNumber(null)).toBe(0);
  });

  it('should return default for undefined', () => {
    expect(parseNumber(undefined)).toBe(0);
  });

  it('should return default for non-numeric string', () => {
    expect(parseNumber('abc')).toBe(0);
  });

  it('should use custom default value', () => {
    expect(parseNumber(null, -1)).toBe(-1);
  });

  it('should return default for NaN', () => {
    expect(parseNumber(NaN)).toBe(0);
  });

  it('should handle object input', () => {
    expect(parseNumber({ value: 10 })).toBe(0);
  });
});

describe('parseInt', () => {
  it('should return integer directly', () => {
    expect(parseInt(42)).toBe(42);
  });

  it('should floor floating point numbers', () => {
    expect(parseInt(42.9)).toBe(42);
  });

  it('should parse string to integer', () => {
    expect(parseInt('123')).toBe(123);
  });

  it('should parse string with decimal to integer', () => {
    expect(parseInt('123.99')).toBe(123);
  });

  it('should return default for null', () => {
    expect(parseInt(null)).toBe(0);
  });

  it('should return default for undefined', () => {
    expect(parseInt(undefined)).toBe(0);
  });

  it('should return default for non-numeric string', () => {
    expect(parseInt('abc')).toBe(0);
  });

  it('should use custom default value', () => {
    expect(parseInt(null, -1)).toBe(-1);
  });

  it('should return default for NaN', () => {
    expect(parseInt(NaN)).toBe(0);
  });
});
