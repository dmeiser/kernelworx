import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_campaign_public_order_settings_pipeline_resolver.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the settings mutation root. It composes the
// saved settings off the item the write step just returned, so the settings view
// repaints (including a minted or rotated token) without a GSI round trip.

describe('update_campaign_public_order_settings_pipeline_resolver', () => {
    it('composes the saved settings off the written campaign item', () => {
        const ctx = {
            stash: { isOwner: true, profileId: 'PROFILE#p1' },
            args: { input: { campaignId: 'CAMPAIGN#c1', enabled: true } },
            prev: {
                result: {
                    campaignId: 'CAMPAIGN#c1',
                    campaignName: 'Fall',
                    isActive: true,
                    publicOrderCount: 0,
                    publicOrders: {
                        enabled: true,
                        token: 'auto-generated-id',
                        allowedPaymentMethods: ['Cash'],
                        acknowledgedAt: '2024-01-01T00:00:00Z',
                        ackVersion: 1
                    }
                }
            }
        };

        assert.deepStrictEqual(response(ctx), {
            enabled: true,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignState: 'OK',
            allowedPaymentMethods: ['Cash'],
            shareToken: 'auto-generated-id',
            publicOrderCount: 0,
            acknowledgedAt: '2024-01-01T00:00:00Z',
            ackVersion: 1
        });
    });

    it('falls back to the validated campaign when the write returned nothing', () => {
        const ctx = {
            stash: {
                isOwner: true,
                profileId: 'PROFILE#p1',
                publicSettingsCampaign: {
                    campaignId: 'CAMPAIGN#c1',
                    campaignName: 'Fall',
                    isActive: false,
                    publicOrders: { enabled: false, token: 'token-abc123', allowedPaymentMethods: ['Cash'] }
                }
            },
            args: { input: { campaignId: 'CAMPAIGN#c1', enabled: false } },
            prev: { result: null }
        };

        const settings = response(ctx);

        assert.strictEqual(settings.enabled, false);
        assert.strictEqual(settings.shareToken, 'token-abc123');
        assert.strictEqual(settings.campaignState, 'INACTIVE');
    });

    it('propagates a pipeline error unchanged', () => {
        const ctx = {
            stash: {},
            args: { input: { campaignId: 'CAMPAIGN#c1', enabled: true } },
            error: { message: 'Campaign not found', type: 'NOT_FOUND' }
        };

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });
});
