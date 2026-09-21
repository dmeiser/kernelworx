/**
 * Tests for the passkey MFA enablement helper (SetUserMFAPreference with
 * WebAuthnMfaSettings.Enabled — the per-user "User verification with
 * passkey" method the Cognito console toggle sets). Cognito rejects a
 * WebAuthn-only request ("WebAuthn MFA requires enabling an additional
 * MFA setting."), so the helper re-sends the user's currently enabled
 * MFA methods in the same request, and the failure path surfaces the
 * service message instead of hiding it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as amplifyAuth from 'aws-amplify/auth';
import {
  enablePasskeyMfa,
  passkeyMfaFailureMessage,
  extractCognitoErrorMessage,
  PASSKEY_MFA_ENABLE_FAILED_MESSAGE,
} from '../../src/lib/passkeyMfa';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  fetchMFAPreference: vi.fn(),
}));

const mockFetch = vi.fn();

const cognitoErrorResponse = (message: string, status = 400): Response =>
  new Response(JSON.stringify({ __type: 'InvalidParameterException', message }), {
    status,
  });

describe('passkeyMfa', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', mockFetch);
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_sDiuCOarb');
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: { accessToken: { toString: () => 'test-access-token' } },
    } as any);
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ enabled: [] });
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
    // No other MFA method enabled: the WebAuthn flag is sent alone.
    expect(JSON.parse(init.body as string)).toEqual({
      AccessToken: 'test-access-token',
      WebAuthnMfaSettings: { Enabled: true },
    });
  });

  it('re-sends an enabled TOTP preference in the same request as WebAuthnMfaSettings', async () => {
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ enabled: ['TOTP'] });
    await enablePasskeyMfa();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    // Exact shape: TOTP is re-sent Enabled=true alongside the WebAuthn
    // flag (the combined-request rule Cognito enforces) and never
    // disabled — no `Enabled: false` appears anywhere in the body.
    expect(JSON.parse(init.body as string)).toEqual({
      AccessToken: 'test-access-token',
      SoftwareTokenMfaSettings: { Enabled: true },
      WebAuthnMfaSettings: { Enabled: true },
    });
  });

  it('re-sends an enabled email preference in the same request as WebAuthnMfaSettings', async () => {
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ enabled: ['EMAIL'] });
    await enablePasskeyMfa();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      AccessToken: 'test-access-token',
      EmailMfaSettings: { Enabled: true },
      WebAuthnMfaSettings: { Enabled: true },
    });
  });

  it('re-sends every enabled method when TOTP, email, and SMS are all enabled', async () => {
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({
      enabled: ['TOTP', 'EMAIL', 'SMS'],
    });
    await enablePasskeyMfa();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      AccessToken: 'test-access-token',
      SoftwareTokenMfaSettings: { Enabled: true },
      EmailMfaSettings: { Enabled: true },
      SmsMfaSettings: { Enabled: true },
      WebAuthnMfaSettings: { Enabled: true },
    });
  });

  it('surfaces the Cognito service message verbatim when no other MFA method is enabled', async () => {
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ enabled: [] });
    mockFetch.mockResolvedValue(cognitoErrorResponse('WebAuthn MFA requires enabling an additional MFA setting.'));

    const caught = await enablePasskeyMfa().catch((err: unknown) => err);

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe('WebAuthn MFA requires enabling an additional MFA setting.');
    // The user-visible failure keeps the static guidance AND the
    // service's actual rule.
    expect(passkeyMfaFailureMessage(caught)).toBe(
      `${PASSKEY_MFA_ENABLE_FAILED_MESSAGE} WebAuthn MFA requires enabling an additional MFA setting.`,
    );
  });

  it('throws the Cognito error message on a non-2xx response', async () => {
    mockFetch.mockResolvedValue(cognitoErrorResponse('WebAuthn MFA not enabled on pool'));
    await expect(enablePasskeyMfa()).rejects.toThrow('WebAuthn MFA not enabled on pool');
  });

  it('falls back to the HTTP status when the error body is not JSON', async () => {
    mockFetch.mockResolvedValue(new Response('plain text', { status: 500 }));
    await expect(enablePasskeyMfa()).rejects.toThrow('Cognito error (HTTP 500)');
  });

  it('derives the endpoint region from the user pool id prefix', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'eu-west-2_ABCDEFG');
    await enablePasskeyMfa();
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe('https://cognito-idp.eu-west-2.amazonaws.com/');
  });

  it('throws without calling fetch when there is no signed-in access token', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({} as any);
    await expect(enablePasskeyMfa()).rejects.toThrow('No signed-in access token; cannot enable passkey MFA');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('throws a descriptive error when the user pool id is not configured', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    await expect(enablePasskeyMfa()).rejects.toThrow('Cognito user pool id is not configured');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('truncates an over-long Cognito service message in the failure message', () => {
    const long = 'x'.repeat(500);
    const message = passkeyMfaFailureMessage(new Error(long));
    expect(message).toContain(PASSKEY_MFA_ENABLE_FAILED_MESSAGE);
    expect(message).not.toContain(long);
    expect(message.endsWith('…')).toBe(true);
    expect(message.length).toBeLessThanOrEqual(PASSKEY_MFA_ENABLE_FAILED_MESSAGE.length + 201);
  });

  it('falls back to the static message when the error carries no detail', () => {
    expect(passkeyMfaFailureMessage(null)).toBe(PASSKEY_MFA_ENABLE_FAILED_MESSAGE);
    expect(passkeyMfaFailureMessage(new Error(''))).toBe(PASSKEY_MFA_ENABLE_FAILED_MESSAGE);
  });

  it('surfaces object errors without a message field as the static message', () => {
    expect(passkeyMfaFailureMessage({ code: 'SomeException' })).toBe(PASSKEY_MFA_ENABLE_FAILED_MESSAGE);
  });

  it('surfaces a plain string error verbatim in the failure message', () => {
    expect(passkeyMfaFailureMessage('WebAuthn MFA requires enabling an additional MFA setting.')).toBe(
      `${PASSKEY_MFA_ENABLE_FAILED_MESSAGE} WebAuthn MFA requires enabling an additional MFA setting.`,
    );
  });

  it('omits the MFA methods block when fetchMFAPreference reports no enabled list', async () => {
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({} as never);

    await enablePasskeyMfa();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ AccessToken: 'test-access-token', WebAuthnMfaSettings: { Enabled: true } });
  });

  it('falls back to the HTTP status when the error body is JSON without a message', async () => {
    const message = await extractCognitoErrorMessage(new Response(JSON.stringify({ __type: 'InternalError' }), { status: 502 }));
    expect(message).toBe('Cognito error (HTTP 502)');
  });

  it('throws a descriptive error when the pool id has no region separator', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'not-a-regional-pool-id');

    await expect(enablePasskeyMfa()).rejects.toThrow('Cognito user pool id is not configured');
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
