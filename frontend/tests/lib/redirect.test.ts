import { describe, it, expect } from 'vitest';
import { isSafeRedirect, getSafeRedirect, resolveRedirectFromState } from '../../src/lib/redirect';

describe('redirect validation', () => {
  describe('isSafeRedirect', () => {
    it('accepts root-relative paths', () => {
      expect(isSafeRedirect('/')).toBe(true);
      expect(isSafeRedirect('/campaigns/123')).toBe(true);
      expect(isSafeRedirect('/scouts?sort=asc')).toBe(true);
    });

    it('rejects absolute URLs', () => {
      expect(isSafeRedirect('https://evil.com')).toBe(false);
      expect(isSafeRedirect('http://localhost:3000/home')).toBe(false);
    });

    it('rejects protocol-relative URLs', () => {
      expect(isSafeRedirect('//evil.com')).toBe(false);
    });

    it('rejects paths containing backslashes', () => {
      expect(isSafeRedirect('/back\\slash')).toBe(false);
    });

    it('rejects non-string and javascript values', () => {
      expect(isSafeRedirect('javascript:alert(1)')).toBe(false);
      expect(isSafeRedirect('')).toBe(false);
      expect(isSafeRedirect(null as unknown as string)).toBe(false);
    });
  });

  describe('getSafeRedirect', () => {
    it('returns the input when it is safe', () => {
      expect(getSafeRedirect('/campaigns/123', '/home')).toBe('/campaigns/123');
    });

    it('returns the fallback when the input is unsafe or missing', () => {
      expect(getSafeRedirect('https://evil.com', '/home')).toBe('/home');
      expect(getSafeRedirect('', '/home')).toBe('/home');
      expect(getSafeRedirect(null as unknown as string, '/home')).toBe('/home');
      expect(getSafeRedirect(undefined as unknown as string, '/home')).toBe('/home');
    });
  });

  describe('resolveRedirectFromState', () => {
    it('resolves string from value', () => {
      expect(resolveRedirectFromState({ from: '/campaigns?tab=active' })).toBe('/campaigns?tab=active');
      expect(resolveRedirectFromState({ from: '/dashboard' })).toBe('/dashboard');
    });

    it('resolves object from value with pathname and search query', () => {
      expect(
        resolveRedirectFromState({ from: { pathname: '/campaigns', search: '?tab=active&sort=desc' } }),
      ).toBe('/campaigns?tab=active&sort=desc');
    });

    it('adds leading question mark to search if missing', () => {
      expect(resolveRedirectFromState({ from: { pathname: '/campaigns', search: 'tab=active' } })).toBe(
        '/campaigns?tab=active',
      );
    });

    it('resolves object from value with pathname only', () => {
      expect(resolveRedirectFromState({ from: { pathname: '/campaigns' } })).toBe('/campaigns');
      expect(resolveRedirectFromState({ from: { pathname: '/campaigns', search: '' } })).toBe('/campaigns');
    });

    it('does not duplicate query if pathname already contains search', () => {
      expect(
        resolveRedirectFromState({ from: { pathname: '/campaigns?tab=active', search: '?tab=active' } }),
      ).toBe('/campaigns?tab=active');
    });

    it('returns undefined for non-objects or missing from', () => {
      expect(resolveRedirectFromState(null)).toBeUndefined();
      expect(resolveRedirectFromState(undefined)).toBeUndefined();
      expect(resolveRedirectFromState('not an object')).toBeUndefined();
      expect(resolveRedirectFromState({})).toBeUndefined();
      expect(resolveRedirectFromState({ from: null })).toBeUndefined();
      expect(resolveRedirectFromState({ from: 123 })).toBeUndefined();
      expect(resolveRedirectFromState({ from: { search: '?tab=active' } })).toBeUndefined();
      expect(resolveRedirectFromState({ from: { pathname: 123 } })).toBeUndefined();
    });
  });
});
