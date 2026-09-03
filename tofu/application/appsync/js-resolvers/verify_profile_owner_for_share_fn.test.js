import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_owner_for_share_fn.js';

describe('verify_profile_owner_for_share_fn request', () => {
    it('constructs GetItem with normalized profileId and ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            args: { input: { profileId: 'prof-456' } },
            stash: {}
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('preserves already-prefixed profileId', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            args: { input: { profileId: 'PROFILE#prof-456' } },
            stash: {}
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });
});

describe('verify_profile_owner_for_share_fn response', () => {
    it('stashes and returns profile when item exists', () => {
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123', name: 'Test' };
        const ctx = {
            stash: {},
            result: profile
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.deepStrictEqual(ctx.stash.profile, profile);
    });

    it('throws Unauthorized when profile is not found', () => {
        const ctx = {
            stash: {},
            result: null
        };

        assert.throws(
            () => response(ctx),
            /Unauthorized: Forbidden: Only profile owner can share profiles/
        );
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB error/
        );
    });
});
