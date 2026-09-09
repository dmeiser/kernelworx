import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_my_shares_fn.js';

describe('query_my_shares_fn request', () => {
    it('queries the targetAccountId-index GSI with prefixed caller sub', () => {
        const ctx = { identity: { sub: 'user-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'targetAccountId-index');
        assert.strictEqual(result.query.expression, 'targetAccountId = :targetAccountId');
        assert.deepStrictEqual(result.query.expressionValues, { ':targetAccountId': 'ACCOUNT#user-123' });
    });

    it('does not double-prefix an already-prefixed sub', () => {
        const ctx = { identity: { sub: 'ACCOUNT#user-123' } };

        const result = request(ctx);

        assert.deepStrictEqual(result.query.expressionValues, { ':targetAccountId': 'ACCOUNT#user-123' });
    });

    it('handles a missing identity gracefully', () => {
        const ctx = {};

        const result = request(ctx);

        assert.deepStrictEqual(result.query.expressionValues, { ':targetAccountId': 'ACCOUNT#' });
    });
});

describe('query_my_shares_fn response', () => {
    function runResponse(items, sub = 'user-123') {
        const ctx = { identity: { sub }, stash: {}, result: { items } };
        const result = response(ctx);
        return { result, stash: ctx.stash };
    }

    it('deduplicates by profileId and stashes shares in query order', () => {
        const items = [
            { profileId: 'PROFILE#p1', targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-1', permissions: ['READ'] },
            { profileId: 'PROFILE#p2', targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-2', permissions: ['WRITE'] },
            { profileId: 'PROFILE#p1', targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-9', permissions: ['READ', 'WRITE'] },
        ];

        const { result, stash } = runResponse(items);

        assert.deepStrictEqual(result, { count: 2 });
        assert.deepStrictEqual(stash.sharedProfileIds, ['PROFILE#p1', 'PROFILE#p2']);
        // First share per profileId wins
        assert.deepStrictEqual(stash.sharesByProfile['PROFILE#p1'], {
            profileId: 'PROFILE#p1',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ'],
        });
    });

    it('skips shares missing profileId or ownerAccountId', () => {
        const items = [
            { targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-1', permissions: ['READ'] },
            { profileId: 'PROFILE#p1', targetAccountId: 'ACCOUNT#user-123', permissions: ['READ'] },
            { profileId: 42, targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-1', permissions: ['READ'] },
            { profileId: 'PROFILE#p2', targetAccountId: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#owner-2', permissions: ['READ'] },
        ];

        const { result, stash } = runResponse(items);

        assert.deepStrictEqual(result, { count: 1 });
        assert.deepStrictEqual(stash.sharedProfileIds, ['PROFILE#p2']);
    });

    it('filters legacy shares with no accessible permissions (#242)', () => {
        const items = [
            { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1', permissions: [] },
            { profileId: 'PROFILE#p2', ownerAccountId: 'ACCOUNT#owner-2' },
            { profileId: 'PROFILE#p3', ownerAccountId: 'ACCOUNT#owner-3', permissions: ['ADMIN'] },
            { profileId: 'PROFILE#p4', ownerAccountId: 'ACCOUNT#owner-4', permissions: ['read'] },
            { profileId: 'PROFILE#p5', ownerAccountId: 'ACCOUNT#owner-5', permissions: ['DELETE', 'WRITE'] },
        ];

        const { result, stash } = runResponse(items);

        assert.deepStrictEqual(result, { count: 2 });
        assert.deepStrictEqual(stash.sharedProfileIds, ['PROFILE#p4', 'PROFILE#p5']);
        // Original permissions array passes through untouched (case preserved)
        assert.deepStrictEqual(stash.sharesByProfile['PROFILE#p4'].permissions, ['read']);
    });

    it('returns an empty stash when there are no shares', () => {
        const { result, stash } = runResponse([]);

        assert.deepStrictEqual(result, { count: 0 });
        assert.deepStrictEqual(stash.sharedProfileIds, []);
        assert.deepStrictEqual(stash.sharesByProfile, {});
    });

    it('handles a null result', () => {
        const ctx = { identity: { sub: 'user-123' }, stash: {}, result: null };

        const result = response(ctx);

        assert.deepStrictEqual(result, { count: 0 });
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'DynamoDB error', type: 'InternalServerError' },
            stash: {},
        };

        assert.throws(() => response(ctx), /InternalServerError: DynamoDB error/);
    });
});
