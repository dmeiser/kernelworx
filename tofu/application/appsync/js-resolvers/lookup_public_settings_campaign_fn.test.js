import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_public_settings_campaign_fn.js';

// #679 settings slice: the settings read's single CampaignsDS GetItem. The
// counter and the campaign name live on the campaign item, not on the profile
// blob, and campaignState is the staleness flag the settings UI renders.

function ownerCtx(publicOrders) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            profile: {
                ownerAccountId: 'ACCOUNT#owner-1',
                profileId: 'PROFILE#p1',
                publicOrders
            }
        },
        args: { profileId: 'PROFILE#p1' },
        identity: { sub: 'user-1' }
    };
}

describe('lookup_public_settings_campaign_fn request', () => {
    it('GetItems the anchor campaign under the stashed profile key', () => {
        const ctx = ownerCtx({
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c1'
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('re-prefixes a stored anchor id that somehow lacks the prefix', () => {
        const ctx = ownerCtx({ enabled: true, campaignId: 'c1' });
        const result = request(ctx);
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
    });

    it('reads nothing for a profile that never enabled the feature', () => {
        const ctx = ownerCtx(undefined);

        const result = request(ctx);

        // runtime.earlyReturn is mocked to return its value.
        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignName, null);
        assert.strictEqual(ctx.stash.publicSettingsOrderCount, null);
    });

    it('reads nothing for an anchor-less blob (disabled before a campaign was picked)', () => {
        const ctx = ownerCtx({ enabled: false, token: 'token-abc123' });
        assert.strictEqual(request(ctx), null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, null);
    });
});

describe('lookup_public_settings_campaign_fn response', () => {
    it('reports OK and fills the counter and name from the campaign row', () => {
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c1' });
        ctx.result = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall Cookie Sale',
            isActive: true,
            publicOrderCount: 7
        };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'OK');
        assert.strictEqual(ctx.stash.publicSettingsCampaignName, 'Fall Cookie Sale');
        assert.strictEqual(ctx.stash.publicSettingsOrderCount, 7);
    });

    it('defaults an anchor campaign without a counter to 0', () => {
        // The counter is created by the public write path (a later slice), so an
        // anchor row without it has served zero public orders.
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c1' });
        ctx.result = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: true };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsOrderCount, 0);
    });

    it('reports INACTIVE for a deactivated anchor', () => {
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c1' });
        ctx.result = { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: false, publicOrderCount: 3 };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'INACTIVE');
        assert.strictEqual(ctx.stash.publicSettingsOrderCount, 3);
    });

    it('treats a missing isActive as active (back-compat default)', () => {
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c1' });
        ctx.result = { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', publicOrderCount: 0 };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'OK');
    });

    it('reports MISSING when the anchor row is gone', () => {
        // Covers both a deleted campaign whose auto-disable never ran and a
        // dangling pointer to a campaign this profile does not own.
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c-gone' });
        ctx.result = null;

        const result = response(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'MISSING');
        assert.strictEqual(ctx.stash.publicSettingsCampaignName, null);
        assert.strictEqual(ctx.stash.publicSettingsOrderCount, null);
    });

    it('re-raises a datasource error', () => {
        const ctx = ownerCtx({ enabled: true, campaignId: 'CAMPAIGN#c1' });
        ctx.error = { message: 'throttled', type: 'DynamoDB:ProvisionedThroughputExceededException' };

        assert.throws(() => response(ctx), /DynamoDB:ProvisionedThroughputExceededException: throttled/);
    });
});
