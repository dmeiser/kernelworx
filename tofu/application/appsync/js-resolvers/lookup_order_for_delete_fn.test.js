import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_order_for_delete_fn.js';

describe('lookup_order_for_delete_fn request', () => {
    // #717: this step read the eventually-consistent orderId-index GSI directly,
    // so deleteOrder issued right after createOrder could look up nothing and
    // silently no-op. It now shares buildOrderLookupRequest with getOrder.
    it('uses a strongly consistent base-table GetItem for a new-format order ID', () => {
        const ctx = {
            args: {
                orderId: 'ORDER#campaign-1#uuid-1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            campaignId: 'CAMPAIGN#campaign-1',
            orderId: 'ORDER#campaign-1#uuid-1',
        });
    });

    it('falls back to the orderId-index GSI for a legacy ORDER#<uuid> ID', () => {
        const ctx = {
            args: {
                orderId: 'ORDER#uuid-1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'orderId = :orderId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':orderId': 'ORDER#uuid-1',
        });
    });
});

describe('lookup_order_for_delete_fn response', () => {
    it('handles missing order idempotently by stashing null and returning null', () => {
        const ctxMissing = { result: null, stash: {} };
        const resultMissing = response(ctxMissing);
        assert.strictEqual(resultMissing, null);
        assert.strictEqual(ctxMissing.stash.order, null);

        const ctxEmpty = { result: { items: [] }, stash: {} };
        const resultEmpty = response(ctxEmpty);
        assert.strictEqual(resultEmpty, null);
        assert.strictEqual(ctxEmpty.stash.order, null);
    });

    it('reads a GetItem result (the item itself, not an items array) into the stash', () => {
        const order = {
            orderId: 'ORDER#campaign-1#uuid-1',
            campaignId: 'CAMPAIGN#campaign-1',
            totalAmount: 45.0,
        };
        const ctx = { stash: {}, result: order };

        const result = response(ctx);

        assert.deepStrictEqual(result, order);
        assert.deepStrictEqual(ctx.stash.order, order);
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
