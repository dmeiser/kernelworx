import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './refresh_latest_campaign_lookup_fn.js';

const CAMPAIGN = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#old' };

describe('refresh_latest_campaign_lookup_fn request', () => {
    it('queries the GSI when updateCampaign changes isActive', () => {
        const ctx = {
            info: { fieldName: 'updateCampaign' },
            args: { input: { campaignId: 'CAMPAIGN#old', isActive: false } },
            stash: { campaign: CAMPAIGN },
            prev: { result: { campaignId: 'CAMPAIGN#old' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-createdAt-index');
        assert.deepStrictEqual(result.query.expressionValues, { ':profileId': 'PROFILE#p1' });
        assert.strictEqual(result.filter.expression, 'isActive = :isActive OR attribute_not_exists(isActive)');
        assert.strictEqual(result.scanIndexForward, false);
    });

    it('queries the GSI when deleteCampaign removes a campaign', () => {
        const ctx = {
            info: { fieldName: 'deleteCampaign' },
            args: { campaignId: 'CAMPAIGN#old' },
            stash: { campaign: CAMPAIGN },
            prev: { result: true },
        };

        assert.strictEqual(request(ctx).operation, 'Query');
    });

    it('skips when updateCampaign does not touch isActive', () => {
        const ctx = {
            info: { fieldName: 'updateCampaign' },
            args: { input: { campaignId: 'CAMPAIGN#old', campaignName: 'New name' } },
            stash: { campaign: CAMPAIGN },
            prev: { result: { campaignId: 'CAMPAIGN#old' } },
        };

        assert.deepStrictEqual(request(ctx), ctx.prev.result);
    });

    it('skips the idempotent deleteCampaign when the campaign is already gone', () => {
        const ctx = {
            info: { fieldName: 'deleteCampaign' },
            args: { campaignId: 'CAMPAIGN#gone' },
            stash: { campaign: null },
            prev: { result: true },
        };

        assert.deepStrictEqual(request(ctx), ctx.prev.result);
    });
});

describe('refresh_latest_campaign_lookup_fn response', () => {
    it('stashes the newest active campaign id and passes prev through', () => {
        const prev = { campaignId: 'CAMPAIGN#old' };
        const ctx = {
            stash: { campaign: CAMPAIGN },
            prev: { result: prev },
            result: {
                items: [
                    { campaignId: 'CAMPAIGN#b' },
                    { campaignId: 'CAMPAIGN#c' },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result, prev);
        assert.strictEqual(ctx.stash.latestActiveCampaignId, 'CAMPAIGN#b');
        assert.strictEqual(ctx.stash.latestActiveCampaignResolved, true);
    });

    it('excludes the just-deleted campaign from a stale GSI read', () => {
        const ctx = {
            stash: { campaign: CAMPAIGN },
            prev: { result: true },
            result: {
                items: [
                    { campaignId: 'CAMPAIGN#old' },
                    { campaignId: 'CAMPAIGN#b' },
                ],
            },
        };

        response(ctx);

        assert.strictEqual(ctx.stash.latestActiveCampaignId, 'CAMPAIGN#b');
    });

    it('stashes null when no active campaigns remain', () => {
        const ctx = {
            stash: { campaign: CAMPAIGN },
            prev: { result: true },
            result: { items: [{ campaignId: 'CAMPAIGN#old', isActive: false }] },
        };

        response(ctx);

        assert.strictEqual(ctx.stash.latestActiveCampaignId, null);
        assert.strictEqual(ctx.stash.latestActiveCampaignResolved, true);
    });

    it('throws on datasource error', () => {
        const ctx = {
            stash: { campaign: CAMPAIGN },
            prev: { result: true },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });
});
