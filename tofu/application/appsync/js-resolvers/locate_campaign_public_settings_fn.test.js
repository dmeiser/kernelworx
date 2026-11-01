import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './locate_campaign_public_settings_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the locator step that both campaign-level
// settings pipelines run first. The Campaigns base table is keyed
// {profileId, campaignId}, so a campaignId alone cannot address the row; this
// step reads the campaignId-index GSI purely to learn the partition key, and
// hands the located item to the write-access pair through ctx.stash.campaign.

function ctxFor(args) {
    return { stash: {}, args, identity: { sub: 'ACCOUNT#owner-1' } };
}

describe('locate_campaign_public_settings_fn request', () => {
    it('queries campaignId-index for a top-level campaignId argument', () => {
        const result = request(ctxFor({ campaignId: 'CAMPAIGN#c1' }));

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.deepStrictEqual(result.query, {
            expression: 'campaignId = :campaignId',
            expressionValues: { ':campaignId': 'CAMPAIGN#c1' }
        });
        assert.strictEqual(result.limit, 1);
    });

    it('resolves the campaignId from the settings mutation input object', () => {
        const result = request(ctxFor({ input: { campaignId: 'CAMPAIGN#c2', enabled: true } }));

        assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'CAMPAIGN#c2' });
    });

    it('normalizes a bare campaignId to the canonical CAMPAIGN# form', () => {
        const result = request(ctxFor({ campaignId: 'c1' }));

        assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'CAMPAIGN#c1' });
    });

    it('rejects a request that names no campaign', () => {
        assert.throws(() => request(ctxFor({})), /INVALID_INPUT: campaignId is required/);
    });
});

describe('locate_campaign_public_settings_fn response', () => {
    it('stashes the located item so the write-access pair can resolve profileId', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' });
        ctx.result = {
            items: [{ profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', campaignName: 'Fall' }]
        };

        const campaign = response(ctx);

        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(ctx.stash.campaign, {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall'
        });
    });

    it('answers NOT_FOUND for a campaignId that resolves to no row', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' });
        ctx.result = { items: [] };

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });

    it('answers NOT_FOUND for a projection without the base-table partition key', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' });
        ctx.result = { items: [{ campaignId: 'CAMPAIGN#c1' }] };

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });

    it('propagates a datasource error unchanged', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' });
        ctx.error = { message: 'Throttled', type: 'DynamoDB:ThrottlingException' };

        assert.throws(() => response(ctx), /DynamoDB:ThrottlingException: Throttled/);
    });
});
