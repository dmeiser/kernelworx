import { describe, it, expect, vi, afterEach } from 'vitest';
import { getOAuthRedirectUrls } from '../src/lib/amplify';

describe('getOAuthRedirectUrls', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('trims trailing slashes from the provided envUrl', () => {
    const urls = getOAuthRedirectUrls('http://localhost:5173/');
    expect(urls[0]).toBe('http://localhost:5173');
  });

  it('trims multiple trailing slashes from the provided envUrl', () => {
    const urls = getOAuthRedirectUrls('https://dev.kernelworx.app///');
    expect(urls[0]).toBe('https://dev.kernelworx.app');
  });

  it('falls back to window.location.origin when envUrl is undefined', () => {
    vi.stubGlobal('window', {
      location: {
        origin: 'https://local.dev.appworx.app:5173',
      },
    });

    const urls = getOAuthRedirectUrls(undefined);
    expect(urls).toEqual(['https://local.dev.appworx.app:5173']);
  });

  it('deduplicates when envUrl and window.location.origin match', () => {
    vi.stubGlobal('window', {
      location: {
        origin: 'https://dev.kernelworx.app',
      },
    });

    const urls = getOAuthRedirectUrls('https://dev.kernelworx.app/');
    expect(urls).toEqual(['https://dev.kernelworx.app']);
  });

  it('includes both envUrl and window.location.origin when they differ', () => {
    vi.stubGlobal('window', {
      location: {
        origin: 'https://local.dev.appworx.app:5173/',
      },
    });

    const urls = getOAuthRedirectUrls('http://localhost:5173/');
    expect(urls).toEqual([
      'http://localhost:5173',
      'https://local.dev.appworx.app:5173',
    ]);
  });

  it('falls back to default localhost URL when envUrl and origin are both empty', () => {
    vi.stubGlobal('window', {
      location: {},
    });

    const urls = getOAuthRedirectUrls(undefined);
    expect(urls).toEqual(['http://localhost:5173']);
  });
});
