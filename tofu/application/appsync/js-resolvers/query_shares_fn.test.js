import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './query_shares_fn.js';

describe('query_shares_fn request', () => {
    it('returns empty query when caller is not owner and has no write permission', () => {
        const ctx = {
            args: { profileId: 'PROFILE#prof-1' },
            stash: { isOwner: false, hasWritePermission: false },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'NONEXISTENT');
    });

    it('queries shares by profileId when caller is owner', () => {
        const ctx = {
            args: { profileId: 'prof-1' },
            stash: { isOwner: true, hasWritePermission: false },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#prof-1');
    });
});

describe('query_shares_fn response', () => {
    it('filters out shares with empty or non-effective permissions', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-1', permissions: ['READ'] },
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-2', permissions: [] },
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-3', permissions: ['WRITE'] },
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-4', permissions: ['ADMIN'] },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 2);
        assert.ok(result.some(item => item.targetAccountId === 'user-1'));
        assert.ok(result.some(item => item.targetAccountId === 'user-3'));
        assert.ok(!result.some(item => item.targetAccountId === 'user-2'));
        assert.ok(!result.some(item => item.targetAccountId === 'user-4'));
    });

    it('filters out shares with missing permissions', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-1', permissions: ['READ'] },
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-2' },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 1);
        assert.strictEqual(result[0].targetAccountId, 'user-1');
    });

    it('strips ACCOUNT# prefix from targetAccountId', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-1', permissions: ['READ'] },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result[0].targetAccountId, 'user-1');
        assert.strictEqual(result[0].profileId, 'PROFILE#prof-1');
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: {
                message: 'DynamoDB error',
                type: 'InternalServerError',
            },
            stash: {},
        };

        assert.throws(
            () => response(ctx),
            /InternalServerError: DynamoDB error/
        );
    });
});
