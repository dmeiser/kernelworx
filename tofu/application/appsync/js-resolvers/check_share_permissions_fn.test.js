import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_share_permissions_fn.js';

describe('check_share_permissions_fn request', () => {
    it('skips share check and returns NOOP when caller is owner', () => {
        const ctx = {
            stash: { isOwner: true },
            args: { input: { profileId: 'prof-1' } },
            identity: { sub: 'user-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP'
        });
    });

    it('skips share check and returns NOOP when skipAuth is true', () => {
        const ctx = {
            stash: { skipAuth: true },
            args: { input: { profileId: 'prof-1' } },
            identity: { sub: 'user-1' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP'
        });
    });

    it('extracts profileId from args.input.profileId and prefixes if needed', () => {
        const ctx = {
            stash: {},
            args: { input: { profileId: 'prof-123' } },
            identity: { sub: 'user-456' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-123',
            targetAccountId: 'ACCOUNT#user-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('extracts profileId from stash.order.profileId', () => {
        const ctx = {
            stash: { order: { profileId: 'PROFILE#prof-from-order' } },
            args: {},
            identity: { sub: 'ACCOUNT#user-456' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-from-order',
            targetAccountId: 'ACCOUNT#user-456'
        });
    });

    it('extracts profileId from stash.campaign.profileId', () => {
        const ctx = {
            stash: { campaign: { profileId: 'prof-from-camp' } },
            args: {},
            identity: { sub: 'user-456' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-from-camp',
            targetAccountId: 'ACCOUNT#user-456'
        });
    });

    it('throws INVALID_INPUT when profileId cannot be found', () => {
        const ctx = {
            stash: {},
            args: {},
            identity: { sub: 'user-456' }
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Profile ID not found for share check/
        );
    });
});

describe('check_share_permissions_fn response', () => {
    it('returns authorized when isOwner is true', () => {
        const ctx = {
            stash: { isOwner: true }
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, { authorized: true });
    });

    it('returns authorized when skipAuth is true', () => {
        const ctx = {
            stash: { skipAuth: true }
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, { authorized: true });
    });

    it('propagates ctx.error when present', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB failure', type: 'DynamoDBException' }
        };

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB failure/
        );
    });

    it('throws FORBIDDEN when share is not found or missing profileId', () => {
        const ctx = {
            stash: {},
            result: null
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action \(no share found\)/
        );
    });

    it('throws FORBIDDEN when share permissions is not an array', () => {
        const ctx = {
            stash: {},
            result: { profileId: 'PROFILE#123', permissions: 'WRITE' }
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Share exists but permissions are invalid/
        );
    });

    it('authorizes and stashes share when caller has WRITE permission and owner matches', () => {
        const share = {
            profileId: 'PROFILE#123',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-1' }
            },
            result: share
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, { authorized: true });
        assert.deepStrictEqual(ctx.stash.share, share);
    });

    it('throws FORBIDDEN when share ownerAccountId does not match profile ownerAccountId', () => {
        const share = {
            profileId: 'PROFILE#123',
            ownerAccountId: 'ACCOUNT#old-owner',
            permissions: ['WRITE']
        };
        const ctx = {
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#new-owner' }
            },
            result: share
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action \(share is no longer valid\)/
        );
    });

    it('throws FORBIDDEN when share only has READ permission', () => {
        const share = {
            profileId: 'PROFILE#123',
            permissions: ['READ']
        };
        const ctx = {
            stash: {},
            result: share
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action \(share has READ only, permissions: \["READ"\]\)/
        );
    });
});
