import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_campaign_pipeline_resolver.js';

describe('create_campaign_pipeline_resolver request', () => {
    it('returns empty object', () => {
        const ctx = { args: {} };
        const result = request(ctx);
        assert.deepStrictEqual(result, {});
    });
});

describe('create_campaign_pipeline_resolver response', () => {
    it('returns createdCampaign from stash', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#123',
            campaignName: 'Test Campaign',
            profileId: 'PROFILE#456',
        };
        const ctx = {
            stash: {
                createdCampaign: campaign,
            },
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, campaign);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            stash: {
                createdCampaign: { campaignId: 'CAMPAIGN#123' },
            },
            error: {
                message: 'Pipeline failed',
                type: 'InternalServerError',
            },
        };

        assert.throws(
            () => response(ctx),
            /InternalServerError: Pipeline failed/
        );
    });
});
