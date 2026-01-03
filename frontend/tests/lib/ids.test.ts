import { describe, it, expect } from 'vitest';
import {
  ensurePrefixed,
  stripPrefix,
  ensureProfileId,
  ensureCampaignId,
  ensureCatalogId,
  ensureProductId,
  ensureOrderId,
  ensureAccountId,
  toUrlId,
} from '../../src/lib/ids';

describe('lib/ids', () => {
  describe('ensurePrefixed', () => {
    it('adds prefix if not present', () => {
      expect(ensurePrefixed('PROFILE', 'abc-123')).toBe('PROFILE#abc-123');
    });

    it('returns ID unchanged if prefix already present', () => {
      expect(ensurePrefixed('PROFILE', 'PROFILE#abc-123')).toBe('PROFILE#abc-123');
    });

    it('returns null for null input', () => {
      expect(ensurePrefixed('PROFILE', null)).toBeNull();
    });

    it('returns null for undefined input', () => {
      expect(ensurePrefixed('PROFILE', undefined)).toBeNull();
    });

    it('returns null for empty string', () => {
      expect(ensurePrefixed('PROFILE', '')).toBeNull();
    });
  });

  describe('stripPrefix', () => {
    it('removes prefix from ID', () => {
      expect(stripPrefix('PROFILE#abc-123')).toBe('abc-123');
    });

    it('returns ID unchanged if no hash present', () => {
      expect(stripPrefix('abc-123')).toBe('abc-123');
    });

    it('returns empty string for null input', () => {
      expect(stripPrefix(null)).toBe('');
    });

    it('returns empty string for undefined input', () => {
      expect(stripPrefix(undefined)).toBe('');
    });

    it('returns empty string for empty string input', () => {
      expect(stripPrefix('')).toBe('');
    });

    it('handles multiple hashes by using first one', () => {
      expect(stripPrefix('PREFIX#abc#def')).toBe('abc#def');
    });
  });

  describe('ensureProfileId', () => {
    it('adds PROFILE# prefix', () => {
      expect(ensureProfileId('abc-123')).toBe('PROFILE#abc-123');
    });
  });

  describe('ensureCampaignId', () => {
    it('adds CAMPAIGN# prefix', () => {
      expect(ensureCampaignId('abc-123')).toBe('CAMPAIGN#abc-123');
    });
  });

  describe('ensureCatalogId', () => {
    it('adds CATALOG# prefix', () => {
      expect(ensureCatalogId('abc-123')).toBe('CATALOG#abc-123');
    });
  });

  describe('ensureProductId', () => {
    it('adds PRODUCT# prefix', () => {
      expect(ensureProductId('abc-123')).toBe('PRODUCT#abc-123');
    });
  });

  describe('ensureOrderId', () => {
    it('adds ORDER# prefix', () => {
      expect(ensureOrderId('abc-123')).toBe('ORDER#abc-123');
    });
  });

  describe('ensureAccountId', () => {
    it('adds ACCOUNT# prefix', () => {
      expect(ensureAccountId('abc-123')).toBe('ACCOUNT#abc-123');
    });
  });

  describe('toUrlId', () => {
    it('extracts UUID from prefixed ID', () => {
      expect(toUrlId('PROFILE#abc-123')).toBe('abc-123');
    });

    it('returns unchanged if no prefix', () => {
      expect(toUrlId('abc-123')).toBe('abc-123');
    });
  });
});
