import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
    ACK_VERSION,
    campaignIsActive,
    composePublicOrderSettings,
    requestCampaignId,
    resolveAllowedPaymentMethods,
    settingsCampaign,
    settingsWriteIsEnforcing,
    stashedCampaignId,
    stashedProfileId,
    storedPublicOrders
} from './public_settings.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the shared campaign-level settings helpers.
// Both settings pipelines resolve the campaign key, the stored blob, and the
// omitted-vs-explicit-null argument semantics through this module so the
// validation step and the write step cannot disagree.

describe('requestCampaignId', () => {
    it('reads the mutation input object first', () => {
        assert.strictEqual(
            requestCampaignId({ args: { input: { campaignId: 'CAMPAIGN#c1' }, campaignId: 'CAMPAIGN#other' } }),
            'CAMPAIGN#c1'
        );
    });

    it('reads a top-level argument for the settings query', () => {
        assert.strictEqual(requestCampaignId({ args: { campaignId: 'c1' } }), 'CAMPAIGN#c1');
    });

    it('returns null when neither names a campaign', () => {
        assert.strictEqual(requestCampaignId({ args: {} }), null);
        assert.strictEqual(requestCampaignId({}), null);
    });
});

describe('settingsCampaign prefers the consistent read over the GSI locator copy', () => {
    it('returns the strongly consistent item when present', () => {
        const ctx = { stash: { campaign: { campaignId: 'CAMPAIGN#c1', campaignName: 'Stale' }, publicSettingsCampaign: { campaignName: 'Fresh' } } };

        assert.strictEqual(settingsCampaign(ctx).campaignName, 'Fresh');
    });

    it('falls back to the locator item', () => {
        assert.deepStrictEqual(settingsCampaign({ stash: { campaign: { campaignId: 'CAMPAIGN#c1' } } }), {
            campaignId: 'CAMPAIGN#c1'
        });
    });

    it('returns null when no campaign was located', () => {
        assert.strictEqual(settingsCampaign({ stash: {} }), null);
        assert.strictEqual(settingsCampaign({}), null);
    });
});

describe('storedPublicOrders', () => {
    it('reads the map off the campaign item', () => {
        const ctx = { stash: { publicSettingsCampaign: { publicOrders: { enabled: true, token: 't' } } } };

        assert.deepStrictEqual(storedPublicOrders(ctx), { enabled: true, token: 't' });
    });

    it('returns null for a campaign that never enabled the feature', () => {
        assert.strictEqual(storedPublicOrders({ stash: { campaign: { campaignId: 'CAMPAIGN#c1' } } }), null);
    });
});

describe('stashedProfileId / stashedCampaignId', () => {
    it('prefers the id the write-access pair normalized', () => {
        const ctx = {
            stash: { profileId: 'PROFILE#p1', campaign: { profileId: 'PROFILE#other', campaignId: 'CAMPAIGN#c1' } },
            args: { campaignId: 'CAMPAIGN#c1' }
        };

        assert.strictEqual(stashedProfileId(ctx), 'PROFILE#p1');
    });

    it('falls back to the located campaign attributes', () => {
        const ctx = { stash: { campaign: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' } }, args: {} };

        assert.strictEqual(stashedProfileId(ctx), 'PROFILE#p1');
        assert.strictEqual(stashedCampaignId(ctx), 'CAMPAIGN#c1');
    });

    it('returns null when nothing was located', () => {
        assert.strictEqual(stashedProfileId({ stash: {}, args: {} }), null);
        assert.strictEqual(stashedCampaignId({ stash: {}, args: {} }), null);
    });
});

describe('resolveAllowedPaymentMethods', () => {
    it('keeps the stored list when the field is omitted', () => {
        const ctx = { args: { input: {} }, stash: { publicSettingsCampaign: { publicOrders: { allowedPaymentMethods: ['Cash'] } } } };

        assert.deepStrictEqual(resolveAllowedPaymentMethods(ctx), ['Cash']);
    });

    it('takes the request list when present', () => {
        const ctx = { args: { input: { allowedPaymentMethods: ['Venmo'] } }, stash: {} };

        assert.deepStrictEqual(resolveAllowedPaymentMethods(ctx), ['Venmo']);
    });

    it('rejects an explicit null rather than treating it as an omission', () => {
        const ctx = { args: { input: { allowedPaymentMethods: null } }, stash: {} };

        assert.throws(
            () => resolveAllowedPaymentMethods(ctx),
            /INVALID_INPUT: allowedPaymentMethods cannot be null/
        );
    });

    it('rejects a list holding a blank name', () => {
        const ctx = { args: { input: { allowedPaymentMethods: [''] } }, stash: {} };

        assert.throws(
            () => resolveAllowedPaymentMethods(ctx),
            /INVALID_INPUT: allowedPaymentMethods must be a list of non-empty names/
        );
    });

    it('returns null when neither the request nor the stored blob names a list', () => {
        assert.strictEqual(resolveAllowedPaymentMethods({ args: { input: {} }, stash: {} }), null);
    });
});

describe('settingsWriteIsEnforcing', () => {
    it('enforces when turning the feature on from an off state', () => {
        assert.strictEqual(settingsWriteIsEnforcing({ args: { input: { enabled: true } }, stash: {} }), true);
    });

    it('does not enforce a save that keeps an already-enabled campaign enabled', () => {
        const ctx = { args: { input: { enabled: true } }, stash: { publicSettingsCampaign: { publicOrders: { enabled: true } } } };

        assert.strictEqual(settingsWriteIsEnforcing(ctx), false);
    });

    it('never enforces a disable, so the off switch always works', () => {
        const ctx = { args: { input: { enabled: false } }, stash: { publicSettingsCampaign: { publicOrders: { enabled: true } } } };

        assert.strictEqual(settingsWriteIsEnforcing(ctx), false);
    });
});

describe('campaignIsActive', () => {
    it('treats an absent isActive as active (pre-attribute back-compat)', () => {
        assert.strictEqual(campaignIsActive({ campaignId: 'CAMPAIGN#c1' }), true);
    });

    it('treats an explicit false as inactive', () => {
        assert.strictEqual(campaignIsActive({ isActive: false }), false);
    });

    it('treats a missing campaign as inactive', () => {
        assert.strictEqual(campaignIsActive(null), false);
    });
});

describe('composePublicOrderSettings', () => {
    it('shapes the settings off the campaign and its map', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            isActive: true,
            publicOrderCount: 4
        };
        const blob = {
            enabled: true,
            token: 'tok',
            allowedPaymentMethods: ['Cash'],
            acknowledgedAt: '2024-01-01T00:00:00Z',
            ackVersion: ACK_VERSION
        };

        assert.deepStrictEqual(composePublicOrderSettings(campaign, blob), {
            enabled: true,
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignState: 'OK',
            allowedPaymentMethods: ['Cash'],
            shareToken: 'tok',
            publicOrderCount: 4,
            acknowledgedAt: '2024-01-01T00:00:00Z',
            ackVersion: ACK_VERSION
        });
    });

    it('defaults a campaign with no map to enabled false with empty defaults', () => {
        const settings = composePublicOrderSettings({ campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: true }, null);

        assert.strictEqual(settings.enabled, false);
        assert.deepStrictEqual(settings.allowedPaymentMethods, []);
        assert.strictEqual(settings.shareToken, null);
        assert.strictEqual(settings.publicOrderCount, 0);
        assert.strictEqual(settings.campaignState, 'OK');
    });

    it('has no MISSING state: rev 7 settings live on the campaign, so the campaign is always present', () => {
        const settings = composePublicOrderSettings({ campaignId: 'CAMPAIGN#c1', isActive: false }, null);

        assert.strictEqual(settings.campaignState, 'INACTIVE');
    });
});
