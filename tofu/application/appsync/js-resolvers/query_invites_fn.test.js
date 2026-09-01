import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './query_invites_fn.js';

describe('query_invites_fn request', () => {
    it('returns empty query when caller is not owner', () => {
        const ctx = {
            args: { profileId: 'PROFILE#prof-1' },
            stash: { isOwner: false },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'NOOP');
    });

    it('queries invites by profileId when caller is owner', () => {
        const ctx = {
            args: { profileId: 'prof-1' },
            stash: { isOwner: true },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#prof-1');
    });
});

describe('query_invites_fn response', () => {
    it('filters out expired, used, and empty-permission invites', () => {
        const originalNowEpochSeconds = util.time.nowEpochSeconds;
        const originalEpochMilliSecondsToISO8601 = util.time.epochMilliSecondsToISO8601;
        util.time.nowEpochSeconds = () => 1000;
        util.time.epochMilliSecondsToISO8601 = () => '2024-01-01T00:00:00Z';
        try {
            const ctx = {
                stash: { isOwner: true },
                result: {
                    items: [
                        { inviteCode: 'VALID1', profileId: 'PROFILE#prof-1', permissions: ['READ'], expiresAt: 2000, used: false },
                        { inviteCode: 'EXPIRED', profileId: 'PROFILE#prof-1', permissions: ['READ'], expiresAt: 500, used: false },
                        { inviteCode: 'USED', profileId: 'PROFILE#prof-1', permissions: ['READ'], expiresAt: 2000, used: true },
                        { inviteCode: 'EMPTY', profileId: 'PROFILE#prof-1', permissions: [], expiresAt: 2000, used: false },
                        { inviteCode: 'MISSING', profileId: 'PROFILE#prof-1', expiresAt: 2000, used: false },
                    ],
                },
            };

            const result = response(ctx);

            assert.strictEqual(result.length, 1);
            assert.strictEqual(result[0].inviteCode, 'VALID1');
        } finally {
            util.time.nowEpochSeconds = originalNowEpochSeconds;
            util.time.epochMilliSecondsToISO8601 = originalEpochMilliSecondsToISO8601;
        }
    });

    it('returns empty array when caller is not owner', () => {
        const ctx = {
            stash: { isOwner: false },
            result: { items: [] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
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
