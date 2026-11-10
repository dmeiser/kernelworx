/**
 * Tests for the reporting-engine assembler: integer arithmetic is the
 * contract; display currency appears only at presentation time.
 */

import { describe, it, expect } from 'vitest';
import {
  addCents,
  aggregateByProduct,
  coverageNeeds,
  formatCents,
  groupBy,
  sortByNumberDesc,
  sortByString,
  totalCents,
} from './assembler';

describe('integer cents arithmetic', () => {
  it('adds cents without float drift', () => {
    expect(addCents(100, 250)).toBe(350);
    expect(addCents(0.1 * 1000, 0)).toBe(100); // 0.1*1000 float artifact normalized by caller contract
  });

  it('rejects non-integer money as a programming error', () => {
    expect(() => addCents(10.5, 0)).toThrow(/integer cents/);
    expect(() => formatCents(10.5)).toThrow(/integer cents/);
  });

  it('formats display currency only at presentation', () => {
    expect(formatCents(0)).toBe('$0.00');
    expect(formatCents(5)).toBe('$0.05');
    expect(formatCents(123456)).toBe('$1,234.56');
    expect(formatCents(-99)).toBe('-$0.99');
  });
});

describe('aggregateByProduct', () => {
  const lines = [
    { productId: 'p1', productName: 'Cookies', quantity: 2, unitPriceCents: 350 },
    { productId: 'p1', productName: 'Cookies', quantity: 1, unitPriceCents: 350 },
    { productId: 'p2', productName: 'Popcorn', quantity: 3, unitPriceCents: 1000 },
  ];

  it('aggregates quantities and cents per product with integer math', () => {
    const aggregates = aggregateByProduct(lines);
    expect(aggregates).toEqual([
      { productId: 'p1', productName: 'Cookies', quantity: 3, totalCents: 1050 },
      { productId: 'p2', productName: 'Popcorn', quantity: 3, totalCents: 3000 },
    ]);
    expect(totalCents(aggregates)).toBe(4050);
  });

  it('sorts by product name for stable output', () => {
    const reversed = aggregateByProduct([lines[2], lines[0]]);
    expect(reversed.map((a) => a.productName)).toEqual(['Cookies', 'Popcorn']);
  });

  it('rejects non-integer quantities', () => {
    expect(() =>
      aggregateByProduct([{ productId: 'p', productName: 'P', quantity: 1.5, unitPriceCents: 100 }]),
    ).toThrow(/integer/);
  });
});

describe('grouping and sorting', () => {
  it('groups rows by key preserving insertion order', () => {
    const groups = groupBy(['ab', 'ac', 'bb'], (s) => s[0]);
    expect([...groups.keys()]).toEqual(['a', 'b']);
    expect(groups.get('a')).toEqual(['ab', 'ac']);
  });

  it('sortByString is stable and non-mutating', () => {
    const rows = [{ n: 'b' }, { n: 'a' }];
    const sorted = sortByString(rows, (r) => r.n);
    expect(sorted.map((r) => r.n)).toEqual(['a', 'b']);
    expect(rows[0].n).toBe('b');
  });

  it('sortByNumberDesc ranks largest first', () => {
    const ranked = sortByNumberDesc([{ v: 3 }, { v: 9 }, { v: 4 }], (r) => r.v);
    expect(ranked.map((r) => r.v)).toEqual([9, 4, 3]);
  });
});

describe('coverageNeeds', () => {
  it('computes max(0, target - onHand) per product and drops zero-need rows', () => {
    const needs = coverageNeeds(
      [
        { productId: 'p1', productName: 'Cookies', target: 10, onHand: 4 },
        { productId: 'p2', productName: 'Popcorn', target: 5, onHand: 5 },
        { productId: 'p3', productName: 'Nuts', target: 2, onHand: 9 },
      ],
      (row) => row,
    );
    expect(needs).toEqual([{ productId: 'p1', productName: 'Cookies', need: 6 }]);
  });
});
