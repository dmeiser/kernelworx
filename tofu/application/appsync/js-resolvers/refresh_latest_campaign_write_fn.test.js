import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './refresh_latest_campaign_write_fn.js';

const PROFILE = { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' };

describe('refresh_latest_campaign_write_fn request', () => {
    it('SETs latestCampaignId when the lookup found a latest active campaign', () => {
        const ctx = {
            stash: {
                profile: PROFILE,
                latestActiveCampaignResolved: true,
                latestActiveCampaignId: 'CAMPAIGN#b',
            },
            prev: { result: { campaignId: 'CAMPAIGN#old' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' });
        assert.strictEqual(result.update.expression, 'SET latestCampaignId = :campaignId');
        assert.deepStrictEqual(result.update.expressionValues, { ':campaignId': 'CAMPAIGN#b' });
    });

    it('REMOVEs latestCampaignId when no active campaigns remain', () => {
        const ctx = {
            stash: {
                profile: PROFILE,
                latestActiveCampaignResolved: true,
                latestActiveCampaignId: null,
            },
            prev: { result: true },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.strictEqual(result.update.expression, 'REMOVE latestCampaignId');
    });

    it('skips when the lookup was skipped', () => {
        const ctx = {
            stash: { profile: PROFILE },
            prev: { result: { campaignId: 'CAMPAIGN#old' } },
        };

        assert.deepStrictEqual(request(ctx), ctx.prev.result);
    });
});

describe('refresh_latest_campaign_write_fn response', () => {
    it('passes prev through so the mutation result is preserved', () => {
        const prev = { campaignId: 'CAMPAIGN#old' };
        assert.strictEqual(response({ prev: { result: prev } }), prev);
    });

    it('throws on datasource error', () => {
        const ctx = {
            prev: { result: null },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });
});
