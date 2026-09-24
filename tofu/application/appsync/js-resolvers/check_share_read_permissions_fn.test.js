import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_share_read_permissions_fn.js';

describe('check_share_read_permissions_fn request', () => {
    it('issues a no-op read when already authorized upstream', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { authorized: true, profileId: 'PROFILE#prof-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'NOOP', targetAccountId: 'NOOP' });
    });

    it('queries the shares table with prefixed profileId and targetAccountId', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profileId: 'prof-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123'
        });
    });
});

describe('check_share_read_permissions_fn response', () => {
    it('passes through when already authorized upstream (owner)', () => {
        const ctx = { stash: { authorized: true } };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
    });

    it('throws when ctx.error is present', () => {
        const ctx = { stash: {}, error: { message: 'DynamoDB error', type: 'DynamoDBException' } };

        assert.throws(() => response(ctx), /DynamoDBException: DynamoDB error/);
    });

    it('denies when no share is found', () => {
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' } },
            result: null
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.authorized, false);
    });

    it('authorizes a share with READ permission when share owner matches the profile owner', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ']
        };
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.authorized, true);
        assert.deepStrictEqual(ctx.stash.share, share);
    });

    it('denies a STALE share whose ownerAccountId no longer matches the profile owner (#432)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['READ']
        };
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#new-owner' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.authorized, false);
    });

    it('still authorizes a stale-owner share when the profile owner is unknown (defensive skip)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('accepts a legacy share without ownerAccountId when permissions allow (backward compat)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#new-owner' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('denies a share without any permission', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: []
        };
        const ctx = {
            stash: { profile: { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.authorized, false);
    });
});
