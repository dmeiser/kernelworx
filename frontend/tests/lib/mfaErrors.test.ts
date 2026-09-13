import { describe, it, expect } from 'vitest';
import { isMfaRequiredError, MFA_REQUIRED_MESSAGE } from '../../src/lib/mfaErrors';

describe('mfaErrors', () => {
  it('exports MFA_REQUIRED_MESSAGE as "MFA required"', () => {
    expect(MFA_REQUIRED_MESSAGE).toBe('MFA required');
  });

  describe('isMfaRequiredError', () => {
    it('returns false for null, undefined, and non-errors', () => {
      expect(isMfaRequiredError(null)).toBe(false);
      expect(isMfaRequiredError(undefined)).toBe(false);
      expect(isMfaRequiredError(123)).toBe(false);
      expect(isMfaRequiredError({})).toBe(false);
    });

    it('matches exact string "MFA required"', () => {
      expect(isMfaRequiredError('MFA required')).toBe(true);
      expect(isMfaRequiredError('  MFA required  ')).toBe(true);
    });

    it('does not match non-exact strings', () => {
      expect(isMfaRequiredError('MFA setup failed')).toBe(false);
      expect(isMfaRequiredError('Error: MFA required for user')).toBe(false);
      expect(isMfaRequiredError('FORBIDDEN')).toBe(false);
    });

    it('matches Error instance with message "MFA required"', () => {
      expect(isMfaRequiredError(new Error('MFA required'))).toBe(true);
      expect(isMfaRequiredError(new Error('Other error'))).toBe(false);
    });

    it('matches ApolloError / GraphQL errors array', () => {
      const apolloErr = {
        graphQLErrors: [{ message: 'MFA required' }],
      };
      expect(isMfaRequiredError(apolloErr)).toBe(true);

      const apolloErrOther = {
        graphQLErrors: [{ message: 'Different message' }],
      };
      expect(isMfaRequiredError(apolloErrOther)).toBe(false);
    });

    it('matches errors array in object', () => {
      const err = {
        errors: [{ message: 'MFA required' }],
      };
      expect(isMfaRequiredError(err)).toBe(true);
    });

    it('matches networkError with message', () => {
      const netErr = {
        networkError: {
          message: 'MFA required',
        },
      };
      expect(isMfaRequiredError(netErr)).toBe(true);
    });

    it('matches networkError with result.message', () => {
      const netErr = {
        networkError: {
          result: {
            message: 'MFA required',
          },
        },
      };
      expect(isMfaRequiredError(netErr)).toBe(true);
    });

    it('matches networkError with result.errors array', () => {
      const netErr = {
        networkError: {
          result: {
            errors: [{ message: 'MFA required' }],
          },
        },
      };
      expect(isMfaRequiredError(netErr)).toBe(true);
    });

    it('matches CustomEvent detail.message', () => {
      const customErr = {
        detail: {
          message: 'MFA required',
        },
      };
      expect(isMfaRequiredError(customErr)).toBe(true);
    });
  });
});
