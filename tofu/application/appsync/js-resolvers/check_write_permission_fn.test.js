import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_write_permission_fn.js';

describe('check_write_permission_fn request', () => {
    it('issues a no-op read when caller is owner upstream', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { isOwner: true, profileId: 'PROFILE#prof-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'NOOP', targetAccountId: 'NOOP' });
    });

    it('queries the shares table with the prefixed profileId and caller sub', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profileId: 'PROFILE#prof-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123'
        });
    });

    it('skips when profileId is unset (skipGetItem path)', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { skipGetItem: true }
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { profileId: 'NOOP', targetAccountId: 'NOOP' });
    });
});

describe('check_write_permission_fn response', () => {
    it('grants write permission when caller is owner upstream', () => {
        const ctx = { stash: { isOwner: true } };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.hasWritePermission, true);
    });

    it('throws when ctx.error is present', () => {
        const ctx = { stash: {}, error: { message: 'DynamoDB error', type: 'DynamoDBException' } };

        assert.throws(() => response(ctx), /DynamoDBException: DynamoDB error/);
    });

    it('denies when no share is found', () => {
        const ctx = {
            stash: { profileOwner: 'ACCOUNT#owner-1' },
            result: null
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.hasWritePermission, false);
    });

    it('grants write permission for a share with WRITE when share owner matches the profile owner', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profileOwner: 'ACCOUNT#owner-1' },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.hasWritePermission, true);
    });

    it('denies a STALE share whose ownerAccountId no longer matches the profile owner (#432)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profileOwner: 'ACCOUNT#new-owner' },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.hasWritePermission, false);
    });

    it('accepts a legacy share without ownerAccountId when it has WRITE (backward compat)', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profileOwner: 'ACCOUNT#new-owner' },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.hasWritePermission, true);
    });

    it('denies a share that only has READ permission', () => {
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ']
        };
        const ctx = {
            stash: { profileOwner: 'ACCOUNT#owner-1' },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.hasWritePermission, false);
    });
});
