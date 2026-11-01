import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_invite_fn.js';

describe('lookup_invite_fn request', () => {
    it('builds strongly consistent GetItem request on inviteCode', () => {
        const ctx = {
            args: {
                input: {
                    inviteCode: 'INVITE-ABCD-1234',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            inviteCode: 'INVITE-ABCD-1234',
        });
    });
});

describe('lookup_invite_fn response', () => {
    it('throws NOT_FOUND when result is missing or lacks inviteCode', () => {
        assert.throws(
            () => response({ result: null, stash: {}, identity: { sub: 'usr-1' } }),
            /NOT_FOUND: Invalid invite code/
        );

        assert.throws(
            () => response({ result: {}, stash: {}, identity: { sub: 'usr-1' } }),
            /NOT_FOUND: Invalid invite code/
        );
    });

    it('throws ConflictException when invite is already used', () => {
        const ctx = {
            stash: {},
            identity: { sub: 'usr-1' },
            result: {
                inviteCode: 'INVITE-ABCD-1234',
                used: true,
            },
        };

        assert.throws(
            () => response(ctx),
            /ConflictException: Invite code has already been used/
        );
    });

    it('throws ConflictException when invite is expired', () => {
        const ctx = {
            stash: {},
            identity: { sub: 'usr-1' },
            result: {
                inviteCode: 'INVITE-ABCD-1234',
                used: false,
                expiresAt: 1704067100, // Before mock nowEpochSeconds (1704067200)
            },
        };

        assert.throws(
            () => response(ctx),
            /ConflictException: Invite code has expired/
        );
    });

    it('accepts valid invite, stashes invite and normalized targetAccountId', () => {
        const invite = {
            inviteCode: 'INVITE-ABCD-1234',
            profileId: 'PROFILE#p1',
            role: 'VIEWER',
            used: false,
            expiresAt: 1704067300, // After mock nowEpochSeconds
        };
        const ctx = {
            stash: {},
            identity: { sub: 'usr-test-123' },
            result: invite,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, invite);
        assert.deepStrictEqual(ctx.stash.invite, invite);
        assert.strictEqual(ctx.stash.targetAccountId, 'ACCOUNT#usr-test-123');
    });

    it('preserves an already-prefixed caller sub in targetAccountId', () => {
        const invite = {
            inviteCode: 'INVITE-ABCD-1234',
            profileId: 'PROFILE#p1',
            used: false,
        };
        const ctx = {
            stash: {},
            identity: { sub: 'ACCOUNT#prefixed-sub' },
            result: invite,
        };

        response(ctx);

        assert.strictEqual(ctx.stash.targetAccountId, 'ACCOUNT#prefixed-sub');
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'Datastore error',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Datastore error/
        );
    });
});
