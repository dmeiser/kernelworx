import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_invite_owner_current_fn.js';

describe('verify_invite_owner_current_fn request', () => {
    it('builds a base-table GetItem under the invite owner and profile id', () => {
        const ctx = {
            stash: {
                invite: {
                    inviteCode: 'ABC123',
                    profileId: 'PROFILE#p1',
                    ownerAccountId: 'ACCOUNT#owner1',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#owner1',
            profileId: 'PROFILE#p1',
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('normalizes a profile id missing the PROFILE# prefix', () => {
        const ctx = {
            stash: {
                invite: {
                    inviteCode: 'ABC123',
                    profileId: 'p1',
                    ownerAccountId: 'ACCOUNT#owner1',
                },
            },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#owner1',
            profileId: 'PROFILE#p1',
        });
    });
});

describe('verify_invite_owner_current_fn response', () => {
    it('stashes the profile when the owner still matches', () => {
        const ctx = {
            result: {
                ownerAccountId: 'ACCOUNT#owner1',
                profileId: 'PROFILE#p1',
            },
            stash: {},
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, ctx.result);
        assert.deepStrictEqual(ctx.stash.profile, ctx.result);
    });

    it('rejects when the profile moved to a new owner (#453)', () => {
        const ctx = {
            result: null,
            stash: {},
        };

        assert.throws(
            () => response(ctx),
            /ConflictException: Invite is no longer valid: profile ownership has changed/
        );
    });

    it('propagates errors', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:InternalServerError',
                message: 'Service unavailable',
            },
            stash: {},
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: Service unavailable/
        );
    });
});
