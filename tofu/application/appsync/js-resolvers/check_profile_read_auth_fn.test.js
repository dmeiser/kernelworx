import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_profile_read_auth_fn.js';

const profile = (ownerAccountId) => ({
    profileId: 'PROFILE#prof-1',
    ownerAccountId: ownerAccountId
});

describe('check_profile_read_auth_fn request', () => {
    it('short-circuits with a no-op read when caller is the profile owner', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            stash: { profile: profile('ACCOUNT#owner-1') }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: { S: 'NOOP' },
            targetAccountId: { S: 'NOOP' }
        });
        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('queries the shares table when caller is not the owner', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profile: profile('ACCOUNT#owner-1') }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: { S: 'PROFILE#prof-1' },
            targetAccountId: { S: 'ACCOUNT#user-123' }
        });
        assert.strictEqual(ctx.stash.authorized, false);
    });

    it('throws when profile is missing from stash', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: {}
        };

        assert.throws(() => request(ctx), /INTERNAL_ERROR: Profile not found in stash/);
    });
});

describe('check_profile_read_auth_fn response', () => {
    it('returns the profile with full permissions when caller is owner', () => {
        const stashedProfile = profile('ACCOUNT#owner-1');
        const ctx = {
            stash: { authorized: true, profile: stashedProfile }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, stashedProfile);
        assert.strictEqual(result.isOwner, true);
        assert.deepStrictEqual(result.permissions, ['READ', 'WRITE']);
    });

    it('throws when ctx.error is present', () => {
        const ctx = {
            stash: { profile: profile('ACCOUNT#owner-1') },
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        assert.throws(() => response(ctx), /DynamoDBException: DynamoDB error/);
    });

    it('denies when no share is found', () => {
        const ctx = {
            stash: { profile: profile('ACCOUNT#owner-1') },
            result: null
        };

        assert.throws(() => response(ctx), /UNAUTHORIZED: Not authorized to access this profile/);
    });

    it('returns the profile with share permissions when share owner matches the profile owner', () => {
        const stashedProfile = profile('ACCOUNT#owner-1');
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ']
        };
        const ctx = {
            stash: { profile: stashedProfile },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, stashedProfile);
        assert.strictEqual(result.isOwner, false);
        assert.deepStrictEqual(result.permissions, ['READ']);
    });

    it('denies a STALE share whose ownerAccountId no longer matches the profile owner (#432)', () => {
        const stashedProfile = profile('ACCOUNT#new-owner');
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['READ']
        };
        const ctx = {
            stash: { profile: stashedProfile },
            result: share
        };

        assert.throws(
            () => response(ctx),
            /UNAUTHORIZED: Not authorized to access this profile/
        );
    });

    it('accepts a legacy share without ownerAccountId when permissions allow (backward compat)', () => {
        const stashedProfile = profile('ACCOUNT#new-owner');
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: { profile: stashedProfile },
            result: share
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, stashedProfile);
        assert.strictEqual(result.isOwner, false);
        assert.deepStrictEqual(result.permissions, ['WRITE']);
    });

    it('denies a share without any permission', () => {
        const stashedProfile = profile('ACCOUNT#owner-1');
        const share = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: []
        };
        const ctx = {
            stash: { profile: stashedProfile },
            result: share
        };

        assert.throws(() => response(ctx), /UNAUTHORIZED: Not authorized to access this profile/);
    });
});
