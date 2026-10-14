import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_campaign_public_order_settings_pipeline_resolver.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the settings query root. It composes the
// PublicOrderSettings output off the consistent campaign item the last step
// stashed, shadowing the locator's eventually-consistent GSI copy.

function ctxFor(consistentCampaign, locatorCampaign) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            campaign: locatorCampaign,
            publicSettingsCampaign: consistentCampaign
        },
        args: { campaignId: 'CAMPAIGN#c1' }
    };
}

describe('get_campaign_public_order_settings_pipeline_resolver', () => {
    it('composes the enabled settings off the consistent campaign item', () => {
        const ctx = ctxFor(
            {
                campaignId: 'CAMPAIGN#c1',
                campaignName: 'Fall',
                isActive: true,
                publicOrderCount: 7,
                publicOrders: {
                    enabled: true,
                    token: 'token-abc123',
                    allowedPaymentMethods: ['Cash', 'Venmo'],
                    acknowledgedAt: '2024-01-01T00:00:00Z',
                    ackVersion: 1
                }
            },
            { campaignId: 'CAMPAIGN#c1' }
        );

        assert.deepStrictEqual(response(ctx), {
            enabled: true,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignState: 'OK',
            allowedPaymentMethods: ['Cash', 'Venmo'],
            shareToken: 'token-abc123',
            publicOrderCount: 7,
            acknowledgedAt: '2024-01-01T00:00:00Z',
            ackVersion: 1
        });
    });

    it('answers enabled false with empty defaults for a campaign that never enabled the feature', () => {
        const ctx = ctxFor(
            { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: true },
            { campaignId: 'CAMPAIGN#c1' }
        );

        assert.deepStrictEqual(response(ctx), {
            enabled: false,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignState: 'OK',
            allowedPaymentMethods: [],
            shareToken: null,
            publicOrderCount: 0,
            acknowledgedAt: null,
            ackVersion: null
        });
    });

    it('reports INACTIVE for a deactivated campaign', () => {
        const ctx = ctxFor(
            {
                campaignId: 'CAMPAIGN#c1',
                campaignName: 'Fall',
                isActive: false,
                publicOrders: { enabled: true, token: 'token-abc123', allowedPaymentMethods: ['Cash'] }
            },
            { campaignId: 'CAMPAIGN#c1' }
        );

        assert.strictEqual(response(ctx).campaignState, 'INACTIVE');
    });

    it('prefers the consistent read over the locator GSI copy', () => {
        const ctx = ctxFor(
            { campaignId: 'CAMPAIGN#c1', campaignName: 'Fresh', isActive: true, publicOrderCount: 2 },
            { campaignId: 'CAMPAIGN#c1', campaignName: 'Stale', publicOrderCount: 0 }
        );

        const settings = response(ctx);

        assert.strictEqual(settings.campaignName, 'Fresh');
        assert.strictEqual(settings.publicOrderCount, 2);
    });

    it('propagates a pipeline error unchanged', () => {
        const ctx = ctxFor(undefined, undefined);
        ctx.error = { message: 'Only the profile owner can manage public order settings', type: 'FORBIDDEN' };

        assert.throws(() => response(ctx), /FORBIDDEN: Only the profile owner/);
    });
});
