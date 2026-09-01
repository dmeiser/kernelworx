import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_profile_invite_fn.js';

describe('delete_profile_invite_fn request', () => {
    it('constructs GetItem with normalized profileId and ownerAccountId and updates stash', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            args: { profileId: 'prof-456', inviteCode: 'INV-789' },
            stash: {}
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });

    it('preserves already-prefixed profileId and ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-123' },
            args: { profileId: 'PROFILE#prof-456', inviteCode: 'INV-789' },
            stash: {}
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });
});

describe('delete_profile_invite_fn response', () => {
    it('stashes inviteCode, sets authorized to true, and returns true when profile exists', () => {
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123' };
        const ctx = {
            args: { profileId: 'PROFILE#prof-456', inviteCode: 'INV-789' },
            stash: {},
            result: profile
        };

        const result = response(ctx);

        assert.strictEqual(result, true);
        assert.strictEqual(ctx.stash.inviteCode, 'INV-789');
        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('throws Unauthorized when profile is not found', () => {
        const ctx = {
            args: { profileId: 'PROFILE#prof-456', inviteCode: 'INV-789' },
            stash: {},
            result: null
        };

        assert.throws(
            () => response(ctx),
            /Unauthorized: Forbidden: Only profile owner can delete invites/
        );
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            args: { profileId: 'PROFILE#prof-456', inviteCode: 'INV-789' },
            stash: {},
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB error/
        );
    });
});
