import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './seller_profile_latest_campaign_resolver.js';

describe('seller_profile_latest_campaign_resolver request', () => {
    it('uses a single GetItem when the profile carries latestCampaignId', () => {
        const ctx = {
            source: {
                profileId: 'PROFILE#p1',
                latestCampaignId: 'CAMPAIGN#1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#1' });
    });

    it('adds the PROFILE# prefix for the GetItem path when missing', () => {
        const ctx = {
            source: {
                profileId: 'p1',
                latestCampaignId: 'CAMPAIGN#1',
            },
        };

        const result = request(ctx);
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#1' });
    });

    it('falls back to the per-item GSI Query when latestCampaignId is absent', () => {
        const ctx = {
            source: { profileId: 'p1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-createdAt-index');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, { ':profileId': 'PROFILE#p1' });
        assert.strictEqual(result.filter.expression, 'isActive = :isActive OR attribute_not_exists(isActive)');
        assert.strictEqual(result.scanIndexForward, false);
    });
});

describe('seller_profile_latest_campaign_resolver response', () => {
    it('returns the fetched campaign on the GetItem path', () => {
        const campaign = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#1', isActive: true };
        const ctx = {
            source: { profileId: 'PROFILE#p1', latestCampaignId: 'CAMPAIGN#1' },
            result: campaign,
        };

        assert.strictEqual(response(ctx), campaign);
    });

    it('defaults a missing isActive to true on the GetItem path', () => {
        const campaign = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#1' };
        const ctx = {
            source: { profileId: 'PROFILE#p1', latestCampaignId: 'CAMPAIGN#1' },
            result: campaign,
        };

        const result = response(ctx);
        assert.strictEqual(result.isActive, true);
    });

    it('returns null on the GetItem path when the campaign is gone (dangling pointer)', () => {
        const ctx = {
            source: { profileId: 'PROFILE#p1', latestCampaignId: 'CAMPAIGN#gone' },
            result: null,
        };

        assert.strictEqual(response(ctx), null);
    });

    it('returns null on the GetItem path when the pointed campaign is inactive', () => {
        const ctx = {
            source: { profileId: 'PROFILE#p1', latestCampaignId: 'CAMPAIGN#off' },
            result: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#off', isActive: false },
        };

        assert.strictEqual(response(ctx), null);
    });

    it('returns the newest active campaign from the fallback Query path', () => {
        const newest = { campaignId: 'CAMPAIGN#2', isActive: true };
        const ctx = {
            source: { profileId: 'PROFILE#p1' },
            result: { items: [newest, { campaignId: 'CAMPAIGN#1' }] },
        };

        assert.strictEqual(response(ctx), newest);
    });

    it('returns null from the fallback Query path when no active campaigns remain', () => {
        const ctx = {
            source: { profileId: 'PROFILE#p1' },
            result: { items: [] },
        };

        assert.strictEqual(response(ctx), null);
    });

    it('throws on datasource error', () => {
        const ctx = {
            source: { profileId: 'PROFILE#p1' },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });
});
