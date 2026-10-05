/**
 * Tests for the public order id and URL helpers.
 *
 * The split-segment reassembly is the one to read carefully: a raw order id is
 * `ORDER#<campaignId>#<orderSuffix>`, `#` is the URL fragment delimiter, and
 * `lib/ids.ts` cuts at the FIRST `#` — so a single "bare" order id cannot exist
 * and the receipt link must carry the id in two segments.
 */

import { describe, it, expect } from 'vitest';
import {
  ORDER_ID_PREFIX,
  buildOrderIdFromSegments,
  buildReceiptPath,
  buildSharePath,
  buildShareUrl,
  isSplitSegmentReceiptUrl,
  splitOrderIdForPath,
} from '../../src/lib/publicOrders';

const CAMPAIGN = '7f0f1c2e-1111-4aaa-8bbb-0c1d2e3f4a5b';
const SUFFIX = '9a8b7c6d-2222-4bbb-9ccc-1d2e3f4a5b6c';
const FULL_ID = `${ORDER_ID_PREFIX}#${CAMPAIGN}#${SUFFIX}`;

describe('buildOrderIdFromSegments', () => {
  it('reassembles the full id from the two URL segments', () => {
    expect(buildOrderIdFromSegments(CAMPAIGN, SUFFIX)).toBe(FULL_ID);
  });

  it('round-trips through the split', () => {
    const segments = splitOrderIdForPath(FULL_ID);
    expect(segments).not.toBeNull();
    expect(buildOrderIdFromSegments(segments!.campaignId, segments!.orderSuffix)).toBe(FULL_ID);
  });
});

describe('splitOrderIdForPath', () => {
  it('splits a three-part id into campaign and suffix', () => {
    expect(splitOrderIdForPath(FULL_ID)).toEqual({ campaignId: CAMPAIGN, orderSuffix: SUFFIX });
  });

  it('rejects a legacy two-part ORDER#<uuid> id', () => {
    expect(splitOrderIdForPath('ORDER#only-a-uuid')).toBeNull();
  });

  it('rejects an empty or missing id', () => {
    expect(splitOrderIdForPath('')).toBeNull();
    expect(splitOrderIdForPath(null)).toBeNull();
    expect(splitOrderIdForPath(undefined)).toBeNull();
  });

  it('rejects an id with an empty segment', () => {
    expect(splitOrderIdForPath('ORDER##suffix')).toBeNull();
    expect(splitOrderIdForPath('ORDER#campaign#')).toBeNull();
  });
});

describe('buildSharePath / buildShareUrl', () => {
  it('builds the two-segment share path', () => {
    expect(buildSharePath('p-1', 'tok en')).toBe('/o/p-1/tok%20en');
  });

  it('prefixes the share path with the current origin', () => {
    expect(buildShareUrl('p-1', 'token')).toBe(`${window.location.origin}/o/p-1/token`);
  });
});

describe('buildReceiptPath', () => {
  it('builds the split-segment receipt path with no raw # in it', () => {
    const path = buildReceiptPath(FULL_ID, 'receipt-token');
    expect(path).toBe(`/r/${CAMPAIGN}/${SUFFIX}/receipt-token`);
    expect(path).not.toContain('#');
  });

  it('returns null for an id that cannot be split', () => {
    expect(buildReceiptPath('ORDER#legacy-uuid', 'token')).toBeNull();
  });
});

describe('isSplitSegmentReceiptUrl', () => {
  it('accepts an absolute https receipt URL with no fragment character', () => {
    expect(isSplitSegmentReceiptUrl('https://dev.kernelworx.app/r/c/s/token')).toBe(true);
  });

  it('rejects a URL carrying a raw order id (#) — the browser would truncate it', () => {
    expect(isSplitSegmentReceiptUrl(`https://dev.kernelworx.app/r/${FULL_ID}/token`)).toBe(false);
  });

  it('rejects a relative or missing URL', () => {
    expect(isSplitSegmentReceiptUrl('/r/c/s/token')).toBe(false);
    expect(isSplitSegmentReceiptUrl('')).toBe(false);
    expect(isSplitSegmentReceiptUrl(null)).toBe(false);
    expect(isSplitSegmentReceiptUrl(undefined)).toBe(false);
  });
});
