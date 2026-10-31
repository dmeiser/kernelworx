import { describe, it, expect, vi } from 'vitest';
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
  parseNumber,
  parseInt as safeParseInt,
  mapPublicSubmissionErrorMessage,
  isBuyerFacingMessage,
  PUBLIC_CHECKOUT_GENERIC_ERROR,
  PUBLIC_CHECKOUT_NETWORK_ERROR,
} from '../../src/lib/api-utils';
import type { ApolloLikeError } from '../../src/lib/api-utils';

describe('lib/api-utils', () => {
  describe('ok / err result helpers', () => {
    it('ok creates a success result', () => {
      expect(ok(42)).toEqual({ ok: true, data: 42 });
    });

    it('err creates an error result', () => {
      expect(err('fail')).toEqual({ ok: false, error: 'fail' });
    });
  });

  describe('getErrorMessage', () => {
    it('returns the default message for falsy values', () => {
      expect(getErrorMessage(null)).toBe('An error occurred');
      expect(getErrorMessage(undefined)).toBe('An error occurred');
      expect(getErrorMessage('')).toBe('An error occurred');
      expect(getErrorMessage(0)).toBe('An error occurred');
    });

    it('uses a custom default message when provided', () => {
      expect(getErrorMessage(null, 'Custom fallback')).toBe('Custom fallback');
    });

    it('extracts message from GraphQL errors', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'ignored',
        graphQLErrors: [{ message: 'GraphQL went boom' }],
      };
      expect(getErrorMessage(error)).toBe('GraphQL went boom');
    });

    it('falls back to default when GraphQL error message is empty', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'ignored',
        graphQLErrors: [{ message: '' }],
      };
      expect(getErrorMessage(error, 'fallback')).toBe('fallback');
    });

    it('reports network errors before GraphQL or message errors', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'Some message',
        graphQLErrors: [],
        networkError: new Error('offline'),
      };
      expect(getErrorMessage(error)).toBe('Network error. Please check your connection and try again.');
    });

    it('filters Apollo network-request-failed messages', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'Network request failed: unable to reach host',
        graphQLErrors: [],
      };
      expect(getErrorMessage(error)).toBe('Network error. Please check your connection and try again.');
    });

    it('returns a plain ApolloLikeError message when present', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'Something else',
        graphQLErrors: [],
      };
      expect(getErrorMessage(error)).toBe('Something else');
    });

    it('falls back to default when ApolloLikeError message is empty', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: '',
        graphQLErrors: [],
      };
      expect(getErrorMessage(error, 'default-msg')).toBe('default-msg');
    });

    it('handles standard Error instances', () => {
      expect(getErrorMessage(new Error('Plain error'))).toBe('Plain error');
    });

    it('falls back to default when standard Error message is empty', () => {
      expect(getErrorMessage(new Error(''), 'fallback')).toBe('fallback');
    });

    it('returns string errors directly', () => {
      expect(getErrorMessage('string error')).toBe('string error');
    });

    it('returns default for unknown non-error values', () => {
      expect(getErrorMessage({ foo: 'bar' })).toBe('An error occurred');
      expect(getErrorMessage(42)).toBe('An error occurred');
    });
  });

  describe('isApolloLikeError', () => {
    it('returns true for objects with a graphQLErrors array', () => {
      expect(isApolloLikeError({ graphQLErrors: [] })).toBe(true);
      expect(isApolloLikeError({ graphQLErrors: [{ message: 'x' }] })).toBe(true);
    });

    it('returns false for null, primitives, and plain objects', () => {
      expect(isApolloLikeError(null)).toBe(false);
      expect(isApolloLikeError(undefined)).toBe(false);
      expect(isApolloLikeError('string')).toBe(false);
      expect(isApolloLikeError(42)).toBe(false);
      expect(isApolloLikeError({})).toBe(false);
      expect(isApolloLikeError({ graphQLErrors: 'not-array' })).toBe(false);
    });
  });

  describe('getErrorCode', () => {
    it('returns undefined for non-Apollo errors', () => {
      expect(getErrorCode(new Error('oops'))).toBeUndefined();
      expect(getErrorCode(null)).toBeUndefined();
    });

    it('returns undefined when there are no GraphQL errors', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'x',
        graphQLErrors: [],
      };
      expect(getErrorCode(error)).toBeUndefined();
    });

    it('prefers extensions.errorCode', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'x',
        graphQLErrors: [{ message: 'x', extensions: { errorCode: 'CUSTOM_CODE', code: 'OTHER' } }],
      };
      expect(getErrorCode(error)).toBe('CUSTOM_CODE');
    });

    it('falls back to extensions.code', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'x',
        graphQLErrors: [{ message: 'x', extensions: { code: 'FORBIDDEN' } }],
      };
      expect(getErrorCode(error)).toBe('FORBIDDEN');
    });

    it('returns undefined when no recognized code is present', () => {
      const error: ApolloLikeError = {
        name: 'ApolloError',
        message: 'x',
        graphQLErrors: [{ message: 'x', extensions: {} }],
      };
      expect(getErrorCode(error)).toBeUndefined();
    });
  });

  describe('error classification helpers', () => {
    const makeError = (code: string) =>
      ({
        name: 'ApolloError',
        message: 'x',
        graphQLErrors: [{ message: 'x', extensions: { code } }],
      }) as ApolloLikeError;

    it('isAuthError identifies UNAUTHORIZED and UNAUTHENTICATED', () => {
      expect(isAuthError(makeError('UNAUTHORIZED'))).toBe(true);
      expect(isAuthError(makeError('UNAUTHENTICATED'))).toBe(true);
      expect(isAuthError(makeError('FORBIDDEN'))).toBe(false);
    });

    it('isForbiddenError identifies FORBIDDEN', () => {
      expect(isForbiddenError(makeError('FORBIDDEN'))).toBe(true);
      expect(isForbiddenError(makeError('UNAUTHORIZED'))).toBe(false);
    });

    it('isNotFoundError identifies not-found codes', () => {
      expect(isNotFoundError(makeError('NOT_FOUND'))).toBe(true);
      expect(isNotFoundError(makeError('PROFILE_NOT_FOUND'))).toBe(true);
      expect(isNotFoundError(makeError('CAMPAIGN_NOT_FOUND'))).toBe(true);
      expect(isNotFoundError(makeError('ORDER_NOT_FOUND'))).toBe(true);
      expect(isNotFoundError(makeError('OTHER'))).toBe(false);
    });

    it('isValidationError identifies validation codes', () => {
      expect(isValidationError(makeError('VALIDATION_ERROR'))).toBe(true);
      expect(isValidationError(makeError('INVALID_INPUT'))).toBe(true);
      expect(isValidationError(makeError('OTHER'))).toBe(false);
    });
  });

  describe('formatDate', () => {
    const date = '2024-03-15T12:00:00.000Z';

    it('returns empty string for null or undefined', () => {
      expect(formatDate(null)).toBe('');
      expect(formatDate(undefined)).toBe('');
    });

    it('returns empty string for invalid date strings', () => {
      expect(formatDate('not-a-date')).toBe('');
    });

    it('formats ISO dates as YYYY-MM-DD', () => {
      expect(formatDate(date, 'iso')).toBe('2024-03-15');
    });

    it('formats dates in long form', () => {
      expect(formatDate(date, 'long')).toBe('Friday, March 15, 2024');
    });

    it('formats dates in short form by default', () => {
      expect(formatDate(date, 'short')).toBe('Mar 15, 2024');
      expect(formatDate(date)).toBe('Mar 15, 2024');
    });

    it('falls back to short format for unknown format values', () => {
      expect(formatDate(date, 'invalid' as unknown as 'short')).toBe('Mar 15, 2024');
    });

    it('returns empty string when Date constructor throws', () => {
      vi.spyOn(globalThis, 'Date').mockImplementationOnce(function () {
        throw new Error('boom');
      } as unknown as DateConstructor);
      expect(formatDate(date)).toBe('');
    });
  });

  describe('formatCurrency', () => {
    it('formats USD by default', () => {
      expect(formatCurrency(1234.5)).toBe('$1,234.50');
    });

    it('formats custom currencies', () => {
      expect(formatCurrency(99.99, 'EUR')).toBe('€99.99');
    });

    it('returns $0.00 for null or undefined', () => {
      expect(formatCurrency(null)).toBe('$0.00');
      expect(formatCurrency(undefined)).toBe('$0.00');
    });
  });

  describe('parseNumber', () => {
    it('returns valid numbers unchanged', () => {
      expect(parseNumber(42)).toBe(42);
      expect(parseNumber(3.14)).toBe(3.14);
    });

    it('parses numeric strings', () => {
      expect(parseNumber('2.5')).toBe(2.5);
    });

    it('returns default for NaN numbers', () => {
      expect(parseNumber(NaN)).toBe(0);
    });

    it('returns default for non-numeric strings', () => {
      expect(parseNumber('abc', -1)).toBe(-1);
    });

    it('returns default for unsupported types', () => {
      expect(parseNumber(null, -2)).toBe(-2);
      expect(parseNumber({}, -3)).toBe(-3);
    });
  });

  describe('safeParseInt', () => {
    it('floors valid numbers', () => {
      expect(safeParseInt(4.9)).toBe(4);
      expect(safeParseInt(-1.2)).toBe(-2);
    });

    it('parses integer strings', () => {
      expect(safeParseInt('42')).toBe(42);
    });

    it('returns default for NaN numbers', () => {
      expect(safeParseInt(NaN)).toBe(0);
    });

    it('returns default for non-numeric strings', () => {
      expect(safeParseInt('xyz', -1)).toBe(-1);
    });

    it('returns default for unsupported types', () => {
      expect(safeParseInt(undefined, -2)).toBe(-2);
    });
  });

  // The public checkout pages are anonymous: whoever reads this text may be an
  // attacker probing the link, and the two failure modes have to be closed at
  // once — an unmapped code echoing a raw DynamoDB fault, and a specific
  // INVALID_INPUT sentence flattened to a generic one.
  describe('mapPublicSubmissionErrorMessage', () => {
    const gql = (message: string, code?: string): ApolloLikeError =>
      ({
        graphQLErrors: [code === undefined ? { message } : { message, extensions: { code } }],
        networkError: undefined,
      }) as unknown as ApolloLikeError;

    it('preserves the backend INVALID_INPUT wording', () => {
      expect(mapPublicSubmissionErrorMessage(gql('ZIP code must be 5 or 9 digits', 'INVALID_INPUT'))).toBe(
        'ZIP code must be 5 or 9 digits',
      );
    });

    it('preserves INVALID_INPUT carried in extensions.errorCode', () => {
      const error = {
        graphQLErrors: [{ message: 'Payment method is required', extensions: { errorCode: 'INVALID_INPUT' } }],
      } as unknown as ApolloLikeError;
      expect(mapPublicSubmissionErrorMessage(error)).toBe('Payment method is required');
    });

    it('replaces an INVALID_INPUT message that betrays the stack', () => {
      const leaky = gql(
        'ConditionalCheckFailedException operation error DynamoDB: PutItem https://service.us-east-1.amazonaws.com/',
        'INVALID_INPUT',
      );
      const shown = mapPublicSubmissionErrorMessage(leaky);
      expect(shown).toBe(PUBLIC_CHECKOUT_GENERIC_ERROR);
      expect(shown).not.toMatch(/dynamodb|amazonaws|conditionalcheck/i);
    });

    it('maps an unrecognized code to the generic sentence rather than the raw message', () => {
      const raw = 'Request has expired';
      expect(mapPublicSubmissionErrorMessage(gql(raw, 'SomeBrandNewCode'))).toBe(PUBLIC_CHECKOUT_GENERIC_ERROR);
    });

    it('maps a codeless GraphQL error to the generic sentence', () => {
      expect(mapPublicSubmissionErrorMessage(gql('Validation error: "totalAmount" must be a number'))).toBe(
        PUBLIC_CHECKOUT_GENERIC_ERROR,
      );
    });

    it('names a dead link for every not-found spelling', () => {
      for (const code of ['NOT_FOUND', 'CAMPAIGN_NOT_FOUND', 'ORDER_NOT_FOUND', 'FORBIDDEN', 'UNAUTHENTICATED']) {
        expect(mapPublicSubmissionErrorMessage(gql('nope', code))).toBe('This order link is no longer available.');
      }
    });

    it('names the campaign cap separately from a dead link', () => {
      expect(mapPublicSubmissionErrorMessage(gql('full', 'PUBLIC_ORDER_LIMIT_EXCEEDED'))).toBe(
        'This campaign has reached its public order limit.',
      );
    });

    it('keeps a retryable failure worded as retryable', () => {
      expect(mapPublicSubmissionErrorMessage(gql('busy', 'RESOURCE_BUSY'))).toBe(
        'The order could not be placed right now. Please try again.',
      );
      expect(mapPublicSubmissionErrorMessage(gql('busy', 'ConflictException'))).toBe(
        'The order could not be placed right now. Please try again.',
      );
    });

    it('blames the connection when no server answer came back', () => {
      const network = {
        graphQLErrors: [],
        networkError: new Error('Failed to fetch'),
      } as unknown as ApolloLikeError;
      expect(mapPublicSubmissionErrorMessage(network)).toBe(PUBLIC_CHECKOUT_NETWORK_ERROR);
    });

    it('treats a bare fetch failure as a transport problem', () => {
      expect(mapPublicSubmissionErrorMessage(new Error('fetch failed'))).not.toBe('fetch failed');
      expect(mapPublicSubmissionErrorMessage(new Error('Network request failed'))).toBe(
        PUBLIC_CHECKOUT_NETWORK_ERROR,
      );
    });

    it('never returns an empty string', () => {
      expect(mapPublicSubmissionErrorMessage(undefined)).toBe(PUBLIC_CHECKOUT_GENERIC_ERROR);
      expect(mapPublicSubmissionErrorMessage(gql(''))).toBe(PUBLIC_CHECKOUT_GENERIC_ERROR);
    });
  });

  describe('isBuyerFacingMessage', () => {
    it('accepts ordinary sentences the resolvers write', () => {
      expect(isBuyerFacingMessage('Address is missing required fields: city')).toBe(true);
    });

    it('rejects infrastructure wording', () => {
      for (const leaky of [
        'ResourceInUseException: table is being created',
        'ThrottlingException: rate exceeded',
        'AccessDeniedException: not authorized to perform',
        'An error occurred (InternalServerError) when calling the SendEmail operation',
        'cannot deserialize the request body',
        'Traceback (most recent call last):',
      ]) {
        expect(isBuyerFacingMessage(leaky)).toBe(false);
      }
    });

    it('rejects an empty or absurdly long message', () => {
      expect(isBuyerFacingMessage('   ')).toBe(false);
      expect(isBuyerFacingMessage('x'.repeat(501))).toBe(false);
    });
  });

  describe('formatCurrency', () => {
    it('formats the default currency to two decimals', () => {
      expect(formatCurrency(1234.5)).toBe('$1,234.50');
    });

    it('renders a missing amount as zero', () => {
      expect(formatCurrency(null)).toBe('$0.00');
      expect(formatCurrency(undefined)).toBe('$0.00');
    });

    it('returns the same formatter result for repeated calls in one currency', () => {
      // The formatter is built once per currency and reused across list rows.
      expect(formatCurrency(10, 'EUR')).toBe(formatCurrency(10, 'EUR'));
    });
  });


describe('coverage gaps', () => {
  it('returns undefined when an apollo-like error has no graphql errors', () => {
    const error = { errors: [] } as unknown as ApolloLikeError;
    expect(getErrorCode(error)).toBeUndefined();
  });
});

});
