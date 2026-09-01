import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_profile_for_update_fn.js';

describe('lookup_profile_for_update_fn request', () => {
    it('uses GetItem with ownerAccountId and profileId (adding PROFILE# prefix)', () => {
        const ctx = {
            identity: { sub: 'user-uuid-123' },
            args: {
                input: {
                    profileId: 'prof-456',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-uuid-123');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
    });

    it('uses GetItem with ownerAccountId and preserves existing PROFILE# prefix', () => {
        const ctx = {
            identity: { sub: 'user-uuid-123' },
            args: {
                input: {
                    profileId: 'PROFILE#prof-456',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-uuid-123');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
    });
});

describe('lookup_profile_for_update_fn response', () => {
    it('returns profile and stashes it in ctx.stash.profile', () => {
        const profile = {
            ownerAccountId: 'ACCOUNT#user-uuid-123',
            profileId: 'PROFILE#prof-456',
            sellerName: 'John Doe',
        };
        const ctx = {
            stash: {},
            result: profile,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.profile, profile);
    });

    it('throws error when DynamoDB error is present', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'DynamoDB error message',
                type: 'DynamoDB:InternalServerError',
            },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: DynamoDB error message/
        );
    });

    it('throws Forbidden when profile is null (not found or not owner)', () => {
        const ctx = {
            stash: {},
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /Forbidden: Profile not found or access denied/
        );
    });

    it('throws Forbidden when profile is undefined', () => {
        const ctx = {
            stash: {},
            result: undefined,
        };

        assert.throws(
            () => response(ctx),
            /Forbidden: Profile not found or access denied/
        );
    });
});
