import { buildSharePath, resolveReceiptUrl } from '../../src/lib/publicOrders';

describe('publicOrders', () => {
  describe('buildSharePath', () => {
    it('returns the correct path', () => {
      expect(buildSharePath('campaign123', 'token456')).toBe('/o/campaign123/token456');
    });
  });

  describe('resolveReceiptUrl', () => {
    it('returns the url for a non-empty string', () => {
      expect(resolveReceiptUrl('https://example.com/receipt/1')).toBe(
        'https://example.com/receipt/1',
      );
    });

    it('returns null for null or undefined', () => {
      expect(resolveReceiptUrl(null)).toBeNull();
      expect(resolveReceiptUrl(undefined)).toBeNull();
    });

    it('returns null for an all-whitespace string', () => {
      expect(resolveReceiptUrl('   ')).toBeNull();
      expect(resolveReceiptUrl('')).toBeNull();
    });

    it('returns null for a non-string value', () => {
      expect(resolveReceiptUrl(42 as unknown as string)).toBeNull();
    });
  });
});
