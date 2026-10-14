import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_campaign_public_settings_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the authoritative settings read of the
// getCampaignPublicOrderSettings pipeline. Rev 7 keeps the publicOrders map on
// the campaign item, so one strongly consistent GetItem returns the settings,
// the counter, and the campaign's own name and active state.

function ctxFor(args, locatorCampaign) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            campaign: locatorCampaign,
            profile: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' }
        },
        args,
        identity: { sub: 'ACCOUNT#owner-1' }
    };
}

const LOCATOR = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' };

describe('lookup_campaign_public_settings_fn request', () => {
    it('GetItems the campaign under the located partition key, consistently', () => {
        const result = request(ctxFor({ campaignId: 'CAMPAIGN#c1' }, LOCATOR));

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('normalizes a bare campaignId to the canonical CAMPAIGN# form', () => {
        const result = request(ctxFor({ campaignId: 'c1' }, LOCATOR));

        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
    });

    it('falls back to the located campaign id when the args name none', () => {
        const ctx = ctxFor({}, LOCATOR);
        delete ctx.stash.profileId;

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
    });

    it('refuses to build a key when no campaign was located', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' }, undefined);
        delete ctx.stash.profileId;

        assert.throws(() => request(ctx), /NOT_FOUND: Campaign not found/);
    });
});

describe('lookup_campaign_public_settings_fn response', () => {
    it('stashes the consistent item so the root composes from it, not the GSI copy', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' }, LOCATOR);
        const consistent = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            isActive: true,
            publicOrderCount: 3,
            publicOrders: { enabled: true, token: 'tok-1', allowedPaymentMethods: ['Cash'] }
        };
        ctx.result = consistent;

        const campaign = response(ctx);

        assert.strictEqual(campaign, consistent);
        assert.deepStrictEqual(ctx.stash.publicSettingsCampaign, consistent);
    });

    it('answers NOT_FOUND when the campaign vanished after the locator read', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' }, LOCATOR);
        ctx.result = null;

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });

    it('propagates a datasource error unchanged', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1' }, LOCATOR);
        ctx.error = { message: 'Throttled', type: 'DynamoDB:ThrottlingException' };

        assert.throws(() => response(ctx), /DynamoDB:ThrottlingException: Throttled/);
    });
});
