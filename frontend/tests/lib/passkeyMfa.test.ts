/**
 * Tests for the passkey MFA enablement helper (SetUserMFAPreference with
 * WebAuthnMfaSettings.Enabled — the per-user "User verification with
 * passkey" method the Cognito console toggle sets).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as amplifyAuth from 'aws-amplify/auth';
import {
  enablePasskeyMfa,
  PASSKEY_MFA_ENABLE_FAILED_MESSAGE,
} from '../../src/lib/passkeyMfa';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
}));

const mockFetch = vi.fn();

describe('passkeyMfa', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', mockFetch);
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_sDiuCOarb');
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: { accessToken: { toString: () => 'test-access-token' } },
    } as any);
    mockFetch.mockResolvedValue(new Response(null, { status: 200 }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('exports a user-facing enablement failure message', () => {
    expect(PASSKEY_MFA_ENABLE_FAILED_MESSAGE).toContain('passkey sign-in could not be enabled');
  });

  it('POSTs SetUserMFAPreference with WebAuthnMfaSettings.Enabled to the pool region endpoint', async () => {
    await enablePasskeyMfa();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://cognito-idp.us-east-1.amazonaws.com/');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({
      'content-type': 'application/x-amz-json-1.1',
      'x-amz-target': 'AWSCognitoIdentityProviderService.SetUserMFAPreference',
    });
    expect(JSON.parse(init.body as string)).toEqual({
      AccessToken: 'test-access-token',
      WebAuthnMfaSettings: { Enabled: true },
    });
  });

  it('derives the endpoint region from the user pool id prefix', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'eu-west-2_ABCDEFG');
    await enablePasskeyMfa();
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe('https://cognito-idp.eu-west-2.amazonaws.com/');
  });

  it('throws without calling fetch when there is no signed-in access token', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({} as any);
    await expect(enablePasskeyMfa()).rejects.toThrow(
      'No signed-in access token; cannot enable passkey MFA',
    );
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('throws a descriptive error when the user pool id is not configured', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    await expect(enablePasskeyMfa()).rejects.toThrow(
      'Cognito user pool id is not configured',
    );
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('throws the Cognito error message on a non-2xx response', async () => {
    mockFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ __type: 'InvalidParameterException', message: 'WebAuthn MFA not enabled on pool' }),
        { status: 400 },
      ),
    );
    await expect(enablePasskeyMfa()).rejects.toThrow('WebAuthn MFA not enabled on pool');
  });

  it('falls back to the HTTP status when the error body is not JSON', async () => {
    mockFetch.mockResolvedValue(new Response('plain text', { status: 500 }));
    await expect(enablePasskeyMfa()).rejects.toThrow('Cognito error (HTTP 500)');
  });
});
