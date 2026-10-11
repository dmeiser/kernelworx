/**
 * Tests for the public order id and URL helpers.
 *
 * The receipt-link safety gate is the one to read carefully: a raw order id is
 * `ORDER#<campaignId>#<orderSuffix>`, `#` is the URL fragment delimiter, and
 * `lib/ids.ts` cuts at the FIRST `#` — so a link carrying a raw `#` would be
 * truncated by the browser and must never reach an href.
 */

import { describe, it, expect } from 'vitest';
import { buildSharePath, buildShareUrl, resolveReceiptUrl } from '../../src/lib/publicOrders';

const CAMPAIGN = '7f0f1c2e-1111-4aaa-8bbb-0c1d2e3f4a5b';
const SUFFIX = '9a8b7c6d-2222-4bbb-9ccc-1d2e3f4a5b6c';
const FULL_ID = `ORDER#${CAMPAIGN}#${SUFFIX}`;

describe('buildSharePath / buildShareUrl', () => {
  it('builds the two-segment share path', () => {
    expect(buildSharePath('p-1', 'tok en')).toBe('/o/p-1/tok%20en');
  });

  it('prefixes the share path with the current origin', () => {
    expect(buildShareUrl('p-1', 'token')).toBe(`${window.location.origin}/o/p-1/token`);
  });
});

describe('resolveReceiptUrl', () => {
  it('passes an absolute receipt URL through unchanged', () => {
    expect(resolveReceiptUrl('https://dev.kernelworx.app/r/c/s/token')).toBe(
      'https://dev.kernelworx.app/r/c/s/token',
    );
  });

  it('resolves the documented relative receipt path against the site origin', () => {
    expect(resolveReceiptUrl(`/r/${CAMPAIGN}/${SUFFIX}/receipt-token`)).toBe(
      `${window.location.origin}/r/${CAMPAIGN}/${SUFFIX}/receipt-token`,
    );
  });

  it('rejects a URL carrying a raw order id (#) — the browser would truncate it', () => {
    expect(resolveReceiptUrl(`https://dev.kernelworx.app/r/${FULL_ID}/token`)).toBeNull();
    expect(resolveReceiptUrl(`/r/${FULL_ID}/token`)).toBeNull();
  });

  it('rejects anything that is neither an absolute URL nor a site path', () => {
    expect(resolveReceiptUrl('mailto:someone@example.com')).toBeNull();
    expect(resolveReceiptUrl('r/c/s/token')).toBeNull();
  });

  it('rejects an empty, missing or blank URL', () => {
    expect(resolveReceiptUrl('')).toBeNull();
    expect(resolveReceiptUrl(null)).toBeNull();
    expect(resolveReceiptUrl(undefined)).toBeNull();
  });
});
