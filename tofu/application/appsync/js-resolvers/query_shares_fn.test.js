import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_shares_fn.js';

describe('query_shares_fn request', () => {
    it('returns empty query for non-existent profileId when caller is not owner and has no write permission', () => {
        const ctx = {
            args: { profileId: 'profile-1' },
            stash: { isOwner: false, hasWritePermission: false },
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'NONEXISTENT',
        });
    });

    it('returns empty query when stash flags are missing or undefined', () => {
        const ctx = {
            args: { profileId: 'profile-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'NONEXISTENT',
        });
    });

    it('queries shares table by normalized profileId when caller is owner', () => {
        const ctx = {
            args: { profileId: 'p-123' },
            stash: { isOwner: true },
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#p-123',
        });
    });

    it('preserves already-prefixed PROFILE# identifier in request', () => {
        const ctx = {
            args: { profileId: 'PROFILE#already-prefixed' },
            stash: { isOwner: true },
        };
        const result = request(ctx);
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#already-prefixed',
        });
    });

    it('queries shares table when caller has write permission but is not owner', () => {
        const ctx = {
            args: { profileId: 'p-456' },
            stash: { isOwner: false, hasWritePermission: true },
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#p-456',
        });
    });
});

describe('query_shares_fn response', () => {
    it('propagates DynamoDB errors', () => {
        const ctx = {
            error: { message: 'Throughput exceeded', type: 'DynamoDB:ProvisionedThroughputExceededException' },
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Throughput exceeded/
        );
    });

    it('strips ACCOUNT# prefix from targetAccountId in result items', () => {
        const ctx = {
            result: {
                items: [
                    {
                        profileId: 'PROFILE#p1',
                        targetAccountId: 'ACCOUNT#user-1',
                        permissions: ['READ'],
                    },
                    {
                        profileId: 'PROFILE#p1',
                        targetAccountId: 'ACCOUNT#user-2',
                        permissions: ['READ', 'WRITE'],
                    },
                ],
            },
        };
        const result = response(ctx);
        assert.deepStrictEqual(result, [
            {
                profileId: 'PROFILE#p1',
                targetAccountId: 'user-1',
                permissions: ['READ'],
            },
            {
                profileId: 'PROFILE#p1',
                targetAccountId: 'user-2',
                permissions: ['READ', 'WRITE'],
            },
        ]);
    });

    it('handles unprefixed targetAccountId in result items', () => {
        const ctx = {
            result: {
                items: [
                    {
                        profileId: 'PROFILE#p1',
                        targetAccountId: 'clean-user-id',
                    },
                ],
            },
        };
        const result = response(ctx);
        assert.strictEqual(result[0].targetAccountId, 'clean-user-id');
    });

    it('returns empty array when items is empty', () => {
        const ctx = {
            result: { items: [] },
        };
        assert.deepStrictEqual(response(ctx), []);
    });

    it('returns empty array when items is absent or result is empty', () => {
        assert.deepStrictEqual(response({ result: {} }), []);
    });
});
