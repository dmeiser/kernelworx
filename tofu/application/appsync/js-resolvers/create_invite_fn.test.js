import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './create_invite_fn.js';

describe('create_invite_fn request', () => {
    const originalAutoId = util.autoId;
    let autoIdCalls;
    beforeEach(() => {
        autoIdCalls = 0;
        util.autoId = () => {
            autoIdCalls += 1;
            return autoIdCalls === 1
                ? 'c73bcdcc-2669-4bf6-81d3-e4ae73fb11fd'
                : '9f1c2ab3-7e54-4d8f-9a3b-1c2d3e4f5a6b';
        };
    });
    afterEach(() => {
        util.autoId = originalAutoId;
    });

    it('builds PutItem request with normalized values', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    expiresInDays: 7,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.attributeValues.profileId, 'PROFILE#p1');
        assert.strictEqual(result.attributeValues.ownerAccountId, 'ACCOUNT#owner1');
        assert.deepStrictEqual(result.attributeValues.permissions, ['READ']);
        assert.strictEqual(result.attributeValues.createdBy, 'owner1');
        assert.strictEqual(result.attributeValues.used, false);
        assert.strictEqual(result.attributeValues.inviteCode.length, 16);
        assert.strictEqual(result.attributeValues.inviteCode, result.attributeValues.inviteCode.toUpperCase());
        assert.match(result.attributeValues.inviteCode, /^[A-Z0-9]{16}$/);
        assert.strictEqual(autoIdCalls, 2);
        assert.strictEqual(result.attributeValues.inviteCode, 'C73BCDCC26699F1C');
        assert.strictEqual(result.attributeValues.expiresAt, 1704672000);
        assert.strictEqual(result.condition.expression, 'attribute_not_exists(inviteCode)');
        assert.strictEqual(ctx.stash.inviteCode, result.attributeValues.inviteCode);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#p1');
        assert.deepStrictEqual(ctx.stash.permissions, ['READ']);
        assert.strictEqual(ctx.stash.expiresAtISO, '2024-01-08T00:00:00.000Z');
    });

    it('accepts WRITE as the only permission', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['WRITE'],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.attributeValues.permissions, ['WRITE']);
    });

    it('rejects empty permissions array', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: [],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('rejects permissions array with no supported permission', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['ADMIN', 'DELETE'],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('rejects mixed valid and garbage permissions (#449)', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ', 'ADMIN'],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('rejects garbage permission alongside valid non-string value (#449)', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['WRITE', 42],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('rejects non-array permissions', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: 'READ',
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('rejects missing permissions', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: permissions must contain only supported permissions \(READ or WRITE\)/
        );
    });

    it('accepts the maximum expiry of 14 days', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    expiresInDays: 14,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.attributeValues.expiresAt, 1705276800);
    });

    it('defaults to 14 days when expiresInDays is omitted', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.attributeValues.expiresAt, 1705276800);
    });

    it('rejects an expiry over 14 days', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    expiresInDays: 15,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/
        );
    });

    it('rejects a zero or negative expiry', () => {
        const base = {
            stash: { profile: { ownerAccountId: 'ACCOUNT#owner1' } },
            identity: { sub: 'owner1' },
        };

        for (const expiresInDays of [0, -1]) {
            assert.throws(
                () => request({
                    ...base,
                    args: { input: { profileId: 'PROFILE#p1', permissions: ['READ'], expiresInDays } },
                }),
                /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/
            );
        }
    });

    it('rejects a fractional expiry', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    expiresInDays: 1.5,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/
        );
    });

    it('rejects a non-numeric expiry', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    expiresInDays: '7',
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/
        );
    });

    it('accepts lowercase read permission', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['read'],
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.attributeValues.permissions, ['read']);
    });
});

describe('create_invite_fn response', () => {
    it('returns invite data from stash', () => {
        const ctx = {
            stash: {
                inviteCode: 'ABC123',
                profileId: 'PROFILE#p1',
                permissions: ['READ'],
                createdBy: 'owner1',
                createdAt: '2024-01-01T00:00:00Z',
                expiresAtISO: '2024-01-08T00:00:00Z',
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.inviteCode, 'ABC123');
        assert.strictEqual(result.profileId, 'PROFILE#p1');
        assert.deepStrictEqual(result.permissions, ['READ']);
        assert.strictEqual(result.createdByAccountId, 'owner1');
        assert.strictEqual(result.createdAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(result.expiresAt, '2024-01-08T00:00:00Z');
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
