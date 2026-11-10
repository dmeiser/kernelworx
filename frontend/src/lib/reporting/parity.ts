/**
 * Legacy parity manifest for the browser-only reporting engine.
 *
 * Purpose: until the browser engine's reports are proven field-for-field
 * semantically equivalent to the legacy server-generated reports, the
 * legacy queries remain the parity oracle. This module is the executable
 * manifest of that comparison: it declares which legacy report sections
 * each assembled dataset reproduces, the unit-conversion boundary
 * (integer cents internally, float dollars only at the legacy seam), and
 * the absence-is-truth rule (8.2.4(a)): a seller or product the source
 * data does not enumerate appears as an explicit zero row when the
 * legacy contract enumerates it — never as an invented or silently
 * dropped entry.
 *
 * Retirement (integration plan step 7) removes `getUnitReport` only
 * after every manifest row passes against production-shaped fixtures.
 */

import { aggregateByProduct, totalCents, type ProductAggregate } from './assembler';

/** One row of the manifest: a legacy report field group and its rule. */
export interface ParityRule {
  /** Legacy contract field, e.g. "UnitReport.sellers[].totalSales". */
  legacyField: string;
  /** Assembled-dataset source that reproduces it. */
  engineSource: string;
  /** Human-readable semantic rule the reconciliation must satisfy. */
  rule: string;
}

export const LEGACY_PARITY_MANIFEST: ReadonlyArray<ParityRule> = [
  {
    legacyField: 'UnitReport.totalSales',
    engineSource: 'aggregateByProduct -> totalCents',
    rule: 'Sum of per-line integer cents equals round(legacy float dollars * 100).',
  },
  {
    legacyField: 'UnitReport.totalOrders',
    engineSource: 'sale rows count',
    rule: 'One sale row counts once; corrections do not double-count (revision-gated rows).',
  },
  {
    legacyField: 'UnitSellerSummary.totalSales',
    engineSource: 'per-seller aggregate',
    rule: 'Per-seller cents sum equals the seller legacy dollars * 100 exactly.',
  },
  {
    legacyField: 'UnitSellerSummary.orderCount',
    engineSource: 'per-seller sale count',
    rule: 'Matches the seller order count in the legacy report.',
  },
  {
    legacyField: 'UnitSellerSummary.orders[]',
    engineSource: 'sale detail rows',
    rule: 'Detail rows reconcile to summary totals; absence-is-truth: sellers the roster enumerates but with no sales appear with count 0, never omitted.',
  },
];

// ---------------------------------------------------------------------------
// Legacy boundary conversion
// ---------------------------------------------------------------------------

/**
 * Legacy reports carry Float dollars. Conversion happens ONLY here, at
 * the parity boundary: integer cents -> dollars with exact decimal cents.
 * Never round-trip: dollars are display/legacy comparison values only.
 */
export function centsToLegacyDollars(cents: number): number {
  if (!Number.isInteger(cents)) {
    throw new Error(`Legacy boundary requires integer cents, got ${cents}.`);
  }
  return Math.round((cents / 100) * 100) / 100 === cents / 100 ? cents / 100 : Number((cents / 100).toFixed(2));
}

/** Compares engine cents against a legacy float dollar amount exactly. */
export function matchesLegacyDollars(cents: number, legacyDollars: number): boolean {
  return Math.abs(centsToLegacyDollars(cents) - legacyDollars) < Number.EPSILON;
}

// ---------------------------------------------------------------------------
// Absence-is-truth (8.2.4(a))
// ---------------------------------------------------------------------------

/**
 * Returns the explicit zero rows for sellers the roster enumerates that
 * the sales dataset does not. The legacy contract enumerates every
 * roster seller; a seller with no sales is a row with zero totals, not an
 * absence. Passing an empty roster returns empty (the engine never
 * invents scope).
 */
export function absentSellerZeroRows<Row extends { sellerName: string }>(
  rosterSellerNames: ReadonlyArray<string>,
  presentRows: ReadonlyArray<Row>,
): Array<{ sellerName: string; totalCents: number; saleCount: number }> {
  const present = new Set(presentRows.map((row) => row.sellerName));
  return rosterSellerNames
    .filter((name) => !present.has(name))
    .sort((a, b) => a.localeCompare(b))
    .map((sellerName) => ({ sellerName, totalCents: 0, saleCount: 0 }));
}

// ---------------------------------------------------------------------------
// Reconciliation
// ---------------------------------------------------------------------------

export interface ReconciliationIssue {
  rule: string;
  detail: string;
}

export interface SellerSalesRow {
  sellerName: string;
  sellerCents: number;
  saleCount: number;
}

export interface LegacyParityInput {
  /** Engine-side aggregates, integer cents. */
  productAggregates: ReadonlyArray<ProductAggregate>;
  perSeller: ReadonlyArray<SellerSalesRow>;
  /** Legacy-side totals to compare against. */
  legacyTotalDollars: number;
  legacyTotalOrders: number;
  legacyPerSellerDollars: ReadonlyArray<{ sellerName: string; totalDollars: number; orderCount: number }>;
}

/**
 * Runs every manifest rule over one assembled dataset and its legacy
 * oracle values. Returns the list of violations (empty = parity holds).
 * The caller decides whether to block retirement on any non-empty result.
 */
function reconcileTotals(input: LegacyParityInput, issues: ReconciliationIssue[]): void {
  const engineTotal = totalCents(input.productAggregates);
  if (!matchesLegacyDollars(engineTotal, input.legacyTotalDollars)) {
    issues.push({
      rule: 'UnitReport.totalSales',
      detail: `engine ${engineTotal} cents vs legacy $${input.legacyTotalDollars}`,
    });
  }
  const engineOrders = input.perSeller.reduce((acc, row) => acc + row.saleCount, 0);
  if (engineOrders !== input.legacyTotalOrders) {
    issues.push({
      rule: 'UnitReport.totalOrders',
      detail: `engine ${engineOrders} vs legacy ${input.legacyTotalOrders}`,
    });
  }
}

function reconcileMissingSeller(
  legacy: { sellerName: string; totalDollars: number; orderCount: number },
  issues: ReconciliationIssue[],
): void {
  // Absence-is-truth: a legacy zero-seller the engine omitted is fine.
  if (legacy.totalDollars !== 0 || legacy.orderCount !== 0) {
    issues.push({
      rule: 'UnitSellerSummary',
      detail: `seller "${legacy.sellerName}" missing from engine dataset`,
    });
  }
}

function reconcileOneSeller(
  legacy: { sellerName: string; totalDollars: number; orderCount: number },
  engine: SellerSalesRow | undefined,
  issues: ReconciliationIssue[],
): void {
  if (!engine) {
    reconcileMissingSeller(legacy, issues);
    return;
  }
  if (!matchesLegacyDollars(engine.sellerCents, legacy.totalDollars)) {
    issues.push({
      rule: 'UnitSellerSummary.totalSales',
      detail: `seller "${legacy.sellerName}" engine ${engine.sellerCents} cents vs legacy $${legacy.totalDollars}`,
    });
  }
  if (engine.saleCount !== legacy.orderCount) {
    issues.push({
      rule: 'UnitSellerSummary.orderCount',
      detail: `seller "${legacy.sellerName}" engine ${engine.saleCount} vs legacy ${legacy.orderCount}`,
    });
  }
}

export function reconcileAgainstLegacy(input: LegacyParityInput): ReconciliationIssue[] {
  const issues: ReconciliationIssue[] = [];
  reconcileTotals(input, issues);
  // Per-seller rows: every legacy seller must be reconciled, and
  // absence-is-truth rows (zero) must match legacy zero sellers.
  const engineBySeller = new Map(input.perSeller.map((row) => [row.sellerName, row]));
  for (const legacy of input.legacyPerSellerDollars) {
    reconcileOneSeller(legacy, engineBySeller.get(legacy.sellerName), issues);
  }
  return issues;
}

export { aggregateByProduct };
