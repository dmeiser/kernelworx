import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { getCognitoDomain } from '../src/lib/cognitoDomain';

describe('getCognitoDomain', () => {
  beforeEach(() => {
    delete (import.meta.env as Record<string, unknown>).VITE_COGNITO_DOMAIN;
    delete (import.meta.env as Record<string, unknown>).VITE_OAUTH_REDIRECT_SIGNIN;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('honors VITE_COGNITO_DOMAIN when explicitly set', () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', 'custom-login.example.com');
    expect(getCognitoDomain()).toBe('custom-login.example.com');
  });

  it('honors prefix domains from ephemeral environments via VITE_COGNITO_DOMAIN', () => {
    const ephemeralDomain = 'kernelworx-ue1-pr-123.auth.us-east-1.amazoncognito.com';
    vi.stubEnv('VITE_COGNITO_DOMAIN', ephemeralDomain);
    expect(getCognitoDomain()).toBe(ephemeralDomain);
  });

  it('derives login.<domain> from VITE_OAUTH_REDIRECT_SIGNIN for dev', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'https://dev.kernelworx.app');
    expect(getCognitoDomain()).toBe('login.dev.kernelworx.app');
  });

  it('handles trailing slashes on VITE_OAUTH_REDIRECT_SIGNIN', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'https://dev.kernelworx.app/');
    expect(getCognitoDomain()).toBe('login.dev.kernelworx.app');
  });

  it('derives login.<domain> from VITE_OAUTH_REDIRECT_SIGNIN for prod', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'https://kernelworx.app');
    expect(getCognitoDomain()).toBe('login.kernelworx.app');
  });

  it('does not double-prefix when VITE_OAUTH_REDIRECT_SIGNIN already starts with login.', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'https://login.dev.kernelworx.app');
    expect(getCognitoDomain()).toBe('login.dev.kernelworx.app');
  });

  it('does not prepend login. to localhost URLs', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'http://localhost:5173');
    expect(getCognitoDomain()).toBe('localhost:5173');
  });

  it('falls back to raw string when VITE_OAUTH_REDIRECT_SIGNIN is not a parseable URL', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'dev.kernelworx.app');
    expect(getCognitoDomain()).toBe('login.dev.kernelworx.app');
  });

  it('does not prepend login. to URLs with custom dev ports', () => {
    vi.stubEnv('VITE_OAUTH_REDIRECT_SIGNIN', 'https://local.dev.appworx.app:5173');
    expect(getCognitoDomain()).toBe('local.dev.appworx.app:5173');
  });

  it('falls back to window.location.host and prepends login. for deployed hosts', () => {
    vi.stubGlobal('window', {
      location: { host: 'dev.kernelworx.app' },
    });
    expect(getCognitoDomain()).toBe('login.dev.kernelworx.app');
  });

  it('does not prepend login. when window.location.host is localhost with port', () => {
    vi.stubGlobal('window', {
      location: { host: 'localhost:5173' },
    });
    expect(getCognitoDomain()).toBe('localhost:5173');
  });

  it('does not prepend login. when window.location.host is 127.0.0.1 with port', () => {
    vi.stubGlobal('window', {
      location: { host: '127.0.0.1:5173' },
    });
    expect(getCognitoDomain()).toBe('127.0.0.1:5173');
  });

  it('returns empty string when no domain or window host is available', () => {
    vi.stubGlobal('window', undefined);
    expect(getCognitoDomain()).toBe('');
  });
});
