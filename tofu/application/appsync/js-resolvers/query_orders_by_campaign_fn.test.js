import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_orders_by_campaign_fn.js';

describe('query_orders_by_campaign_fn request', () => {
    it('queries orders by campaignId without pagination args', () => {
        const ctx = {
            stash: { authorized: true },
            args: { campaignId: 'CAMPAIGN#c1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.strictEqual(result.limit, undefined);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('passes limit and nextToken through to the DynamoDB query', () => {
        const ctx = {
            stash: { authorized: true },
            args: { campaignId: 'CAMPAIGN#c1', limit: 25, nextToken: 'tok-1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.limit, 25);
        assert.strictEqual(result.nextToken, 'tok-1');
    });

    it('returns a non-existent-campaign query when not authorized', () => {
        const ctx = { stash: {}, args: { campaignId: 'CAMPAIGN#c1' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'NONEXISTENT');
        assert.strictEqual(result.limit, undefined);
    });
});

describe('query_orders_by_campaign_fn response', () => {
    it('wraps orders and nextToken', () => {
        const ctx = {
            stash: {},
            result: { items: [{ orderId: 'o1' }], nextToken: 'tok-1' },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { orders: [{ orderId: 'o1' }], nextToken: 'tok-1' });
    });

    it('returns empty orders and null nextToken when no items', () => {
        const ctx = { stash: {}, result: {} };

        const result = response(ctx);

        assert.deepStrictEqual(result, { orders: [], nextToken: null });
    });
});
