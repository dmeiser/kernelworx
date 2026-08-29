import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_profiles_fn.js';

describe('list_my_profiles_fn request', () => {
    it('queries profiles by ownerAccountId without pagination args', () => {
        const ctx = { identity: { sub: 'user-1' }, args: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'ownerAccountId = :accountId');
        assert.strictEqual(result.query.expressionValues[':accountId'].S, 'ACCOUNT#user-1');
        assert.strictEqual(result.limit, undefined);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('passes limit and nextToken through to the DynamoDB query', () => {
        const ctx = { identity: { sub: 'user-1' }, args: { limit: 50, nextToken: 'tok-1' } };

        const result = request(ctx);

        assert.strictEqual(result.limit, 50);
        assert.strictEqual(result.nextToken, 'tok-1');
    });
});

describe('list_my_profiles_fn response', () => {
    it('wraps profiles in a connection and adds owner fields', () => {
        const ctx = {
            stash: {},
            result: {
                items: [{ profileId: 'PROFILE#p1', createdAt: '2024-01-01T00:00:00Z' }],
                nextToken: 'tok-1',
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.nextToken, 'tok-1');
        assert.strictEqual(result.profiles.length, 1);
        assert.strictEqual(result.profiles[0].profileId, 'PROFILE#p1');
        assert.strictEqual(result.profiles[0].isOwner, true);
        assert.deepStrictEqual(result.profiles[0].permissions, ['READ', 'WRITE']);
    });

    it('filters out incomplete records and returns empty profiles', () => {
        const ctx = {
            stash: {},
            result: { items: [{ profileId: 'PROFILE#incomplete' }] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { profiles: [], nextToken: null });
    });
});
