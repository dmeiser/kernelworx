import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_invite_fn.js';

describe('create_invite_fn request', () => {
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
        assert.strictEqual(result.attributeValues.inviteCode.length, 10);
        assert.strictEqual(result.attributeValues.inviteCode, result.attributeValues.inviteCode.toUpperCase());
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
            /InvalidInput: permissions must contain at least one supported permission \(READ or WRITE\)/
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
            /InvalidInput: permissions must contain at least one supported permission \(READ or WRITE\)/
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
            /InvalidInput: permissions must contain at least one supported permission \(READ or WRITE\)/
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
            /InvalidInput: permissions must contain at least one supported permission \(READ or WRITE\)/
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
