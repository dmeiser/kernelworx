import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_shared_campaign_fn.js';

describe('lookup_shared_campaign_fn request', () => {
    it('builds GetItem request when sharedCampaignCode is provided', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'TROOP123-COOK-CA-25-ABCDEF',
                },
            },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.sharedCampaignCode, 'TROOP123-COOK-CA-25-ABCDEF');
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(ctx.stash.skipSharedCampaign, undefined);
    });

    it('trims whitespace from sharedCampaignCode', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: '  TROOP123-COOK-CA-25-ABCDEF  ',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.key.sharedCampaignCode, 'TROOP123-COOK-CA-25-ABCDEF');
    });

    it('returns NOOP GetItem and sets skipSharedCampaign when code is omitted', () => {
        const ctx = {
            args: {
                input: {
                    campaignName: 'Test',
                },
            },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.sharedCampaignCode, 'NOOP');
        assert.strictEqual(ctx.stash.skipSharedCampaign, true);
    });

    it('returns NOOP GetItem when code is empty string', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: '   ',
                },
            },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.sharedCampaignCode, 'NOOP');
        assert.strictEqual(ctx.stash.skipSharedCampaign, true);
    });
});

describe('lookup_shared_campaign_fn response', () => {
    it('returns null when skipSharedCampaign is set', () => {
        const ctx = {
            stash: { skipSharedCampaign: true },
            result: null,
        };

        const result = response(ctx);
        assert.strictEqual(result, null);
    });

    it('throws when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB error', type: 'DynamoDB:InternalServerError' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: DynamoDB error/
        );
    });

    it('throws NOT_FOUND when shared campaign item is not found', () => {
        const ctx = {
            args: { input: { sharedCampaignCode: 'INVALID-CODE' } },
            stash: {},
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Shared Campaign INVALID-CODE not found/
        );
    });

    it('throws NOT_FOUND when shared campaign item has no sharedCampaignCode', () => {
        const ctx = {
            args: { input: { sharedCampaignCode: 'EMPTY-ITEM' } },
            stash: {},
            result: {},
        };

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Shared Campaign EMPTY-ITEM not found/
        );
    });

    it('throws INVALID_INPUT when shared campaign is inactive', () => {
        const ctx = {
            args: { input: { sharedCampaignCode: 'INACTIVE-CODE' } },
            stash: {},
            result: {
                sharedCampaignCode: 'INACTIVE-CODE',
                isActive: false,
            },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign INACTIVE-CODE is no longer active/
        );
    });

    it('stashes and returns shared campaign when active', () => {
        const sharedItem = {
            sharedCampaignCode: 'ACTIVE-CODE',
            campaignName: 'Cookie Campaign',
            campaignYear: 2025,
            catalogId: 'CATALOG#cat-1',
            unitType: 'Pack',
            unitNumber: 100,
            city: 'Springfield',
            state: 'IL',
            isActive: true,
            createdBy: 'ACCOUNT#creator-1',
        };

        const ctx = {
            args: { input: { sharedCampaignCode: 'ACTIVE-CODE' } },
            stash: {},
            result: sharedItem,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, sharedItem);
        assert.deepStrictEqual(ctx.stash.sharedCampaign, sharedItem);
    });
});
