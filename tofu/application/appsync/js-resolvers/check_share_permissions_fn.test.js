import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_share_permissions_fn.js';

describe('check_share_permissions_fn request', () => {
    it('returns noop GetItem when already authorized via isOwner', () => {
        const ctx = {
            stash: { isOwner: true },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP',
        });
    });

    it('returns noop GetItem when skipAuth is set', () => {
        const ctx = {
            stash: { skipAuth: true },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP',
        });
    });

    it('throws INVALID_INPUT when profileId cannot be resolved', () => {
        const ctx = {
            args: {},
            stash: {},
            identity: { sub: 'user-123' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Profile ID not found for share check/
        );
    });

    it('builds share lookup key from input profileId and identity sub', () => {
        const ctx = {
            args: { input: { profileId: 'p123' } },
            stash: {},
            identity: { sub: 'user-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p123',
            targetAccountId: 'ACCOUNT#user-123',
        });
    });

    it('builds share lookup key from stash.order.profileId', () => {
        const ctx = {
            args: {},
            stash: { order: { profileId: 'prof-order' } },
            identity: { sub: 'ACCOUNT#user-123' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-order',
            targetAccountId: 'ACCOUNT#user-123',
        });
    });

    it('builds share lookup key from stash.campaign.profileId', () => {
        const ctx = {
            args: {},
            stash: { campaign: { profileId: 'PROFILE#prof-camp' } },
            identity: { sub: 'user-123' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#prof-camp',
            targetAccountId: 'ACCOUNT#user-123',
        });
    });
});

describe('check_share_permissions_fn response', () => {
    it('returns authorized: true when already authorized via isOwner', () => {
        const ctx = {
            stash: { isOwner: true },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
    });

    it('returns authorized: true when skipAuth is set', () => {
        const ctx = {
            stash: { skipAuth: true },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
    });

    it('propagates ctx.error', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB failure', type: 'DynamoDBException' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB failure/
        );
    });

    it('throws clean FORBIDDEN error without leaking share object when share has READ only', () => {
        const errorLogs = [];
        const originalConsoleError = console.error;
        console.error = (...args) => {
            errorLogs.push(args.join(' '));
        };

        const ctx = {
            stash: {},
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                permissions: ['READ'],
            },
        };

        try {
            assert.throws(
                () => response(ctx),
                (err) => {
                    assert.strictEqual(
                        err.message,
                        'FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action (share has READ only)'
                    );
                    // Must not leak the internal share object shape to the client-facing error
                    assert.ok(!err.message.includes('{'), 'must not contain serialized object');
                    assert.ok(!err.message.includes('['), 'must not contain serialized array');
                    assert.ok(!err.message.includes('permissions:'), 'must not contain permissions dump');
                    assert.ok(!err.message.includes('ownerAccountId'), 'must not contain ownerAccountId');
                    assert.ok(!err.message.includes('profileId'), 'must not contain profileId value');
                    return true;
                }
            );

            // Diagnostic details logged server-side only
            assert.strictEqual(errorLogs.length, 1);
            assert.ok(errorLogs[0].includes('Share permission check failed (READ only)'));
            assert.ok(errorLogs[0].includes('READ'));
        } finally {
            console.error = originalConsoleError;
        }
    });

    it('throws FORBIDDEN when no share is found', () => {
        const ctx = {
            stash: {},
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action \(no share found\)/
        );
    });

    it('throws FORBIDDEN when share permissions field is invalid', () => {
        const ctx = {
            stash: {},
            result: { profileId: 'PROFILE#p1', permissions: 'not-an-array' },
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Share exists but permissions are invalid/
        );
    });

    it('authorizes and stashes share when caller has WRITE permission', () => {
        const share = {
            profileId: 'PROFILE#p1',
            ownerAccountId: 'ACCOUNT#owner-1',
            permissions: ['READ', 'WRITE'],
        };
        const ctx = {
            stash: { profile: { ownerAccountId: 'ACCOUNT#owner-1' } },
            result: share,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.share, share);
    });

    it('rejects stale share when owner has changed', () => {
        const ctx = {
            stash: { profile: { ownerAccountId: 'ACCOUNT#new-owner' } },
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#old-owner',
                permissions: ['WRITE'],
            },
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Forbidden: Only profile owner or users with WRITE permission can perform this action \(share is no longer valid\)/
        );
    });
});
