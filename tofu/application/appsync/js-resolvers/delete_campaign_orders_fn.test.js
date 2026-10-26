import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_campaign_orders_fn.js';

// Table name matching the template placeholder defined in delete_campaign_orders_fn.js
const TABLE_NAME = '${table_name}';

describe('delete_campaign_orders_fn request', () => {
    it('early-returns true when ordersToDelete is empty', () => {
        const ctx = {
            stash: {
                ordersToDelete: [],
            },
        };

        const result = request(ctx);

        assert.strictEqual(result, true);
    });

    it('early-returns true when ordersToDelete is undefined', () => {
        const ctx = {
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result, true);
    });

    it('builds BatchDeleteItem request with mapped keys', () => {
        const ctx = {
            stash: {
                ordersToDelete: [
                    { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' },
                    { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o2' },
                ],
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'BatchDeleteItem');
        assert.deepStrictEqual(result.tables[TABLE_NAME], [
            { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' },
            { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o2' },
        ]);
    });
});

describe('delete_campaign_orders_fn response', () => {
    it('counts deleted orders and updates stash on success', () => {
        const ctx = {
            stash: {},
            result: {
                data: {
                    [TABLE_NAME]: [
                        { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' },
                        { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o2' },
                    ],
                },
            },
        };

        const result = response(ctx);

        assert.strictEqual(result, 2);
        assert.strictEqual(ctx.stash.deletedOrdersCount, 2);
    });

    it('filters out null items in tableData when counting deletions', () => {
        const ctx = {
            stash: {},
            result: {
                data: {
                    [TABLE_NAME]: [
                        { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' },
                        null,
                    ],
                },
            },
        };

        const result = response(ctx);

        assert.strictEqual(result, 1);
        assert.strictEqual(ctx.stash.deletedOrdersCount, 1);
    });

    it('returns 0 deleted count when tableData is missing', () => {
        const ctx = {
            stash: {},
            result: {
                data: {},
            },
        };

        const result = response(ctx);

        assert.strictEqual(result, 0);
        assert.strictEqual(ctx.stash.deletedOrdersCount, 0);
    });

    it('throws INTERNAL_ERROR when unprocessedKeys has unprocessed orders', () => {
        const ctx = {
            stash: {},
            result: {
                data: {
                    [TABLE_NAME]: [{ campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' }],
                },
                unprocessedKeys: {
                    [TABLE_NAME]: [{ campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o2' }],
                },
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Failed to delete 1 order\(s\)/
        );
        assert.strictEqual(ctx.stash.deletedOrdersCount, undefined);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            stash: {},
            error: { message: 'Batch write throttled', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Batch write throttled/
        );
    });
});
