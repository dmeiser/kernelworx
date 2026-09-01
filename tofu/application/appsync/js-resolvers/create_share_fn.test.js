import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_share_fn.js';

describe('create_share_fn request', () => {
    it('throws ALREADY_SHARED when existingShare is present in stash', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                },
            },
            stash: {
                targetAccountId: 'ACCOUNT#u1',
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
                existingShare: {
                    profileId: 'PROFILE#p1',
                    targetAccountId: 'ACCOUNT#u1',
                    permissions: ['READ'],
                },
            },
            identity: { sub: 'owner1' },
        };

        assert.throws(
            () => request(ctx),
            /ALREADY_SHARED: This profile is already shared with this user\./
        );
    });

    it('builds PutItem request with conditional check for shareProfileDirect flow', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'p1',
                    permissions: ['READ', 'WRITE'],
                },
            },
            stash: {
                targetAccountId: 'user1',
                profile: { ownerAccountId: 'ACCOUNT#owner1' },
            },
            identity: { sub: 'owner1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p1',
            targetAccountId: 'ACCOUNT#user1',
        });
        assert.deepStrictEqual(result.condition, {
            expression: 'attribute_not_exists(profileId) AND attribute_not_exists(targetAccountId)',
        });
        assert.strictEqual(result.attributeValues.profileId, 'PROFILE#p1');
        assert.strictEqual(result.attributeValues.targetAccountId, 'ACCOUNT#user1');
        assert.strictEqual(result.attributeValues.shareId, 'SHARE#ACCOUNT#user1');
        assert.deepStrictEqual(result.attributeValues.permissions, ['READ', 'WRITE']);
        assert.strictEqual(result.attributeValues.ownerAccountId, 'ACCOUNT#owner1');
        assert.strictEqual(result.attributeValues.createdByAccountId, 'ACCOUNT#owner1');
        assert.ok(result.attributeValues.createdAt);
        assert.deepStrictEqual(ctx.stash.shareItem, result.attributeValues);
    });

    it('builds PutItem request for redeemProfileInvite flow using stash.invite', () => {
        const ctx = {
            args: {
                input: {},
            },
            stash: {
                targetAccountId: 'ACCOUNT#user2',
                invite: {
                    profileId: 'PROFILE#p2',
                    permissions: ['READ'],
                    ownerAccountId: 'ACCOUNT#owner2',
                },
            },
            identity: { sub: 'user2' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p2',
            targetAccountId: 'ACCOUNT#user2',
        });
        assert.deepStrictEqual(result.condition, {
            expression: 'attribute_not_exists(profileId) AND attribute_not_exists(targetAccountId)',
        });
        assert.strictEqual(result.attributeValues.profileId, 'PROFILE#p2');
        assert.strictEqual(result.attributeValues.targetAccountId, 'ACCOUNT#user2');
        assert.deepStrictEqual(result.attributeValues.permissions, ['READ']);
        assert.strictEqual(result.attributeValues.ownerAccountId, 'ACCOUNT#owner2');
        assert.strictEqual(result.attributeValues.createdByAccountId, 'ACCOUNT#user2');
    });

    it('throws error when ownerAccountId cannot be determined', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                },
            },
            stash: {
                targetAccountId: 'ACCOUNT#user1',
            },
            identity: { sub: 'user1' },
        };

        assert.throws(
            () => request(ctx),
            /InternalServerError: Failed to determine profile owner/
        );
    });
});

describe('create_share_fn response', () => {
    it('throws ALREADY_SHARED when DynamoDB ConditionalCheckFailedException occurs', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed',
            },
            stash: {},
        };

        assert.throws(
            () => response(ctx),
            /ALREADY_SHARED: This profile is already shared with this user\./
        );
    });

    it('throws ALREADY_SHARED when error message contains ConditionalCheckFailed', () => {
        const ctx = {
            error: {
                type: 'DynamoDB',
                message: 'ConditionalCheckFailed: item already exists',
            },
            stash: {},
        };

        assert.throws(
            () => response(ctx),
            /ALREADY_SHARED: This profile is already shared with this user\./
        );
    });

    it('propagates other errors unchanged', () => {
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

    it('returns share item with targetAccountId stripped of ACCOUNT# prefix', () => {
        const ctx = {
            stash: {
                shareItem: {
                    profileId: 'PROFILE#p1',
                    targetAccountId: 'ACCOUNT#user123',
                    shareId: 'SHARE#ACCOUNT#user123',
                    permissions: ['READ'],
                    ownerAccountId: 'ACCOUNT#owner1',
                    createdByAccountId: 'ACCOUNT#owner1',
                    createdAt: '2024-01-01T00:00:00Z',
                },
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.targetAccountId, 'user123');
        assert.strictEqual(result.profileId, 'PROFILE#p1');
        assert.strictEqual(result.shareId, 'SHARE#ACCOUNT#user123');
        assert.deepStrictEqual(result.permissions, ['READ']);
    });

    it('handles targetAccountId without ACCOUNT# prefix correctly', () => {
        const ctx = {
            stash: {
                shareItem: {
                    profileId: 'PROFILE#p1',
                    targetAccountId: 'user123',
                    shareId: 'SHARE#ACCOUNT#user123',
                    permissions: ['READ'],
                },
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.targetAccountId, 'user123');
    });
});
