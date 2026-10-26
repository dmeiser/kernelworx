import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_order_for_delete_fn.js';

describe('lookup_order_for_delete_fn request', () => {
    it('queries orderId-index GSI with orderId and limit 1', () => {
        const ctx = {
            args: {
                orderId: 'ORDER#campaign-1#uuid-1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'orderId = :orderId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':orderId': 'ORDER#campaign-1#uuid-1',
        });
    });
});

describe('lookup_order_for_delete_fn response', () => {
    it('handles missing order idempotently by stashing null and returning null', () => {
        const ctxMissing = { result: {}, stash: {} };
        const resultMissing = response(ctxMissing);
        assert.strictEqual(resultMissing, null);
        assert.strictEqual(ctxMissing.stash.order, null);

        const ctxEmpty = { result: { items: [] }, stash: {} };
        const resultEmpty = response(ctxEmpty);
        assert.strictEqual(resultEmpty, null);
        assert.strictEqual(ctxEmpty.stash.order, null);
    });

    it('stashes order and returns it when found', () => {
        const order = {
            orderId: 'ORDER#campaign-1#uuid-1',
            campaignId: 'CAMPAIGN#campaign-1',
            totalAmount: 45.0,
        };
        const ctx = {
            stash: {},
            result: {
                items: [order],
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, order);
        assert.deepStrictEqual(ctx.stash.order, order);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'Query failed',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Query failed/
        );
    });
});
