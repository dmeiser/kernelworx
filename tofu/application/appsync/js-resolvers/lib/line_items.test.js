import { describe, it } from 'node:test';
import assert from 'node:assert';
import { enrichLineItems } from './line_items.js';

const CATALOG = {
    products: [
        { productId: 'PROD#1', productName: 'Popcorn', price: 1.99 },
        { productId: 'PROD#2', productName: 'Caramel', price: 0.1 },
        { productId: 'PROD#3', productName: 'Cheese', price: 0.2 },
    ],
};

describe('enrichLineItems', () => {
    it('computes per-unit price, subtotal and total in integer cents', () => {
        const { enrichedLineItems, totalAmountCents } = enrichLineItems(
            [{ productId: 'PROD#1', quantity: 3 }],
            CATALOG
        );

        assert.deepStrictEqual(enrichedLineItems, [
            { productId: 'PROD#1', productName: 'Popcorn', quantity: 3, pricePerUnit: 1.99, subtotal: 5.97 },
        ]);
        assert.strictEqual(totalAmountCents, 597);
    });

    it('sums totals in cents so 0.10 + 0.20 does not drift to 0.30000000000000004', () => {
        const { enrichedLineItems, totalAmountCents } = enrichLineItems(
            [
                { productId: 'PROD#2', quantity: 1 },
                { productId: 'PROD#3', quantity: 1 },
            ],
            CATALOG
        );

        assert.strictEqual(enrichedLineItems[0].subtotal, 0.1);
        assert.strictEqual(enrichedLineItems[1].subtotal, 0.2);
        // 0.10 + 0.20 in float dollars is 0.30000000000000004; in cents it is 30.
        assert.strictEqual(totalAmountCents, 30);
        assert.strictEqual(totalAmountCents / 100, 0.3);
    });

    it('rounds a fractional cent price to the nearest cent (round, never floor)', () => {
        // 0.125 * 100 is exactly 12.5: Math.round -> 13, Math.floor -> 12.
        const half = enrichLineItems(
            [{ productId: 'PROD#4', quantity: 1 }],
            { products: [{ productId: 'PROD#4', productName: 'Odd', price: 0.125 }] }
        );
        assert.strictEqual(half.enrichedLineItems[0].pricePerUnit, 0.13);
        assert.strictEqual(half.totalAmountCents, 13);

        // 1.995 * 100 is 199.5: Math.round -> 200, Math.floor -> 199.
        const up = enrichLineItems(
            [{ productId: 'PROD#4', quantity: 1 }],
            { products: [{ productId: 'PROD#4', productName: 'Odd', price: 1.995 }] }
        );
        assert.strictEqual(up.enrichedLineItems[0].pricePerUnit, 2);
        assert.strictEqual(up.totalAmountCents, 200);
    });

    it('multiplies quantity against the rounded per-unit cents, not the dollar price', () => {
        // 0.07 * 3 in float dollars is 0.21000000000000002.
        const { totalAmountCents } = enrichLineItems(
            [{ productId: 'PROD#5', quantity: 3 }],
            { products: [{ productId: 'PROD#5', productName: 'Nuts', price: 0.07 }] }
        );

        assert.strictEqual(totalAmountCents, 21);
    });

    it('rejects a quantity below 1 with INVALID_INPUT', () => {
        assert.throws(
            () => enrichLineItems([{ productId: 'PROD#1', quantity: 0 }], CATALOG),
            /INVALID_INPUT: Quantity must be at least 1 \(got 0\)/
        );
    });

    it('rejects a productId missing from the catalog with INVALID_INPUT', () => {
        assert.throws(
            () => enrichLineItems([{ productId: 'PROD#NOPE', quantity: 1 }], CATALOG),
            /INVALID_INPUT: Product PROD#NOPE not found in catalog/
        );
    });

    it('rejects a line item against an empty catalog', () => {
        assert.throws(
            () => enrichLineItems([{ productId: 'PROD#1', quantity: 1 }], { products: [] }),
            /INVALID_INPUT: Product PROD#1 not found in catalog/
        );
    });
});
