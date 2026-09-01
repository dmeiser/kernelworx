import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_existing_share_fn.js';

describe('check_existing_share_fn request', () => {
    it('queries shares table with prefixed ACCOUNT# when targetAccountId already has ACCOUNT# prefix', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#prof-1',
                },
            },
            stash: {
                targetAccountId: 'ACCOUNT#user-123',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-1');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#user-123');
        assert.strictEqual(ctx.stash.cleanTargetAccountId, 'user-123');
    });

    it('queries shares table with prefixed ACCOUNT# when targetAccountId is unprefixed', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#prof-1',
                },
            },
            stash: {
                targetAccountId: 'user-123',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-1');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#user-123');
        assert.strictEqual(ctx.stash.cleanTargetAccountId, 'user-123');
    });

    it('normalizes unprefixed profileId to have PROFILE# prefix', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'prof-1',
                },
            },
            stash: {
                targetAccountId: 'ACCOUNT#user-123',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-1');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#user-123');
    });

    it('uses profileId from ctx.stash.invite for redeem invite flow', () => {
        const ctx = {
            args: {
                input: {
                    inviteCode: 'INVITE123',
                },
            },
            stash: {
                invite: {
                    profileId: 'prof-from-invite',
                },
                targetAccountId: 'user-456',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-from-invite');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#user-456');
        assert.strictEqual(ctx.stash.cleanTargetAccountId, 'user-456');
    });

    it('handles undefined targetAccountId and profileId gracefully', () => {
        const ctx = {
            args: {},
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, undefined);
        assert.strictEqual(result.key.targetAccountId, undefined);
        assert.strictEqual(ctx.stash.cleanTargetAccountId, undefined);
    });
});

describe('check_existing_share_fn response', () => {
    it('stashes existing share if profileId is present in result', () => {
        const existingShare = {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['READ'],
        };
        const ctx = {
            stash: {},
            result: existingShare,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, existingShare);
        assert.deepStrictEqual(ctx.stash.existingShare, existingShare);
    });

    it('does not set existingShare in stash if result is null', () => {
        const ctx = {
            stash: {},
            result: null,
        };

        const result = response(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.existingShare, undefined);
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
