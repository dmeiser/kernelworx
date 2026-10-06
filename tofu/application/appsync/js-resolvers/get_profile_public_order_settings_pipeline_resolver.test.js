import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_profile_public_order_settings_pipeline_resolver.js';

// #679 settings slice: the settings read's output shaping. The blob comes off
// the profile the ownership pair stashed; the campaign fields come off the
// CampaignsDS step's stash writes.

describe('get_profile_public_order_settings_pipeline_resolver', () => {
    it('issues no datastore read of its own', () => {
        assert.deepStrictEqual(request({ stash: {}, args: {} }), {});
    });

    it('returns the token, counter and campaign fields for an enabled profile', () => {
        const ctx = {
            stash: {
                isOwner: true,
                profileId: 'PROFILE#p1',
                profile: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                    publicOrders: {
                        enabled: true,
                        token: 'token-abc123',
                        campaignId: 'CAMPAIGN#c1',
                        allowedPaymentMethods: ['Venmo', 'Cash'],
                        acknowledgedAt: '2026-01-02T03:04:05Z',
                        ackVersion: 1
                    }
                },
                publicSettingsCampaignState: 'OK',
                publicSettingsCampaignName: 'Fall Cookie Sale',
                publicSettingsOrderCount: 7
            },
            prev: {
                result: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', campaignName: 'Fall Cookie Sale' }
            }
        };

        assert.deepStrictEqual(response(ctx), {
            enabled: true,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall Cookie Sale',
            campaignState: 'OK',
            allowedPaymentMethods: ['Venmo', 'Cash'],
            shareToken: 'token-abc123',
            publicOrderCount: 7,
            acknowledgedAt: '2026-01-02T03:04:05Z',
            ackVersion: 1
        });
    });

    it('answers a never-enabled profile with enabled false and nulls, not an error', () => {
        const ctx = {
            stash: {
                isOwner: true,
                profileId: 'PROFILE#p1',
                profile: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' },
                publicSettingsCampaignState: null,
                publicSettingsCampaignName: null,
                publicSettingsOrderCount: null
            },
            prev: { result: null }
        };

        assert.deepStrictEqual(response(ctx), {
            enabled: false,
            campaignId: null,
            campaignName: null,
            campaignState: null,
            allowedPaymentMethods: [],
            shareToken: null,
            publicOrderCount: null,
            acknowledgedAt: null,
            ackVersion: null
        });
    });

    it('flags a dangling anchor as MISSING', () => {
        const ctx = {
            stash: {
                isOwner: true,
                profile: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                    publicOrders: {
                        enabled: true,
                        token: 'token-abc123',
                        campaignId: 'CAMPAIGN#c-gone',
                        allowedPaymentMethods: ['Cash'],
                        ackVersion: 1
                    }
                },
                publicSettingsCampaignState: 'MISSING',
                publicSettingsCampaignName: null,
                publicSettingsOrderCount: null
            },
            prev: { result: null }
        };

        const settings = response(ctx);
        assert.strictEqual(settings.campaignState, 'MISSING');
        assert.strictEqual(settings.campaignId, 'CAMPAIGN#c-gone');
        assert.strictEqual(settings.publicOrderCount, null);
    });

    it('flags a deactivated anchor as INACTIVE', () => {
        const ctx = {
            stash: {
                isOwner: true,
                profile: {
                    ownerAccountId: 'ACCOUNT#owner-1',
                    profileId: 'PROFILE#p1',
                    publicOrders: {
                        enabled: true,
                        token: 'token-abc123',
                        campaignId: 'CAMPAIGN#c1',
                        allowedPaymentMethods: ['Cash']
                    }
                },
                publicSettingsCampaignState: 'INACTIVE',
                publicSettingsCampaignName: 'Fall Cookie Sale',
                publicSettingsOrderCount: 3
            },
            prev: { result: { campaignId: 'CAMPAIGN#c1', isActive: false } }
        };

        const settings = response(ctx);
        assert.strictEqual(settings.campaignState, 'INACTIVE');
        assert.strictEqual(settings.publicOrderCount, 3);
    });

    it('re-raises an upstream pipeline error', () => {
        const ctx = { stash: {}, error: { message: 'boom', type: 'FORBIDDEN' } };
        assert.throws(() => response(ctx), /FORBIDDEN: boom/);
    });
});
