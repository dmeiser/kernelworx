/**
 * Tests for the legacy parity manifest: unit conversion boundary,
 * absence-is-truth (8.2.4(a)), and full reconciliation.
 */

import { describe, it, expect } from 'vitest';
import {
  LEGACY_PARITY_MANIFEST,
  absentSellerZeroRows,
  centsToLegacyDollars,
  matchesLegacyDollars,
  reconcileAgainstLegacy,
} from './parity';
import { aggregateByProduct } from './assembler';

describe('LEGACY_PARITY_MANIFEST', () => {
  it('covers totals, order counts, per-seller summaries, and detail rows', () => {
    const fields = LEGACY_PARITY_MANIFEST.map((rule) => rule.legacyField);
    expect(fields).toContain('UnitReport.totalSales');
    expect(fields).toContain('UnitReport.totalOrders');
    expect(fields).toContain('UnitSellerSummary.totalSales');
    expect(fields).toContain('UnitSellerSummary.orderCount');
    expect(fields).toContain('UnitSellerSummary.orders[]');
    for (const rule of LEGACY_PARITY_MANIFEST) {
      expect(rule.engineSource.length).toBeGreaterThan(0);
      expect(rule.rule.length).toBeGreaterThan(0);
    }
  });
});

describe('centsToLegacyDollars', () => {
  it('converts exactly at the boundary and only there', () => {
    expect(centsToLegacyDollars(4050)).toBe(40.5);
    expect(centsToLegacyDollars(5)).toBe(0.05);
    expect(centsToLegacyDollars(123456)).toBe(1234.56);
  });

  it('rejects non-integer cents', () => {
    expect(() => centsToLegacyDollars(10.5)).toThrow(/integer cents/);
  });

  it('matches legacy floats exactly', () => {
    expect(matchesLegacyDollars(4050, 40.5)).toBe(true);
    expect(matchesLegacyDollars(4051, 40.5)).toBe(false);
  });
});

describe('absentSellerZeroRows (8.2.4(a))', () => {
  it('enumerates roster sellers with no sales as explicit zero rows', () => {
    const rows = absentSellerZeroRows(['Alice', 'Bob', 'Carol'], [{ sellerName: 'Bob' }]);
    expect(rows).toEqual([
      { sellerName: 'Alice', totalCents: 0, saleCount: 0 },
      { sellerName: 'Carol', totalCents: 0, saleCount: 0 },
    ]);
  });

  it('never invents rows for an empty roster', () => {
    expect(absentSellerZeroRows([], [])).toEqual([]);
  });

  it('returns empty when every roster seller has sales', () => {
    expect(absentSellerZeroRows(['Alice'], [{ sellerName: 'Alice' }])).toEqual([]);
  });
});

describe('reconcileAgainstLegacy', () => {
  const productAggregates = aggregateByProduct([
    { productId: 'p1', productName: 'Cookies', quantity: 2, unitPriceCents: 350 },
    { productId: 'p2', productName: 'Popcorn', quantity: 1, unitPriceCents: 1000 },
  ]); // 1700 cents total

  const baseInput = {
    productAggregates,
    perSeller: [
      { sellerName: 'Alice', sellerCents: 700, saleCount: 1 },
      { sellerName: 'Bob', sellerCents: 1000, saleCount: 1 },
    ],
    legacyTotalDollars: 17.0,
    legacyTotalOrders: 2,
    legacyPerSellerDollars: [
      { sellerName: 'Alice', totalDollars: 7.0, orderCount: 1 },
      { sellerName: 'Bob', totalDollars: 10.0, orderCount: 1 },
    ],
  };

  it('returns no issues when engine and legacy agree exactly', () => {
    expect(reconcileAgainstLegacy(baseInput)).toEqual([]);
  });

  it('flags a total-sales mismatch', () => {
    const issues = reconcileAgainstLegacy({ ...baseInput, legacyTotalDollars: 17.01 });
    expect(issues.some((i) => i.rule === 'UnitReport.totalSales')).toBe(true);
  });

  it('flags an order-count mismatch', () => {
    const issues = reconcileAgainstLegacy({ ...baseInput, legacyTotalOrders: 3 });
    expect(issues.some((i) => i.rule === 'UnitReport.totalOrders')).toBe(true);
  });

  it('flags a per-seller sales mismatch', () => {
    const issues = reconcileAgainstLegacy({
      ...baseInput,
      legacyPerSellerDollars: [
        { sellerName: 'Alice', totalDollars: 7.5, orderCount: 1 },
        { sellerName: 'Bob', totalDollars: 10.0, orderCount: 1 },
      ],
    });
    expect(issues.some((i) => i.rule === 'UnitSellerSummary.totalSales' && i.detail.includes('Alice'))).toBe(true);
  });

  it('flags a per-seller count mismatch', () => {
    const issues = reconcileAgainstLegacy({
      ...baseInput,
      legacyPerSellerDollars: [
        { sellerName: 'Alice', totalDollars: 7.0, orderCount: 2 },
        { sellerName: 'Bob', totalDollars: 10.0, orderCount: 1 },
      ],
    });
    expect(issues.some((i) => i.rule === 'UnitSellerSummary.orderCount')).toBe(true);
  });

  it('accepts a legacy zero-seller the engine dataset omitted (absence-is-truth)', () => {
    const issues = reconcileAgainstLegacy({
      ...baseInput,
      legacyPerSellerDollars: [
        ...baseInput.legacyPerSellerDollars,
        { sellerName: 'Carol', totalDollars: 0, orderCount: 0 },
      ],
    });
    expect(issues).toEqual([]);
  });

  it('flags a non-zero legacy seller missing from the engine dataset', () => {
    const issues = reconcileAgainstLegacy({
      ...baseInput,
      legacyPerSellerDollars: [
        ...baseInput.legacyPerSellerDollars,
        { sellerName: 'Carol', totalDollars: 5.0, orderCount: 1 },
      ],
    });
    expect(issues.some((i) => i.rule === 'UnitSellerSummary' && i.detail.includes('Carol'))).toBe(true);
  });
});
