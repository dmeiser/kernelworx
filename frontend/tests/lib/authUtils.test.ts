import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  isFederatedIdentitiesClaim,
  isFederatedTokenPayload,
  isFederatedSession,
  checkIsFederatedSession,
} from '../../src/lib/authUtils';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
}));

describe('authUtils - federated identity detection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('isFederatedIdentitiesClaim', () => {
    it('returns true for parsed array with providerName', () => {
      const claim = [{ userId: '12345', providerName: 'Google', providerType: 'Google' }];
      expect(isFederatedIdentitiesClaim(claim)).toBe(true);
    });

    it('returns true for stringified JSON array with providerName', () => {
      const claim = JSON.stringify([{ userId: '12345', providerName: 'Google' }]);
      expect(isFederatedIdentitiesClaim(claim)).toBe(true);
    });

    it('returns true for multiple providers if at least one valid providerName exists', () => {
      const claim = [
        { providerName: 'Google' },
        { providerName: 'Facebook' },
      ];
      expect(isFederatedIdentitiesClaim(claim)).toBe(true);
    });

    it('returns false for absent or undefined claim', () => {
      expect(isFederatedIdentitiesClaim(undefined)).toBe(false);
      expect(isFederatedIdentitiesClaim(null)).toBe(false);
      expect(isFederatedIdentitiesClaim('')).toBe(false);
    });

    it('returns false for empty array or stringified empty array', () => {
      expect(isFederatedIdentitiesClaim([])).toBe(false);
      expect(isFederatedIdentitiesClaim('[]')).toBe(false);
    });

    it('returns false for malformed JSON string', () => {
      expect(isFederatedIdentitiesClaim('not-valid-json')).toBe(false);
      expect(isFederatedIdentitiesClaim('{ "providerName": "Google" }')).toBe(false);
    });

    it('returns false for array items missing or invalid providerName', () => {
      expect(isFederatedIdentitiesClaim([{ userId: '12345' }])).toBe(false);
      expect(isFederatedIdentitiesClaim([{ providerName: '' }])).toBe(false);
      expect(isFederatedIdentitiesClaim([{ providerName: '   ' }])).toBe(false);
      expect(isFederatedIdentitiesClaim([{ providerName: 123 }])).toBe(false);
      expect(isFederatedIdentitiesClaim([null, undefined, 42, 'str'])).toBe(false);
    });

    it('returns false for non-array parsed types', () => {
      expect(isFederatedIdentitiesClaim(12345)).toBe(false);
      expect(isFederatedIdentitiesClaim(true)).toBe(false);
      expect(isFederatedIdentitiesClaim({ providerName: 'Google' })).toBe(false);
    });
  });

  describe('isFederatedTokenPayload', () => {
    it('returns true for payload with valid federated identities claim', () => {
      const payload = {
        sub: 'user-sub-123',
        email: 'user@example.com',
        identities: [{ providerName: 'Google' }],
      };
      expect(isFederatedTokenPayload(payload)).toBe(true);
    });

    it('returns true for payload with stringified identities claim', () => {
      const payload = {
        sub: 'user-sub-123',
        identities: JSON.stringify([{ providerName: 'Google' }]),
      };
      expect(isFederatedTokenPayload(payload)).toBe(true);
    });

    it('returns false for native user payload without identities claim', () => {
      const payload = {
        sub: 'user-sub-123',
        email: 'native@example.com',
        'cognito:groups': ['ADMIN'],
      };
      expect(isFederatedTokenPayload(payload)).toBe(false);
    });

    it('returns false for invalid or null payload', () => {
      expect(isFederatedTokenPayload(null)).toBe(false);
      expect(isFederatedTokenPayload(undefined)).toBe(false);
      expect(isFederatedTokenPayload('string')).toBe(false);
      expect(isFederatedTokenPayload({ identities: [] })).toBe(false);
    });
  });

  describe('isFederatedSession', () => {
    it('returns true for session with federated idToken payload', () => {
      const session = {
        tokens: {
          idToken: {
            payload: {
              identities: [{ providerName: 'Google' }],
            },
          },
        },
      };
      expect(isFederatedSession(session)).toBe(true);
    });

    it('returns false for native user session', () => {
      const session = {
        tokens: {
          idToken: {
            payload: {
              email: 'native@example.com',
            },
          },
        },
      };
      expect(isFederatedSession(session)).toBe(false);
    });

    it('returns false for empty or invalid session', () => {
      expect(isFederatedSession(null)).toBe(false);
      expect(isFederatedSession(undefined)).toBe(false);
      expect(isFederatedSession({})).toBe(false);
      expect(isFederatedSession({ tokens: {} })).toBe(false);
    });
  });

  describe('checkIsFederatedSession', () => {
    it('resolves true when fetchAuthSession returns federated session', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
        tokens: {
          idToken: {
            payload: {
              identities: [{ providerName: 'Google' }],
            },
          },
        },
      } as any);

      const result = await checkIsFederatedSession();
      expect(result).toBe(true);
    });

    it('resolves false when fetchAuthSession returns native session', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
        tokens: {
          idToken: {
            payload: {
              email: 'native@example.com',
            },
          },
        },
      } as any);

      const result = await checkIsFederatedSession();
      expect(result).toBe(false);
    });

    it('resolves false when fetchAuthSession throws', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockRejectedValue(new Error('Auth error'));

      const result = await checkIsFederatedSession();
      expect(result).toBe(false);
    });
  });
});
