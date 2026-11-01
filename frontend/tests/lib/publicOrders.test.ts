import { buildSharePath, resolveReceiptUrl } from '../../src/lib/publicOrders';

describe('publicOrders', () => {
  describe('buildSharePath', () => {
    it('returns the correct path', () => {
      expect(buildSharePath('campaign123', 'token456')).toBe('/o/campaign123/token456');
    });

    it('normalizes prefixed campaign IDs using toUrlId', () => {
      expect(buildSharePath('CAMPAIGN#campaign123', 'token456')).toBe('/o/campaign123/token456');
    });
  });

  describe('resolveReceiptUrl', () => {
    it('returns a valid root-relative receipt path unchanged', () => {
      expect(resolveReceiptUrl('/r/campaign123/suffix456/token789')).toBe(
        '/r/campaign123/suffix456/token789',
      );
    });

    it('returns the root-relative path of a same-origin https receipt URL', () => {
      expect(resolveReceiptUrl(`https://${window.location.host}/r/c1/s1/t1`)).toBe('/r/c1/s1/t1');
    });

    it('strips query string and fragment from same-origin https receipt URLs', () => {
      expect(resolveReceiptUrl(`https://${window.location.host}/r/c1/s1/t1?utm=qr#fragment`)).toBe(
        '/r/c1/s1/t1',
      );
    });

    it('returns null for a fragment in a root-relative path', () => {
      expect(resolveReceiptUrl('/r/c1/s1/t1#fragment')).toBeNull();
    });

    it('returns null for javascript: and data: URLs', () => {
      expect(resolveReceiptUrl('javascript:alert(1)')).toBeNull();
      expect(resolveReceiptUrl('data:text/html,<script>alert(1)</script>')).toBeNull();
    });

    it('returns null for http: and other schemes', () => {
      expect(resolveReceiptUrl(`http://${window.location.host}/r/c1/s1/t1`)).toBeNull();
      expect(resolveReceiptUrl('mailto:seller@example.com')).toBeNull();
    });

    it('returns null for relative paths and protocol-relative URLs', () => {
      expect(resolveReceiptUrl('r/c1/s1/t1')).toBeNull();
      expect(resolveReceiptUrl('//evil.example/r/c1/s1/t1')).toBeNull();
    });

    it('returns null for foreign hosts, even with a receipt-shaped path', () => {
      expect(resolveReceiptUrl('https://evil.example/r/c1/s1/t1')).toBeNull();
    });

    it('returns null for same-origin https URLs whose path is not a receipt path', () => {
      expect(resolveReceiptUrl(`https://${window.location.host}/o/c1/t1`)).toBeNull();
      expect(resolveReceiptUrl(`https://${window.location.host}/r/c1/s1`)).toBeNull();
      expect(resolveReceiptUrl(`https://${window.location.host}/r/c1/s1/t1/t2`)).toBeNull();
    });

    it('returns null for an https URL that fails to parse', () => {
      expect(resolveReceiptUrl('https://')).toBeNull();
    });

    it('returns null for null, undefined, empty, and non-string values', () => {
      expect(resolveReceiptUrl(null)).toBeNull();
      expect(resolveReceiptUrl(undefined)).toBeNull();
      expect(resolveReceiptUrl('')).toBeNull();
      expect(resolveReceiptUrl('   ')).toBeNull();
      expect(resolveReceiptUrl(42 as unknown as string)).toBeNull();
    });
  });
});
