import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_order_fn.js';

describe('query_order_fn request', () => {
    it('uses GetItem for new order IDs with embedded campaignId', () => {
        const ctx = {
            args: { orderId: 'ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#campaign-123');
        assert.strictEqual(result.key.orderId, 'ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000');
    });

    it('falls back to GSI Query for legacy order IDs', () => {
        const ctx = {
            args: { orderId: 'ORDER#550e8400-e29b-41d4-a716-446655440000' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
    });

    it('falls back to GSI Query for non-standard order IDs', () => {
        const ctx = {
            args: { orderId: 'ORDER#non-existent-order' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
    });
});

describe('query_order_fn response', () => {
    it('returns GetItem result and stashes profileId', () => {
        const order = { orderId: 'ORDER#campaign-123#uuid', campaignId: 'CAMPAIGN#campaign-123', profileId: 'PROFILE#p1' };
        const ctx = { stash: {}, result: order };

        const result = response(ctx);

        assert.deepStrictEqual(result, order);
        assert.strictEqual(ctx.stash.order, order);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#p1');
    });

    it('returns Query result and stashes profileId', () => {
        const order = { orderId: 'ORDER#legacy', campaignId: 'CAMPAIGN#campaign-123', profileId: 'PROFILE#p1' };
        const ctx = { stash: {}, result: { items: [order] } };

        const result = response(ctx);

        assert.deepStrictEqual(result, order);
        assert.strictEqual(ctx.stash.order, order);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#p1');
    });

    it('returns null and flags orderNotFound when GetItem finds nothing', () => {
        const ctx = { stash: {}, result: null };

        const result = response(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.orderNotFound, true);
    });

    it('returns null and flags orderNotFound when Query finds nothing', () => {
        const ctx = { stash: {}, result: { items: [] } };

        const result = response(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.orderNotFound, true);
    });
});