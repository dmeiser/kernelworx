import { describe, it, expect } from 'vitest';
import { isSafeRedirect, getSafeRedirect } from '../../src/lib/redirect';

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
});
