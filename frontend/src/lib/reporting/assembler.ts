/**
 * Report assembler for the browser-only reporting engine.
 *
 * Pure functions: grouping, filtering, sorting, and aggregation use
 * integer quantities and integer cents only. Display currency is applied
 * at presentation time, never during assembly — the same function drives
 * screen, CSV, XLSX, and printable output so totals cannot diverge.
 */

export interface ProductAggregate {
  productId: string;
  productName: string;
  quantity: number;
  /** Integer cents. */
  totalCents: number;
}

/**
 * Adds integer cents without float intermediates. Inputs must already be
 * integers; a non-integer input is a programming error and throws.
 */
export function addCents(a: number, b: number): number {
  assertIntegerCents(a);
  assertIntegerCents(b);
  return a + b;
}

function assertIntegerCents(value: number): void {
  if (!Number.isInteger(value)) {
    throw new Error(`Money must be integer cents, got ${value}.`);
  }
}

/**
 * Display conversion: integer cents -> "$1,234.56". This is presentation
 * ONLY; never feed its output back into an aggregate.
 */
export function formatCents(cents: number): string {
  assertIntegerCents(cents);
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, '0');
  const grouped = dollars.toLocaleString('en-US');
  return `${negative ? '-' : ''}$${grouped}.${fraction}`;
}

export function groupBy<Row>(rows: ReadonlyArray<Row>, keyFn: (row: Row) => string): Map<string, Row[]> {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const key = keyFn(row);
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(row);
    } else {
      groups.set(key, [row]);
    }
  }
  return groups;
}

/** Stable sort by a string key extracted per row. */
export function sortByString<Row>(rows: ReadonlyArray<Row>, keyFn: (row: Row) => string): Row[] {
  return [...rows].sort((a, b) => keyFn(a).localeCompare(keyFn(b)));
}

/** Numeric descending sort (largest first) for report rankings. */
export function sortByNumberDesc<Row>(rows: ReadonlyArray<Row>, valueFn: (row: Row) => number): Row[] {
  return [...rows].sort((a, b) => valueFn(b) - valueFn(a));
}

/**
 * Aggregates sale lines per product with integer arithmetic. Rows without
 * a positive quantity contribute zero; quantity and cents are summed
 * independently and both must be integers throughout.
 */
export function aggregateByProduct(
  lines: ReadonlyArray<{ productId: string; productName: string; quantity: number; unitPriceCents: number }>,
): ProductAggregate[] {
  const groups = groupBy(lines, (line) => line.productId);
  const aggregates: ProductAggregate[] = [];
  for (const [productId, productLines] of groups) {
    let quantity = 0;
    let totalCents = 0;
    let productName = productId;
    for (const line of productLines) {
      if (!Number.isInteger(line.quantity)) {
        throw new Error(`Quantity must be an integer, got ${line.quantity}.`);
      }
      assertIntegerCents(line.unitPriceCents);
      quantity += line.quantity;
      totalCents = addCents(totalCents, line.quantity * line.unitPriceCents);
      productName = line.productName || productName;
    }
    aggregates.push({ productId, productName, quantity, totalCents });
  }
  return sortByString(aggregates, (a) => a.productName);
}

/** Grand total across product aggregates — integer cents. */
export function totalCents(aggregates: ReadonlyArray<ProductAggregate>): number {
  return aggregates.reduce((acc, a) => addCents(acc, a.totalCents), 0);
}

/**
 * Council-Needs-style coverage formula, kept generic: for each product,
 * need = max(0, target - onHand). Pure integer; targets and on-hand are
 * quantities. The specific Show & Sell Council Needs projection supplies
 * the target/on-hand extractors.
 */
export function coverageNeeds<Row>(
  rows: ReadonlyArray<Row>,
  extract: (row: Row) => { productId: string; productName: string; target: number; onHand: number },
): Array<{ productId: string; productName: string; need: number }> {
  return rows
    .map((row) => {
      const { productId, productName, target, onHand } = extract(row);
      return { productId, productName, need: Math.max(0, target - onHand) };
    })
    .filter((row) => row.need > 0);
}
