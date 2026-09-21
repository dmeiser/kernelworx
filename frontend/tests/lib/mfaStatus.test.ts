/**
 * Tests for the direct Cognito GetUser MFA status read — the authoritative
 * settings-page MFA gate. The pinned aws-amplify fetchMFAPreference cannot
 * surface a WEB_AUTHN_MFA preference, so a passkey-MFA-preferred user must
 * still read back as MFA-enabled from the raw GetUser response.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as amplifyAuth from 'aws-amplify/auth';
import { getMfaEnabledFromCognito } from '../../src/lib/mfaStatus';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
}));

const mockFetch = vi.fn();

const cognitoErrorResponse = (message: string, status = 400): Response =>
  new Response(JSON.stringify({ __type: 'NotAuthorizedException', message }), { status });

const getUserResponse = (body: Record<string, unknown>): Response => new Response(JSON.stringify(body), { status: 200 });

describe('mfaStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', mockFetch);
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_sDiuCOarb');
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: { accessToken: { toString: () => 'test-access-token' } },
    } as any);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('POSTs GetUser with the access token to the pool region endpoint', async () => {
    mockFetch.mockResolvedValue(getUserResponse({ UserMFASettingList: [], PreferredMfaSetting: '' }));

    await getMfaEnabledFromCognito();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://cognito-idp.us-east-1.amazonaws.com/');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({
      'content-type': 'application/x-amz-json-1.1',
      'x-amz-target': 'AWSCognitoIdentityProviderService.GetUser',
    });
    expect(JSON.parse(init.body as string)).toEqual({ AccessToken: 'test-access-token' });
  });

  it('reports MFA enabled for a TOTP-only user', async () => {
    mockFetch.mockResolvedValue(
      getUserResponse({
        UserMFASettingList: ['SOFTWARE_TOKEN_MFA'],
        PreferredMfaSetting: 'SOFTWARE_TOKEN_MFA',
      }),
    );

    await expect(getMfaEnabledFromCognito()).resolves.toBe(true);
  });

  it('reports MFA enabled for a passkey-MFA-preferred user', async () => {
    mockFetch.mockResolvedValue(
      getUserResponse({
        UserMFASettingList: ['WEB_AUTHN_MFA'],
        PreferredMfaSetting: 'WEB_AUTHN_MFA',
      }),
    );

    await expect(getMfaEnabledFromCognito()).resolves.toBe(true);
  });

  it('reports MFA enabled when TOTP and passkey MFA are both enabled', async () => {
    mockFetch.mockResolvedValue(
      getUserResponse({
        UserMFASettingList: ['SOFTWARE_TOKEN_MFA', 'WEB_AUTHN_MFA'],
        PreferredMfaSetting: 'WEB_AUTHN_MFA',
      }),
    );

    await expect(getMfaEnabledFromCognito()).resolves.toBe(true);
  });

  it('reports MFA enabled from a non-empty UserMFASettingList even without a preference', async () => {
    mockFetch.mockResolvedValue(getUserResponse({ UserMFASettingList: ['SOFTWARE_TOKEN_MFA'] }));

    await expect(getMfaEnabledFromCognito()).resolves.toBe(true);
  });

  it('reports MFA enabled from a set PreferredMfaSetting even with an empty list', async () => {
    mockFetch.mockResolvedValue(getUserResponse({ UserMFASettingList: [], PreferredMfaSetting: 'SOFTWARE_TOKEN_MFA' }));

    await expect(getMfaEnabledFromCognito()).resolves.toBe(true);
  });

  it('reports no MFA for a user with no methods and no preference', async () => {
    mockFetch.mockResolvedValue(getUserResponse({}));
    await expect(getMfaEnabledFromCognito()).resolves.toBe(false);

    mockFetch.mockResolvedValue(getUserResponse({ UserMFASettingList: [], PreferredMfaSetting: '' }));
    await expect(getMfaEnabledFromCognito()).resolves.toBe(false);
  });

  it('throws without calling fetch when there is no signed-in access token', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({} as any);
    await expect(getMfaEnabledFromCognito()).rejects.toThrow('No signed-in access token; cannot read MFA status');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('throws the Cognito error message on a non-2xx response', async () => {
    mockFetch.mockResolvedValue(cognitoErrorResponse('Invalid token'));
    await expect(getMfaEnabledFromCognito()).rejects.toThrow('Invalid token');
  });

  it('throws a descriptive error when the user pool id is not configured', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    await expect(getMfaEnabledFromCognito()).rejects.toThrow('Cognito user pool id is not configured');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('derives the endpoint region from the user pool id prefix', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'eu-west-2_ABCDEFG');
    mockFetch.mockResolvedValue(getUserResponse({}));

    await getMfaEnabledFromCognito();
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe('https://cognito-idp.eu-west-2.amazonaws.com/');
  });
});
