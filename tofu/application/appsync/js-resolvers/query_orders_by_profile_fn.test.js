import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_orders_by_profile_fn.js';

describe('query_orders_by_profile_fn request', () => {
    it('queries orders by profileId via the GSI without pagination args', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'p1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#p1');
        assert.strictEqual(result.limit, undefined);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('passes limit and nextToken through to the DynamoDB query', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'PROFILE#p1', limit: 10, nextToken: 'tok-2' },
        };

        const result = request(ctx);

        assert.strictEqual(result.limit, 10);
        assert.strictEqual(result.nextToken, 'tok-2');
    });

    it('returns a non-existent-profile query when not authorized', () => {
        const ctx = { stash: {}, args: { profileId: 'p1' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'NONEXISTENT');
        assert.strictEqual(result.limit, undefined);
    });
});

describe('query_orders_by_profile_fn response', () => {
    it('wraps orders and nextToken', () => {
        const ctx = {
            stash: {},
            result: { items: [{ orderId: 'o1' }], nextToken: 'tok-2' },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { orders: [{ orderId: 'o1' }], nextToken: 'tok-2' });
    });

    it('returns empty orders and null nextToken when no items', () => {
        const ctx = { stash: {}, result: {} };

        const result = response(ctx);

        assert.deepStrictEqual(result, { orders: [], nextToken: null });
    });
});
