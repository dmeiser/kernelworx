import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_profile_public_order_settings_pipeline_resolver.js';

// #679 settings slice: the settings mutation returns the saved settings, not the
// raw profile item. The blob comes off the updated item; the campaign display
// fields come off the CampaignsDS validation step's stash writes.

describe('update_profile_public_order_settings_pipeline_resolver', () => {
    it('issues no datastore read of its own', () => {
        assert.deepStrictEqual(request({ stash: {}, args: {} }), {});
    });

    it('shapes the saved settings from the updated item and the campaign stash', () => {
        const ctx = {
            prev: {
                result: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                    updatedAt: '2026-01-02T03:04:05Z',
                    publicOrders: {
                        enabled: true,
                        token: 'token-abc123',
                        campaignId: 'CAMPAIGN#c1',
                        allowedPaymentMethods: ['Venmo', 'Cash'],
                        acknowledgedAt: '2026-01-02T03:04:05Z',
                        ackVersion: 1
                    }
                }
            },
            stash: {
                isOwner: true,
                publicSettingsCampaignState: 'OK',
                publicSettingsCampaignName: 'Fall Cookie Sale',
                publicSettingsOrderCount: 12
            }
        };

        assert.deepStrictEqual(response(ctx), {
            enabled: true,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall Cookie Sale',
            campaignState: 'OK',
            allowedPaymentMethods: ['Venmo', 'Cash'],
            shareToken: 'token-abc123',
            publicOrderCount: 12,
            acknowledgedAt: '2026-01-02T03:04:05Z',
            ackVersion: 1
        });
    });

    it('leaves the campaign fields null for a disable-only save that read no campaign', () => {
        const ctx = {
            prev: {
                result: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                    publicOrders: { enabled: false, token: 'token-abc123' }
                }
            },
            stash: { isOwner: true }
        };

        const settings = response(ctx);

        assert.strictEqual(settings.enabled, false);
        assert.strictEqual(settings.shareToken, 'token-abc123');
        assert.strictEqual(settings.campaignName, null);
        assert.strictEqual(settings.campaignState, null);
        assert.strictEqual(settings.publicOrderCount, null);
        assert.deepStrictEqual(settings.allowedPaymentMethods, []);
    });

    it('re-raises an upstream pipeline error', () => {
        const ctx = { stash: {}, error: { message: 'nope', type: 'FORBIDDEN' } };
        assert.throws(() => response(ctx), /FORBIDDEN: nope/);
    });
});
