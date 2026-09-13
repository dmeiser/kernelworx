import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Behavioral tests for the SOFTWARE_TOKEN_MFA challenge handling in
 * ``signInUser`` (tests/integration/setup/cognitoAuth.ts). The Cognito SDK
 * client is replaced with a fake so no AWS calls are made; the tests assert
 * the challenge is detected and answered with a valid TOTP code.
 */

const sendMock = vi.fn();

vi.mock('@aws-sdk/client-cognito-identity-provider', () => ({
  AuthFlowType: { USER_PASSWORD_AUTH: 'USER_PASSWORD_AUTH' },
  CognitoIdentityProviderClient: class {
    send = sendMock;
  },
  InitiateAuthCommand: class {
    constructor(public readonly input: unknown) {}
  },
  RespondToAuthChallengeCommand: class {
    constructor(public readonly input: unknown) {}
  },
  ListUserPoolClientsCommand: class {
    constructor(public readonly input: unknown) {}
  },
}));

import { signInUser } from '../integration/setup/cognitoAuth';
import { generateTotp, resetTotpWindowTracking } from '../integration/setup/totp';

const FIXED_NOW_MS = 1_700_000_000_000;
const SECRET_B32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';

function fakeIdToken(email: string): string {
  const payload = Buffer.from(JSON.stringify({ sub: 'sub-1', email })).toString('base64url');
  return `header.${payload}.signature`;
}

function authResult() {
  return {
    AccessToken: 'access-token',
    IdToken: fakeIdToken('owner@kernelworx.test'),
    RefreshToken: 'refresh-token',
  };
}

describe('signInUser SOFTWARE_TOKEN_MFA challenge', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: FIXED_NOW_MS });
    resetTotpWindowTracking();
    sendMock.mockReset();
    process.env.TEST_USER_POOL_ID = 'us-east-1_pool';
    process.env.TEST_USER_POOL_CLIENT_ID = 'client-id';
    process.env.TEST_APPSYNC_ENDPOINT = 'https://api.example.com/graphql';
  });

  afterEach(() => {
    vi.useRealTimers();
    delete process.env.TEST_USER_POOL_ID;
    delete process.env.TEST_USER_POOL_CLIENT_ID;
    delete process.env.TEST_APPSYNC_ENDPOINT;
  });

  it('returns tokens directly when Cognito issues no challenge', async () => {
    sendMock.mockResolvedValueOnce({ AuthenticationResult: authResult() });

    const result = await signInUser('owner@kernelworx.test', 'password');

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(result.tokens.idToken).toBe(fakeIdToken('owner@kernelworx.test'));
    expect(result.accountId).toBe('sub-1');
  });

  it('answers the challenge with a TOTP code derived from the secret', async () => {
    sendMock
      .mockResolvedValueOnce({
        ChallengeName: 'SOFTWARE_TOKEN_MFA',
        ChallengeParameters: { USERNAME: 'owner@kernelworx.test' },
        Session: 'mfa-session',
      })
      .mockResolvedValueOnce({ AuthenticationResult: authResult() });

    const result = await signInUser('owner@kernelworx.test', 'password', SECRET_B32);

    expect(sendMock).toHaveBeenCalledTimes(2);
    const challengeCommand = sendMock.mock.calls[1][0];
    expect(challengeCommand.constructor.name).toBe('RespondToAuthChallengeCommand');
    expect(challengeCommand.input).toEqual({
      ClientId: 'client-id',
      ChallengeName: 'SOFTWARE_TOKEN_MFA',
      Session: 'mfa-session',
      ChallengeResponses: {
        USERNAME: 'owner@kernelworx.test',
        // Same fixed timestamp as the fake clock, so this is deterministic.
        SOFTWARE_TOKEN_MFA_CODE: await generateTotp(SECRET_B32, FIXED_NOW_MS),
      },
    });
    expect(result.tokens.refreshToken).toBe('refresh-token');
  });

  it('fails loudly when a challenge arrives without a TOTP secret', async () => {
    sendMock.mockResolvedValueOnce({
      ChallengeName: 'SOFTWARE_TOKEN_MFA',
      Session: 'mfa-session',
    });

    await expect(signInUser('owner@kernelworx.test', 'password')).rejects.toThrow(
      /TEST_OWNER_TOTP_SECRET/,
    );
    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it('fails loudly when the challenge has no session', async () => {
    sendMock.mockResolvedValueOnce({ ChallengeName: 'SOFTWARE_TOKEN_MFA' });

    await expect(
      signInUser('owner@kernelworx.test', 'password', SECRET_B32),
    ).rejects.toThrow(/without a session/);
  });
});
