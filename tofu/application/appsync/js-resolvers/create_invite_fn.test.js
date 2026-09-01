import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './create_invite_fn.js';

describe('create_invite_fn request', () => {
    it('rejects empty permissions array', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#prof-1',
                    permissions: [],
                },
            },
            identity: { sub: 'user-123' },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-1' },
            },
        };

        let capturedError = null;
        const originalError = util.error;
        util.error = (message, type) => {
            capturedError = { message, type };
            throw new Error(message);
        };
        try {
            request(ctx);
        } catch (_err) {
            // expected
        } finally {
            util.error = originalError;
        }

        assert.ok(capturedError);
        assert.match(capturedError.message, /permissions must include at least one permission/i);
        assert.strictEqual(capturedError.type, 'BadRequest');
    });

    it('rejects missing permissions', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#prof-1',
                },
            },
            identity: { sub: 'user-123' },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-1' },
            },
        };

        let capturedError = null;
        const originalError = util.error;
        util.error = (message, type) => {
            capturedError = { message, type };
            throw new Error(message);
        };
        try {
            request(ctx);
        } catch (_err) {
            // expected
        } finally {
            util.error = originalError;
        }

        assert.ok(capturedError);
        assert.match(capturedError.message, /permissions must include at least one permission/i);
        assert.strictEqual(capturedError.type, 'BadRequest');
    });

    it('creates invite when permissions are non-empty', () => {
        const originalNowEpochSeconds = util.time.nowEpochSeconds;
        const originalNowISO8601 = util.time.nowISO8601;
        const originalEpochMilliSecondsToISO8601 = util.time.epochMilliSecondsToISO8601;
        util.time.nowEpochSeconds = () => 1704067200;
        util.time.nowISO8601 = () => '2024-01-01T00:00:00Z';
        util.time.epochMilliSecondsToISO8601 = () => '2024-01-15T00:00:00Z';
        try {
            const ctx = {
                args: {
                    input: {
                        profileId: 'PROFILE#prof-1',
                        permissions: ['READ'],
                    },
                },
                identity: { sub: 'user-123' },
                stash: {
                    profile: { ownerAccountId: 'ACCOUNT#owner-1' },
                },
            };

            const result = request(ctx);

            assert.strictEqual(result.operation, 'PutItem');
            assert.deepStrictEqual(result.attributeValues.permissions, ['READ']);
            assert.deepStrictEqual(ctx.stash.permissions, ['READ']);
        } finally {
            util.time.nowEpochSeconds = originalNowEpochSeconds;
            util.time.nowISO8601 = originalNowISO8601;
            util.time.epochMilliSecondsToISO8601 = originalEpochMilliSecondsToISO8601;
        }
    });
});

describe('create_invite_fn response', () => {
    it('returns invite data from stash', () => {
        const ctx = {
            stash: {
                inviteCode: 'ABC123',
                profileId: 'PROFILE#prof-1',
                permissions: ['READ'],
                createdBy: 'user-123',
                createdAt: '2024-01-01T00:00:00Z',
                expiresAtISO: '2024-01-15T00:00:00Z',
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.inviteCode, 'ABC123');
        assert.deepStrictEqual(result.permissions, ['READ']);
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
