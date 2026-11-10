/**
 * EXECUTABLE GATE for legacy report retirement (integration plan step 7).
 *
 * Review finding W5-1 (r2, wave 5): the parity manifest was executable
 * but nothing gated on it — getUnitReport could have retired on a human
 * promise. This file IS the gate: scripts/reporting-parity-gate.mjs runs
 * it in CI on every PR to main, and any PR touching the retirement block
 * (removing getUnitReport / UnitReport surface, or modifying
 * src/handlers/campaign_reporting.py) necessarily carries a passing gate
 * run because this check is required.
 *
 * The fixtures below are production-SHAPED: multi-seller, multi-product,
 * integer-cents engine side vs float-dollar legacy oracle side, one
 * roster seller with zero sales exercising 8.2.4(a). The negative
 * control proves the gate is not vacuous: a deliberately mismatched
 * fixture MUST produce violations (asserted, not assumed).
 */

import { describe, it, expect } from 'vitest';
import { aggregateByProduct } from './assembler';
import { absentSellerZeroRows, reconcileAgainstLegacy, type LegacyParityInput } from './parity';

/** Production-shaped engine dataset: three sellers, four products. */
const ENGINE_LINES = [
  { productId: 'p-cookie', productName: 'Cookies', quantity: 14, unitPriceCents: 350 },
  { productId: 'p-cookie', productName: 'Cookies', quantity: 6, unitPriceCents: 350 },
  { productId: 'p-popcorn', productName: 'Popcorn', quantity: 9, unitPriceCents: 1000 },
  { productId: 'p-nuts', productName: 'Nuts', quantity: 3, unitPriceCents: 550 },
  { productId: 'p-pretzel', productName: 'Pretzels', quantity: 11, unitPriceCents: 425 },
];

const ROSTER = ['Alice', 'Bob', 'Carol'];

const PASSING_INPUT: LegacyParityInput = {
  productAggregates: aggregateByProduct(ENGINE_LINES),
  // Cookies 20*350 = 7000c ($70.00); Popcorn 9*1000 = 9000c ($90.00);
  // Nuts 3*550 = 1650c ($16.50); Pretzels 11*425 = 4675c ($46.75).
  perSeller: [
    { sellerName: 'Alice', sellerCents: 7000 + 1650, saleCount: 2 },
    { sellerName: 'Bob', sellerCents: 9000, saleCount: 1 },
    { sellerName: 'Carol', sellerCents: 4675, saleCount: 1 },
  ],
  legacyTotalDollars: 223.25,
  legacyTotalOrders: 4,
  legacyPerSellerDollars: [
    { sellerName: 'Alice', totalDollars: 86.5, orderCount: 2 },
    { sellerName: 'Bob', totalDollars: 90.0, orderCount: 1 },
    { sellerName: 'Carol', totalDollars: 46.75, orderCount: 1 },
  ],
};

describe('reporting parity gate (retirement precondition)', () => {
  it('passes production-shaped fixtures with zero violations', () => {
    expect(reconcileAgainstLegacy(PASSING_INPUT)).toEqual([]);
  });

  it('enumerates zero-sale roster sellers as explicit absence-is-truth rows', () => {
    const present = PASSING_INPUT.perSeller.filter((row) => row.sellerName !== 'Carol');
    const zeroRows = absentSellerZeroRows(ROSTER, present);
    expect(zeroRows).toEqual([{ sellerName: 'Carol', totalCents: 0, saleCount: 0 }]);
  });

  it('NEGATIVE CONTROL: a drifted legacy total is detected (gate is not vacuous)', () => {
    const drifted = { ...PASSING_INPUT, legacyTotalDollars: 223.26 };
    const issues = reconcileAgainstLegacy(drifted);
    expect(issues.length).toBeGreaterThan(0);
    expect(issues.some((i) => i.rule === 'UnitReport.totalSales')).toBe(true);
  });

  it('NEGATIVE CONTROL: an engine seller missing against a non-zero legacy seller is detected', () => {
    const missing = {
      ...PASSING_INPUT,
      perSeller: PASSING_INPUT.perSeller.filter((row) => row.sellerName !== 'Bob'),
    };
    const issues = reconcileAgainstLegacy(missing);
    expect(issues.some((i) => i.rule === 'UnitSellerSummary' && i.detail.includes('Bob'))).toBe(true);
  });

  it('NEGATIVE CONTROL: a per-seller count drift is detected', () => {
    const drifted = {
      ...PASSING_INPUT,
      legacyPerSellerDollars: PASSING_INPUT.legacyPerSellerDollars.map((row) =>
        row.sellerName === 'Alice' ? { ...row, orderCount: 3 } : row,
      ),
    };
    const issues = reconcileAgainstLegacy(drifted);
    expect(issues.some((i) => i.rule === 'UnitSellerSummary.orderCount')).toBe(true);
  });
});
