import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './set_profile_latest_campaign_fn.js';

describe('set_profile_latest_campaign_fn request', () => {
    it('SETs latestCampaignId on the owning profile in the create pipeline', () => {
        const ctx = {
            stash: {
                profile: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                },
                createdCampaign: {
                    profileId: 'PROFILE#p1',
                    campaignId: 'CAMPAIGN#new',
                },
            },
            prev: { result: null },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' });
        assert.strictEqual(result.update.expression, 'SET latestCampaignId = :campaignId');
        assert.deepStrictEqual(result.update.expressionValues, { ':campaignId': 'CAMPAIGN#new' });
    });

    it('falls back to ctx.prev.result for the campaign id when stash is empty', () => {
        const ctx = {
            stash: {
                profile: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                },
            },
            prev: { result: { campaignId: 'CAMPAIGN#from-prev' } },
        };

        const result = request(ctx);
        assert.deepStrictEqual(result.update.expressionValues, { ':campaignId': 'CAMPAIGN#from-prev' });
    });

    it('errors when the profile is missing from the stash', () => {
        const ctx = { stash: {}, prev: { result: { campaignId: 'CAMPAIGN#x' } } };
        assert.throws(() => request(ctx), /InternalError: Profile not found in stash/);
    });

    it('errors when no campaign id is available', () => {
        const ctx = {
            stash: { profile: { ownerAccountId: 'ACCOUNT#o', profileId: 'PROFILE#p' } },
            prev: { result: {} },
        };
        assert.throws(() => request(ctx), /InternalError: Created campaign not found/);
    });
});

describe('set_profile_latest_campaign_fn response', () => {
    it('passes the created campaign (prev result) through untouched', () => {
        const created = { campaignId: 'CAMPAIGN#new' };
        const ctx = { prev: { result: created } };

        assert.strictEqual(response(ctx), created);
    });

    it('throws on datasource error', () => {
        const ctx = {
            prev: { result: null },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });
});
