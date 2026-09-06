import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_campaign_share_fn.js';

describe('create_campaign_share_fn request', () => {
    const baseCtx = {
        args: {
            input: {
                profileId: 'PROFILE#p-1',
                sharedCampaignCode: 'SHARED-CODE-1',
                shareWithCreator: true,
            },
        },
        stash: {
            profile: {
                profileId: 'PROFILE#p-1',
                ownerAccountId: 'ACCOUNT#owner-sub',
            },
            sharedCampaign: {
                sharedCampaignCode: 'SHARED-CODE-1',
                createdBy: 'ACCOUNT#creator-sub',
            },
        },
        identity: { sub: 'owner-sub' },
    };

    it('creates share item when shareWithCreator is true and creator is not owner', () => {
        const result = request(baseCtx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#p-1');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#creator-sub');
        assert.strictEqual(result.attributeValues.profileId, 'PROFILE#p-1');
        assert.strictEqual(result.attributeValues.targetAccountId, 'ACCOUNT#creator-sub');
        assert.strictEqual(result.attributeValues.ownerAccountId, 'ACCOUNT#owner-sub');
        assert.deepStrictEqual(result.attributeValues.permissions, ['READ']);
        assert.strictEqual(result.attributeValues.createdByAccountId, 'ACCOUNT#owner-sub');
        assert.strictEqual(result.attributeValues.GSI1PK, 'ACCOUNT#creator-sub');
        assert.strictEqual(result.attributeValues.GSI1SK, 'SHARE#auto-generated-id');
        assert.strictEqual(
            result.condition.expression,
            'attribute_not_exists(profileId) AND attribute_not_exists(targetAccountId)'
        );
        assert.strictEqual(baseCtx.stash.skipShare, undefined);
    });

    it('handles createdBy without ACCOUNT# prefix correctly', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'p-1',
                    sharedCampaignCode: 'SHARED-CODE-1',
                    shareWithCreator: true,
                },
            },
            stash: {
                profile: {
                    profileId: 'PROFILE#p-1',
                    ownerAccountId: 'owner-sub',
                },
                sharedCampaign: {
                    sharedCampaignCode: 'SHARED-CODE-1',
                    createdBy: 'raw-creator-sub',
                },
            },
            identity: { sub: 'owner-sub' },
        };

        const result = request(ctx);
        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.targetAccountId, 'ACCOUNT#raw-creator-sub');
        assert.strictEqual(result.attributeValues.ownerAccountId, 'ACCOUNT#owner-sub');
        assert.strictEqual(result.attributeValues.createdByAccountId, 'ACCOUNT#owner-sub');
    });

    it('skips share when sharedCampaignCode is not present', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p-1',
                    shareWithCreator: true,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-sub' },
                sharedCampaign: { createdBy: 'ACCOUNT#creator-sub' },
            },
        };

        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'NOOP');
        assert.strictEqual(ctx.stash.skipShare, true);
    });

    it('skips share when shareWithCreator is false or omitted', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p-1',
                    sharedCampaignCode: 'SHARED-CODE-1',
                    shareWithCreator: false,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-sub' },
                sharedCampaign: { createdBy: 'ACCOUNT#creator-sub' },
            },
        };

        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(ctx.stash.skipShare, true);
    });

    it('skips share when creator is the profile owner', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p-1',
                    sharedCampaignCode: 'SHARED-CODE-1',
                    shareWithCreator: true,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#same-sub' },
                sharedCampaign: { createdBy: 'same-sub' },
            },
        };

        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(ctx.stash.skipShare, true);
    });

    it('skips share when createdBy is empty or missing', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p-1',
                    sharedCampaignCode: 'SHARED-CODE-1',
                    shareWithCreator: true,
                },
            },
            stash: {
                profile: { ownerAccountId: 'ACCOUNT#owner-sub' },
                sharedCampaign: { createdBy: null },
            },
        };

        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(ctx.stash.skipShare, true);
    });
});

describe('create_campaign_share_fn response', () => {
    it('returns null when skipShare is true', () => {
        const ctx = {
            stash: { skipShare: true },
            result: null,
        };

        const result = response(ctx);
        assert.strictEqual(result, null);
    });

    it('silently ignores ConditionalCheckFailedException when share already exists', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'The conditional request failed',
                type: 'DynamoDB:ConditionalCheckFailedException',
            },
        };

        const result = response(ctx);
        assert.strictEqual(result, null);
    });

    it('silently ignores error with ConditionalCheckFailed in message', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'ConditionalCheckFailed: duplicate share',
                type: 'TransactionCanceledException',
            },
        };

        const result = response(ctx);
        assert.strictEqual(result, null);
    });

    it('throws when ctx.error is a different DynamoDB error', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'Provisioned throughput exceeded',
                type: 'DynamoDB:ProvisionedThroughputExceededException',
            },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Provisioned throughput exceeded/
        );
    });

    it('returns result on successful put', () => {
        const shareResult = { profileId: 'PROFILE#p-1', targetAccountId: 'ACCOUNT#creator' };
        const ctx = {
            stash: {},
            result: shareResult,
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, shareResult);
    });
});
