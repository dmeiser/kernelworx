import { describe, it, expect, vi } from 'vitest';
import { isSessionDismissed } from '../src/lib/amrTripwire';

describe('amrTripwire', () => {
  it('returns false when sessionStorage access throws', () => {
    const getItem = vi.fn(() => {
      throw new Error('blocked');
    });
    vi.stubGlobal('sessionStorage', { getItem });
    try {
      expect(isSessionDismissed('any-key')).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('returns false when sessionStorage is undefined', () => {
    const original = (globalThis as any).sessionStorage;
    try {
      delete (globalThis as any).sessionStorage;
      expect(isSessionDismissed('any-key')).toBe(false);
    } finally {
      if (original) (globalThis as any).sessionStorage = original;
    }
  });
});
