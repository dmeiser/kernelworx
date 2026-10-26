import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_campaign_orders_for_delete_fn.js';

describe('query_campaign_orders_for_delete_fn request', () => {
    it('sets skipOrderQuery, empty ordersToDelete, and returns NOOP query when campaign is absent from stash', () => {
        const ctx = {
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipOrderQuery, true);
        assert.deepStrictEqual(ctx.stash.ordersToDelete, []);
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'NOOP',
        });
    });

    it('queries orders by campaignId when campaign exists in stash', () => {
        const ctx = {
            stash: {
                campaign: {
                    campaignId: 'CAMPAIGN#camp-123',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#camp-123',
        });
        assert.strictEqual(ctx.stash.skipOrderQuery, undefined);
    });
});

describe('query_campaign_orders_for_delete_fn response', () => {
    it('returns empty array when skipOrderQuery is set in stash, ignoring errors', () => {
        const ctx = {
            stash: {
                skipOrderQuery: true,
            },
            error: {
                message: 'Should be ignored because skipOrderQuery is set',
                type: 'INTERNAL_ERROR',
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('stashes ordersToDelete and returns orders when query succeeds', () => {
        const orders = [
            { orderId: 'ORDER#c1#o1', campaignId: 'CAMPAIGN#c1' },
            { orderId: 'ORDER#c1#o2', campaignId: 'CAMPAIGN#c1' },
        ];
        const ctx = {
            stash: {},
            result: {
                items: orders,
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, orders);
        assert.deepStrictEqual(ctx.stash.ordersToDelete, orders);
    });

    it('handles missing result items by stashing and returning empty array', () => {
        const ctx = {
            stash: {},
            result: {},
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
        assert.deepStrictEqual(ctx.stash.ordersToDelete, []);
    });

    it('throws propagated error when ctx.error is present and skipOrderQuery is false', () => {
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
