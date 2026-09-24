import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_payment_methods_access_fn.js';

describe('check_payment_methods_access_fn request', () => {
    it('stores the profile owner in stash and short-circuits for the owner', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' } }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'NOOP', targetAccountId: 'NOOP' });
        assert.strictEqual(ctx.stash.accessLevel, 'OWNER');
        assert.strictEqual(ctx.stash.canSeeQR, true);
        assert.strictEqual(ctx.stash.ownerAccountId, 'ACCOUNT#owner-1');
    });

    it('queries the shares table for non-owners with prefixed keys', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profile: { profileId: 'prof-1', ownerAccountId: 'ACCOUNT#owner-1' } }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123'
        });
    });

    it('throws NOT_FOUND when profile is missing from stash', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: {}
        };

        assert.throws(() => request(ctx), /NOT_FOUND: Profile not found/);
    });
});

describe('check_payment_methods_access_fn response', () => {
    it('skips the share check when the caller is the owner', () => {
        const ctx = {
            stash: {
                accessLevel: 'OWNER',
                canSeeQR: true,
                profile: { ownerAccountId: 'ACCOUNT#owner-1' }
            }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, {});
        assert.strictEqual(ctx.stash.accessLevel, 'OWNER');
        assert.strictEqual(ctx.stash.canSeeQR, true);
    });

    it('throws when ctx.error is present', () => {
        const ctx = {
            stash: { accessLevel: undefined },
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        assert.throws(() => response(ctx), /DynamoDBException: DynamoDB error/);
    });

    it('denies when no share is found', () => {
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#owner-1' } },
            result: null
        };

        assert.throws(() => response(ctx), /FORBIDDEN: Unauthorized access to profile/);
    });

    it('sets WRITE access level for a share with WRITE when share owner matches the profile owner', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, {});
        assert.strictEqual(ctx.stash.accessLevel, 'WRITE');
        assert.strictEqual(ctx.stash.canSeeQR, true);
    });

    it('denies a STALE share whose ownerAccountId no longer matches the profile owner (#432)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#new-owner' } },
            result: share
        };

        assert.throws(() => response(ctx), /FORBIDDEN: Unauthorized access to profile/);
        assert.strictEqual(ctx.stash.accessLevel, undefined);
        assert.strictEqual(ctx.stash.canSeeQR, undefined);
    });

    it('accepts a legacy share without ownerAccountId when it has WRITE (backward compat)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#new-owner' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, {});
        assert.strictEqual(ctx.stash.accessLevel, 'WRITE');
        assert.strictEqual(ctx.stash.canSeeQR, true);
    });

    it('sets READ access level (no QR codes) for a share with only READ', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ']
        };
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, {});
        assert.strictEqual(ctx.stash.accessLevel, 'READ');
        assert.strictEqual(ctx.stash.canSeeQR, false);
    });

    it('denies a share without any permission', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: []
        };
        const ctx = {
            stash: { accessLevel: undefined, profile: { ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share
        };

        assert.throws(() => response(ctx), /FORBIDDEN: Insufficient permissions/);
    });
});
