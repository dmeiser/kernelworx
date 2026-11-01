import { describe, it, expect } from 'vitest';
import { extractErrorCode, mapErrorCodeToMessage } from '../../src/lib/errorCodes';

describe('lib/errorCodes', () => {
  describe('extractErrorCode', () => {
    it('returns undefined when extensions are absent', () => {
      expect(extractErrorCode(undefined)).toBeUndefined();
    });

    it('prefers errorCode, then code, then errorType', () => {
      expect(extractErrorCode({ errorCode: 'FORBIDDEN', code: 'X', errorType: 'Y' })).toBe(
        'FORBIDDEN',
      );
      expect(extractErrorCode({ code: 'FORBIDDEN', errorType: 'Y' })).toBe('FORBIDDEN');
      expect(extractErrorCode({ errorType: 'FORBIDDEN' })).toBe('FORBIDDEN');
    });

    it('returns undefined when no code field is set', () => {
      expect(extractErrorCode({})).toBeUndefined();
    });
  });

  describe('mapErrorCodeToMessage', () => {
    it('returns the mapped message for known error codes', () => {
      expect(mapErrorCodeToMessage('FORBIDDEN', 'default')).toBe(
        'You do not have permission to perform this action.',
      );
      expect(mapErrorCodeToMessage('NOT_FOUND', 'default')).toBe(
        'The requested resource was not found.',
      );
      expect(mapErrorCodeToMessage('RESOURCE_BUSY', 'default')).toBe(
        'This operation could not be completed right now. Please try again.',
      );
    });

    it('returns the default message when the code is undefined or unknown', () => {
      expect(mapErrorCodeToMessage(undefined, 'default message')).toBe('default message');
      expect(mapErrorCodeToMessage('UNKNOWN_CODE', 'fallback')).toBe('fallback');
    });
  });
});
