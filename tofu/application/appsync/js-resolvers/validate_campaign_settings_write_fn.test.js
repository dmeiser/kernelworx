import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_campaign_settings_write_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the write pipeline's CampaignsDS step. The
// GetItem is keyed by the partition key the locator step learned, so a campaign
// owned by another profile is a GetItem miss - the same shape as "campaign not
// found", never a cross-account read.

function ctxFor(input, locatorCampaign) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            campaign: locatorCampaign,
            profile: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' }
        },
        args: { input },
        identity: { sub: 'ACCOUNT#owner-1' }
    };
}

const LOCATOR = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' };

const ENABLE_INPUT = {
    campaignId: 'CAMPAIGN#c1',
    enabled: true,
    allowedPaymentMethods: ['Venmo'],
    acknowledgementsAccepted: true
};

describe('validate_campaign_settings_write_fn request', () => {
    it('GetItems the campaign under the located partition key, consistently', () => {
        const result = request(ctxFor(ENABLE_INPUT, LOCATOR));

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('normalizes a bare campaignId to the canonical CAMPAIGN# form', () => {
        const input = { ...ENABLE_INPUT, campaignId: 'c1' };
        const result = request(ctxFor(input, LOCATOR));

        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
    });

    it('refuses to build a key when no campaign was located', () => {
        const ctx = ctxFor(ENABLE_INPUT, undefined);
        delete ctx.stash.profileId;

        assert.throws(() => request(ctx), /NOT_FOUND: Campaign not found/);
    });
});

describe('validate_campaign_settings_write_fn response', () => {
    it('stashes the consistent campaign and hands the catalog id to the CatalogsDS step when enabling', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            isActive: true,
            catalogId: 'CATALOG#cat-1'
        };

        const campaign = response(ctx);

        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(ctx.stash.publicSettingsCampaign, ctx.result);
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat-1');
    });

    it('normalizes a bare catalogId for the CatalogsDS step', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: true, catalogId: 'cat-1' };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat-1');
    });

    it('answers NOT_FOUND for a foreign or missing campaign identically', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = null;

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });

    it('rejects enabling over a deactivated campaign', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: false, catalogId: 'CATALOG#cat-1' };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Public orders can only be enabled on an active campaign/
        );
    });

    it('treats an absent isActive as active (pre-attribute back-compat)', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat-1' };

        const campaign = response(ctx);

        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat-1');
    });

    it('rejects enabling when the campaign has no catalog', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: true };

        assert.throws(() => response(ctx), /INVALID_INPUT: Campaign has no catalog assigned/);
    });

    it('lets a disable save through over a deactivated campaign (the off switch must work)', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1', enabled: false }, {
            ...LOCATOR,
            publicOrders: { enabled: true, token: 'tok-1' }
        });
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: false, catalogId: 'CATALOG#cat-1' };

        const campaign = response(ctx);

        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
    });

    it('lets a rotate-token save through over a deactivated campaign', () => {
        const ctx = ctxFor({ campaignId: 'CAMPAIGN#c1', enabled: false, rotateToken: true }, {
            ...LOCATOR,
            publicOrders: { enabled: false, token: 'tok-1' }
        });
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: false, catalogId: 'CATALOG#cat-1' };

        assert.strictEqual(response(ctx).campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
    });

    it('does not re-enforce a save that keeps an already-enabled campaign enabled', () => {
        const ctx = ctxFor(
            { campaignId: 'CAMPAIGN#c1', enabled: true, allowedPaymentMethods: ['Cash'] },
            { ...LOCATOR, publicOrders: { enabled: true, token: 'tok-1' } }
        );
        ctx.result = {
            campaignId: 'CAMPAIGN#c1',
            isActive: false,
            catalogId: 'CATALOG#cat-1',
            publicOrders: { enabled: true, token: 'tok-1', ackVersion: 1 }
        };

        assert.strictEqual(response(ctx).campaignId, 'CAMPAIGN#c1');
    });

    it('propagates a datasource error unchanged', () => {
        const ctx = ctxFor(ENABLE_INPUT, LOCATOR);
        ctx.error = { message: 'Throttled', type: 'DynamoDB:ThrottlingException' };

        assert.throws(() => response(ctx), /DynamoDB:ThrottlingException: Throttled/);
    });
});

// Consistent-read precedence (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1): the publish-
// gating decision must come from the step's own strongly consistent GetItem,
// not from the locator's eventually-consistent GSI copy, which can still
// project the state the owner just changed during a quick disable/re-enable.
describe('validate_campaign_settings_write_fn consistent-read precedence', () => {
    it('rejects a re-enable over an inactive campaign even when the stale GSI copy looks enforcing', () => {
        const locator = {
            ...LOCATOR,
            isActive: true,
            catalogId: 'CATALOG#cat-1',
            publicOrders: { enabled: true, token: 'tok-1' }
        };
        const consistent = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            isActive: false,
            catalogId: 'CATALOG#cat-1',
            publicOrders: { enabled: false, token: 'tok-1' }
        };
        const ctx = ctxFor(ENABLE_INPUT, locator);
        ctx.result = consistent;

        assert.throws(() => response(ctx), /INVALID_INPUT: Public orders can only be enabled on an active campaign/);
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
        assert.strictEqual(ctx.stash.publicSettingsCampaign, consistent);
    });

    it('passes an enable when the stale GSI copy looks inactive but the consistent copy is active', () => {
        const locator = {
            ...LOCATOR,
            isActive: false,
            catalogId: 'CATALOG#cat-1',
            publicOrders: { enabled: false }
        };
        const consistent = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            isActive: true,
            catalogId: 'CATALOG#cat-1',
            publicOrders: { enabled: false }
        };
        const ctx = ctxFor(ENABLE_INPUT, locator);
        ctx.result = consistent;

        const campaign = response(ctx);

        assert.strictEqual(campaign, consistent);
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat-1');
        assert.strictEqual(ctx.stash.publicSettingsCampaign, consistent);
    });
});
