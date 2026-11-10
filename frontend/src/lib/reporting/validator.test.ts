/**
 * Tests for the reporting-engine validator.
 */

import { describe, it, expect } from 'vitest';
import {
  CrossScopeRowError,
  MissingDetailError,
  assertScopeConsistency,
  assertVersionStability,
  requireFields,
} from './validator';

describe('assertScopeConsistency', () => {
  it('passes rows matching the scope', () => {
    expect(() =>
      assertScopeConsistency(
        [{ unitCampaignId: 'uc-1' }, { unitCampaignId: 'uc-1', productId: 'p' }],
        'unitCampaignId',
        'uc-1',
      ),
    ).not.toThrow();
  });

  it('passes rows that omit the checked field (projection-dependent)', () => {
    expect(() => assertScopeConsistency([{ productId: 'p' }], 'unitCampaignId', 'uc-1')).not.toThrow();
  });

  it('fails loudly on a cross-scope identifier', () => {
    expect(() => assertScopeConsistency([{ unitCampaignId: 'uc-2' }], 'unitCampaignId', 'uc-1')).toThrow(
      CrossScopeRowError,
    );
  });
});

describe('requireFields', () => {
  it('passes complete rows', () => {
    expect(() => requireFields([{ productId: 'p', quantity: 2 }], ['productId', 'quantity'])).not.toThrow();
  });

  it('fails on missing required detail', () => {
    expect(() => requireFields([{ productId: 'p' }], ['quantity'])).toThrow(MissingDetailError);
  });

  it('fails on null detail', () => {
    expect(() => requireFields([{ quantity: null }], ['quantity'])).toThrow(MissingDetailError);
  });
});

describe('assertVersionStability', () => {
  it('passes unchanged versions', () => {
    expect(() =>
      assertVersionStability({ inventory: 3, finalization: 9 }, { inventory: 3, finalization: 9 }),
    ).not.toThrow();
  });

  it('fails on drift with a refresh instruction', () => {
    expect(() => assertVersionStability({ inventory: 4 }, { inventory: 3 })).toThrow(/refresh/i);
  });

  it('ignores sources not present in the observed set', () => {
    expect(() => assertVersionStability({}, { inventory: 3 })).not.toThrow();
  });
});
