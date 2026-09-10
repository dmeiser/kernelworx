import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_campaigns_fn.js';

describe('query_campaigns_fn request', () => {
    it('queries campaigns by profileId without pagination args (first page)', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'p1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#p1');
        assert.strictEqual(result.limit, undefined);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('adds the PROFILE# prefix when the argument already carries it', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'PROFILE#p1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#p1');
    });

    it('passes limit and nextToken through to the DynamoDB query (second page)', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'p1', limit: 25, nextToken: 'tok-1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.limit, 25);
        assert.strictEqual(result.nextToken, 'tok-1');
    });

    it('ignores a non-positive limit', () => {
        const ctx = {
            stash: { authorized: true },
            args: { profileId: 'p1', limit: 0 },
        };

        const result = request(ctx);

        assert.strictEqual(result.limit, undefined);
    });

    it('returns a no-op query when not authorized or profile not found', () => {
        const ctx = { stash: {}, args: { profileId: 'p1' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'NOOP');
        assert.strictEqual(result.limit, 1);
    });
});

describe('query_campaigns_fn response', () => {
    it('wraps campaigns and nextToken (first page)', () => {
        const ctx = {
            stash: { authorized: true },
            result: { items: [{ campaignId: 'c1' }], nextToken: 'tok-2' },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, {
            campaigns: [{ campaignId: 'c1', isActive: true }],
            nextToken: 'tok-2',
        });
    });

    it('defaults isActive to true for legacy items without it', () => {
        const ctx = {
            stash: { authorized: true },
            result: { items: [{ campaignId: 'c1' }, { campaignId: 'c2', isActive: false }] },
        };

        const result = response(ctx);

        assert.strictEqual(result.campaigns[0].isActive, true);
        assert.strictEqual(result.campaigns[1].isActive, false);
    });

    it('returns empty campaigns and null nextToken when no items', () => {
        const ctx = { stash: { authorized: true }, result: {} };

        const result = response(ctx);

        assert.deepStrictEqual(result, { campaigns: [], nextToken: null });
    });

    it('returns an empty connection when not authorized', () => {
        const ctx = { stash: {}, result: { items: [{ campaignId: 'c1' }] } };

        const result = response(ctx);

        assert.deepStrictEqual(result, { campaigns: [], nextToken: null });
    });
});
