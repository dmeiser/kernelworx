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
            {
                productId: 'PROD#1',
                productName: 'Popcorn',
                quantity: 3,
                pricePerUnit: 1.99,
                subtotal: 5.97,
                lineItemId: 'auto-generated-id',
                fulfilledQuantity: 0,
            },
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

    // §5.19 (checklist 2.4.1): a line's identity is minted once and survives an
    // edit, and its fulfilled count rides along, because a fulfillment recorded
    // against a lineItemId is only meaningful if that id still names the line.
    it('mints a distinct identity per line on the create path, with nothing fulfilled', () => {
        const { enrichedLineItems } = enrichLineItems(
            [{ productId: 'PROD#1', quantity: 2 }, { productId: 'PROD#2', quantity: 1 }],
            CATALOG,
            []
        );

        assert.strictEqual(enrichedLineItems.length, 2);
        // The harness stubs util.autoId() to a constant, so uniqueness is not
        // what this pins; what it pins is that every line gets an identity and a
        // zero fulfilled count rather than an absent one.
        for (const line of enrichedLineItems) {
            assert.strictEqual(typeof line.lineItemId, 'string');
            assert.ok(line.lineItemId.length > 0);
            assert.strictEqual(line.fulfilledQuantity, 0);
        }
    });

    it('inherits identity and the fulfilled count from the stored lines on an edit', () => {
        const stored = [
            { productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 },
            { productId: 'PROD#1', lineItemId: 'LINE#B', fulfilledQuantity: 0, quantity: 1 },
        ];
        const { enrichedLineItems } = enrichLineItems(
            [
                { productId: 'PROD#1', quantity: 4, lineItemId: 'LINE#A' },
                { productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#B' },
            ],
            CATALOG,
            stored
        );

        assert.strictEqual(enrichedLineItems[0].lineItemId, 'LINE#A');
        assert.strictEqual(enrichedLineItems[0].fulfilledQuantity, 2);
        // Two lines of one product must not collapse onto the same identity.
        assert.strictEqual(enrichedLineItems[1].lineItemId, 'LINE#B');
        assert.strictEqual(enrichedLineItems[1].fulfilledQuantity, 0);
    });

    // FUNC-2: matching a row to a stored line by PRODUCT is a guess whenever either side
    // has more than one line for that product. For a line with no history the guess is the
    // pre-Wave-3 contract and stays; for a line that already moved stock it decides which
    // line inherits a fulfilled quantity -- and the fulfillment rows and stock effect
    // attached to it -- so the caller has to say which line it means.
    it('still matches by product when neither side has more than one line for it', () => {
        const stored = [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 0, quantity: 3 }];

        const { enrichedLineItems } = enrichLineItems([{ productId: 'PROD#1', quantity: 4 }], CATALOG, stored);

        assert.strictEqual(enrichedLineItems[0].lineItemId, 'LINE#A');
    });

    it('refuses an ambiguous product mapping when one of the lines already has history', () => {
        const stored = [
            { productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 },
            { productId: 'PROD#1', lineItemId: 'LINE#B', fulfilledQuantity: 0, quantity: 1 },
        ];

        assert.throws(
            () => enrichLineItems(
                [{ productId: 'PROD#1', quantity: 4 }, { productId: 'PROD#1', quantity: 1 }],
                CATALOG,
                stored
            ),
            /INVALID_INPUT: lineItemId is required to change product PROD#1/
        );
    });

    it('refuses a line that keeps a fulfilled identity but changes product', () => {
        const stored = [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 1 }];

        assert.throws(
            () => enrichLineItems([{ productId: 'PROD#2', quantity: 2, lineItemId: 'LINE#A' }], CATALOG, stored),
            /INVALID_INPUT: lineItemId LINE#A has already been fulfilled and cannot change product/
        );
    });

    it('refuses dropping a line that has fulfillment history, because its history would outlive it', () => {
        const stored = [
            { productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 },
            { productId: 'PROD#2', lineItemId: 'LINE#B', fulfilledQuantity: 0, quantity: 1 },
        ];

        assert.throws(
            () => enrichLineItems([{ productId: 'PROD#2', quantity: 1 }], CATALOG, stored),
            /INVALID_INPUT: lineItemId LINE#A has 2 fulfilled item\(s\) and cannot be removed/
        );
    });

    it('lets a line with no history be dropped, which is the edit contract before Wave 3', () => {
        const stored = [
            { productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 0, quantity: 3 },
            { productId: 'PROD#2', lineItemId: 'LINE#B', fulfilledQuantity: 0, quantity: 1 },
        ];

        const { enrichedLineItems } = enrichLineItems([{ productId: 'PROD#2', quantity: 1 }], CATALOG, stored);

        assert.strictEqual(enrichedLineItems.length, 1);
        assert.strictEqual(enrichedLineItems[0].lineItemId, 'LINE#B');
    });

    it('keeps a caller-named lineItemId when it names a stored line', () => {
        const stored = [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 1 }];
        const { enrichedLineItems } = enrichLineItems(
            [{ productId: 'PROD#1', quantity: 5, lineItemId: 'LINE#A' }],
            CATALOG,
            stored
        );

        assert.strictEqual(enrichedLineItems[0].lineItemId, 'LINE#A');
        assert.strictEqual(enrichedLineItems[0].fulfilledQuantity, 1);
    });

    it('refuses a lineItemId that names no line on this order', () => {
        assert.throws(
            () =>
                enrichLineItems(
                    [{ productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#GHOST' }],
                    CATALOG,
                    [{ productId: 'PROD#1', lineItemId: 'LINE#A' }]
                ),
            /INVALID_INPUT: Unknown lineItemId LINE#GHOST for this order/
        );
    });

    it('refuses to edit a line below the quantity already fulfilled', () => {
        // The stored line has 3 ordered / 2 fulfilled. Editing it to 1 ordered
        // would leave a fulfillment naming a line that no longer owes it.
        assert.throws(
            () =>
                enrichLineItems(
                    [{ productId: 'PROD#1', quantity: 1 }],
                    CATALOG,
                    [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 }]
                ),
            /INVALID_INPUT: Quantity of 1 is below the line's already-fulfilled amount of 2/
        );
    });

    it('refuses two rows that name the same stored line, when that line has history', () => {
        // Both rows inherit LINE#A's identity and its fulfilled quantity, so the Order
        // carries two lines claiming one line's history -- and fulfill or reverse, which
        // address a line by id, move it for only the first of them.
        assert.throws(
            () =>
                enrichLineItems(
                    [
                        { productId: 'PROD#1', quantity: 2, lineItemId: 'LINE#A' },
                        { productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#A' },
                    ],
                    CATALOG,
                    [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 }]
                ),
            /INVALID_INPUT: lineItemId LINE#A appears more than once in this update; one row replaces one stored line/
        );
    });

    it('refuses a repeated id on a line with no history too, because the second row would re-key the first', () => {
        assert.throws(
            () =>
                enrichLineItems(
                    [
                        { productId: 'PROD#1', quantity: 2, lineItemId: 'LINE#A' },
                        { productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#A' },
                    ],
                    CATALOG,
                    [{ productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 0, quantity: 3 }]
                ),
            /INVALID_INPUT: lineItemId LINE#A appears more than once/
        );
    });

    it('refuses a repeated id even when the order has no stored lines to name', () => {
        assert.throws(
            () =>
                enrichLineItems(
                    [
                        { productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#A' },
                        { productId: 'PROD#2', quantity: 1, lineItemId: 'LINE#A' },
                    ],
                    CATALOG
                ),
            /INVALID_INPUT: lineItemId LINE#A appears more than once/
        );
    });

    it('binds each named identity to exactly one row when the ids differ', () => {
        const { enrichedLineItems } = enrichLineItems(
            [
                { productId: 'PROD#1', quantity: 2, lineItemId: 'LINE#A' },
                { productId: 'PROD#1', quantity: 1, lineItemId: 'LINE#B' },
            ],
            CATALOG,
            [
                { productId: 'PROD#1', lineItemId: 'LINE#A', fulfilledQuantity: 2, quantity: 3 },
                { productId: 'PROD#1', lineItemId: 'LINE#B', fulfilledQuantity: 1, quantity: 2 },
            ]
        );
        assert.deepStrictEqual(
            enrichedLineItems.map(function (line) { return [line.lineItemId, line.fulfilledQuantity, line.quantity]; }),
            [['LINE#A', 2, 2], ['LINE#B', 1, 1]]
        );
    });
});
