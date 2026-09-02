/**
 * Tests for the same-origin edge architecture (#165/#166).
 *
 * Behavioral coverage of the frontend side of the single-distribution design:
 * - Apollo must call `/graphql` same-origin when VITE_APPSYNC_ENDPOINT is unset
 *   (dev/prod), and the absolute endpoint when it is set (ephemeral / vite dev).
 * - Amplify's OAuth domain must fall back to the site host when
 *   VITE_COGNITO_DOMAIN is unset, and honor it when set.
 * - AuthContext's manual logout fallback must build the logout URL against the
 *   same-origin auth proxy (site host) rather than a dedicated login domain.
 *
 * Each case exercises the real module through its public interface; env vars
 * are switched per case and modules are re-imported so the import-time
 * configuration is rebuilt under each environment.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { gql } from '@apollo/client';

const SITE_URL = 'https://dev.kernelworx.app/';
const LOGIN_DOMAIN = 'login.dev.kernelworx.app';
const DIRECT_APPSYNC = 'https://abc123.appsync-api.us-east-1.amazonaws.com/graphql';

// Capture Amplify.configure calls so we can assert the resolved OAuth domain.
const configureMock = vi.fn();
vi.mock('aws-amplify', async (importOriginal) => {
  const actual = await importOriginal<typeof import('aws-amplify')>();
  return { ...actual, Amplify: { ...actual.Amplify, configure: configureMock } };
});

// The auth link must obtain a token before any request is sent, and the
// logout flow must be drivable from tests.
vi.mock('aws-amplify/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('aws-amplify/auth')>();
  return {
    ...actual,
    fetchAuthSession: vi.fn().mockResolvedValue({
      tokens: { idToken: { toString: () => 'mock-id-token' } },
    }),
    signOut: vi.fn(),
    getCurrentUser: vi.fn(),
    signInWithRedirect: vi.fn(),
    signIn: vi.fn(),
  };
});

const QUERY = gql`
  query GetMyAccount {
    getMyAccount {
      accountId
    }
  }
`;

function mockFetchWithGraphQLResponse() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        data: { getMyAccount: { __typename: 'Account', accountId: 'a1' } },
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.resetModules();
  configureMock.mockClear();
  // Same-origin baseline: no absolute endpoints configured (dev/prod mode).
  delete (import.meta.env as Record<string, unknown>).VITE_APPSYNC_ENDPOINT;
  delete (import.meta.env as Record<string, unknown>).VITE_COGNITO_DOMAIN;
  vi.stubEnv('VITE_APPSYNC_ENDPOINT', undefined as unknown as string);
  vi.stubEnv('VITE_COGNITO_DOMAIN', undefined as unknown as string);
  vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', SITE_URL);
  vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNOUT', SITE_URL);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('Apollo endpoint resolution (#165 same-origin)', () => {
  it('sends GraphQL requests to /graphql when VITE_APPSYNC_ENDPOINT is unset (dev/prod)', async () => {
    const fetchMock = mockFetchWithGraphQLResponse();
    const { apolloClient } = await import('../src/lib/apollo');

    const result = await apolloClient.query({ query: QUERY });

    if (fetchMock.mock.calls.length !== 1) {
      throw new Error(
        `expected 1 fetch call, got ${fetchMock.mock.calls.length}; query error: ${JSON.stringify(result.error)}`,
      );
    }
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/graphql');
    expect(url).not.toContain('amazonaws.com');
    // Auth must still flow through the CloudFront /graphql behavior.
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer mock-id-token');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('sends GraphQL requests to the absolute endpoint when set (ephemeral / vite dev)', async () => {
    vi.stubEnv('VITE_APPSYNC_ENDPOINT', DIRECT_APPSYNC);
    (import.meta.env as Record<string, unknown>).VITE_APPSYNC_ENDPOINT = DIRECT_APPSYNC;
    const fetchMock = mockFetchWithGraphQLResponse();
    const { apolloClient } = await import('../src/lib/apollo');

    const result = await apolloClient.query({ query: QUERY });

    if (fetchMock.mock.calls.length !== 1) {
      throw new Error(
        `expected 1 fetch call, got ${fetchMock.mock.calls.length}; query error: ${JSON.stringify(result.error)}`,
      );
    }
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(DIRECT_APPSYNC);
  });
});

describe('Cognito OAuth domain resolution (#166 same-origin auth proxy)', () => {
  it('falls back to the site host when VITE_COGNITO_DOMAIN is unset (dev/prod)', async () => {
    await import('../src/lib/amplify');

    expect(configureMock).toHaveBeenCalledTimes(1);
    const config = configureMock.mock.calls[0][0] as {
      Auth: { Cognito: { loginWith: { oauth: { domain: string } } } };
    };
    expect(config.Auth.Cognito.loginWith.oauth.domain).toBe('dev.kernelworx.app');
  });

  it('honors VITE_COGNITO_DOMAIN when set (ephemeral / vite dev)', async () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', LOGIN_DOMAIN);
    (import.meta.env as Record<string, unknown>).VITE_COGNITO_DOMAIN = LOGIN_DOMAIN;
    await import('../src/lib/amplify');

    const config = configureMock.mock.calls[0][0] as {
      Auth: { Cognito: { loginWith: { oauth: { domain: string } } } };
    };
    expect(config.Auth.Cognito.loginWith.oauth.domain).toBe(LOGIN_DOMAIN);
  });
});

describe('Manual logout fallback URL (AuthContext)', () => {
  it('routes the fallback logout through the same-origin auth proxy paths', async () => {
    const setHref = vi.fn();
    const originalLocation = window.location;
    // Replace location with a stub so we can observe the navigation target
    // (jsdom does not implement cross-document navigation).
    const locationStub = { hostname: 'dev.kernelworx.app', host: 'dev.kernelworx.app' };
    Object.defineProperty(locationStub, 'href', {
      configurable: true,
      set: setHref,
      get: () => '',
    });
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: locationStub,
    });

    try {
      const auth = await import('aws-amplify/auth');
      vi.mocked(auth.signOut).mockRejectedValue(new Error('network down'));

      const { AuthProvider, useAuth } = await import('../src/contexts/AuthContext');
      const { renderHook, act } = await import('@testing-library/react');
      const wrapper = ({ children }: { children: React.ReactNode }) => <AuthProvider>{children}</AuthProvider>;
      const { result } = renderHook(() => useAuth(), { wrapper });

      await act(async () => {
        await result.current.logout();
      });

      expect(setHref).toHaveBeenCalledTimes(1);
      const target = new URL(setHref.mock.calls[0][0] as string);
      // Logout goes to the site host (proxied to Cognito at /logout), not to a
      // separate login subdomain.
      expect(target.host).toBe('dev.kernelworx.app');
      expect(target.pathname).toBe('/logout');
      expect(target.searchParams.get('logout_uri')).toBe(SITE_URL);
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: originalLocation,
      });
    }
  });
});
