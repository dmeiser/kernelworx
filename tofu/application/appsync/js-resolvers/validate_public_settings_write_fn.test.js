import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_settings_write_fn.js';

// #679 settings slice: the write pipeline's CampaignsDS step. The GetItem is
// keyed by the stashed profile's own partition key, so a campaign owned by
// another profile is a GetItem miss - the same shape as "campaign not found",
// never a cross-account read.

function ctxFor(args, publicOrders) {
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
        args,
        identity: { sub: 'user-1' }
    };
}

const ENABLED_ARGS = {
    profileId: 'PROFILE#p1',
    enabled: true,
    campaignId: 'CAMPAIGN#c1',
    allowedPaymentMethods: ['Venmo'],
    acknowledgementsAccepted: true
};

describe('validate_public_settings_write_fn request', () => {
    it('GetItems the chosen campaign under the stashed profile key', () => {
        const result = request(ctxFor(ENABLED_ARGS, undefined));

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('normalizes a bare campaignId to the canonical CAMPAIGN# form', () => {
        const args = { ...ENABLED_ARGS, campaignId: 'c1' };
        const ctx = ctxFor(args, undefined);
        const result = request(ctx);
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCampaignId, 'CAMPAIGN#c1');
    });

    it('validates the stored anchor when campaignId is omitted', () => {
        const args = { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Venmo'] };
        const ctx = ctxFor(args, {
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c-stored'
        });

        const result = request(ctx);

        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c-stored');
    });

    it('reads nothing for a disable-only save with no stored anchor', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, undefined);
        assert.strictEqual(request(ctx), null);
    });

    it('rejects enabled true with no campaign anywhere', () => {
        const ctx = ctxFor(
            { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Venmo'] },
            undefined
        );
        assert.throws(() => request(ctx), /INVALID_INPUT: campaignId is required to enable public orders/);
    });

    it('rejects an explicit null campaignId, which is not the same as omitting it', () => {
        const args = { ...ENABLED_ARGS, campaignId: null };
        assert.throws(
            () => request(ctxFor(args, { enabled: true, campaignId: 'CAMPAIGN#c1' })),
            /INVALID_INPUT: campaignId cannot be null; omit the field to keep the current campaign/
        );
    });

    it('never mentions the share token in a rejection', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: true }, {
            enabled: false,
            token: 'token-abc123',
            allowedPaymentMethods: ['Cash']
        });

        assert.throws(() => request(ctx), (error) => {
            assert.ok(!error.message.includes('token-abc123'));
            return true;
        });
    });
});

describe('validate_public_settings_write_fn response', () => {
    it('stashes the campaign, its state, and the normalized catalog key', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.result = {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall Cookie Sale',
            isActive: true,
            catalogId: 'CATALOG#cat1',
            publicOrderCount: 4
        };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'OK');
        assert.strictEqual(ctx.stash.publicSettingsCampaignName, 'Fall Cookie Sale');
        assert.strictEqual(ctx.stash.publicSettingsOrderCount, 4);
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat1');
    });

    it('normalizes a bare stored catalogId', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: true, catalogId: 'cat1' };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCatalogId, 'CATALOG#cat1');
    });

    it('treats a campaign owned by another profile as a GetItem miss', () => {
        // The key carries the stashed profileId, so a foreign campaign simply
        // is not found. Assert the exact-string equality with the plain
        // not-found case: no oracle for whether the id exists elsewhere.
        const foreign = ctxFor(ENABLED_ARGS, undefined);
        foreign.result = null;
        const absent = ctxFor(ENABLED_ARGS, undefined);
        absent.result = null;

        let foreignMessage = null;
        let absentMessage = null;
        try {
            response(foreign);
        } catch (error) {
            foreignMessage = error.message;
        }
        try {
            response(absent);
        } catch (error) {
            absentMessage = error.message;
        }

        assert.strictEqual(foreignMessage, 'NOT_FOUND: Campaign not found');
        assert.strictEqual(foreignMessage, absentMessage);
    });

    it('rejects a deactivated campaign', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: false, catalogId: 'CATALOG#cat1' };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Public orders can only be anchored to an active campaign/
        );
    });

    it('treats a missing isActive as active (back-compat default)', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', campaignName: 'Fall' };

        response(ctx);

        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'OK');
    });

    it('rejects a campaign with no catalog', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: true };

        assert.throws(() => response(ctx), /INVALID_INPUT: Campaign has no catalog assigned/);
    });

    it('lets a disable stand over a deactivated anchor and flags INACTIVE', () => {
        // The off switch must never be blocked by a stale anchor: rejecting this
        // save would strand the seller over a dead campaign.
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, {
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c1'
        });
        ctx.result = { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: false, catalogId: 'CATALOG#cat1' };

        const campaign = response(ctx);

        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'INACTIVE');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
    });

    it('lets a disable stand over a missing anchor and flags MISSING', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, {
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c-gone'
        });
        ctx.result = null;

        assert.strictEqual(response(ctx), null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'MISSING');
    });

    it('lets a rotate-token save stand over a missing anchor and flags MISSING', () => {
        // enabled=true alone is not enforcing: a rotate-only save must not be
        // dragged into anchor validation, or token revocation is blocked
        // exactly when the stored anchor is out of sync.
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: true, rotateToken: true }, {
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c-gone'
        });
        ctx.result = null;

        assert.strictEqual(response(ctx), null);
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'MISSING');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
    });

    it('lets a method-list change stand over an inactive anchor and flags INACTIVE', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Venmo'] }, {
            enabled: true,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c1'
        });
        ctx.result = { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: false, catalogId: 'CATALOG#cat1' };

        const campaign = response(ctx);
        assert.strictEqual(campaign.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(ctx.stash.publicSettingsCampaignState, 'INACTIVE');
        assert.strictEqual(ctx.stash.publicSettingsCatalogId, undefined);
    });

    it('rejects a save that enables over an inactive stored anchor without re-picking', () => {
        // The disabled->enabled transition is publishing: the stored anchor is
        // validated again even when the request does not name it.
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Venmo'] }, {
            enabled: false,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c1'
        });
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: false, catalogId: 'CATALOG#cat1' };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Public orders can only be anchored to an active campaign/
        );
    });

    it('rejects a save that enables over a missing stored anchor without re-picking', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Venmo'] }, {
            enabled: false,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c-gone'
        });
        ctx.result = null;

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });

    it('enforces again when a parked save re-picks the anchor campaign', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false, campaignId: 'CAMPAIGN#c2' }, {
            enabled: false,
            token: 'token-abc123',
            campaignId: 'CAMPAIGN#c1'
        });
        ctx.result = { campaignId: 'CAMPAIGN#c2', isActive: false, catalogId: 'CATALOG#cat1' };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Public orders can only be anchored to an active campaign/
        );
    });

    it('never mentions the share token in a rejection', () => {
        const ctx = ctxFor(ENABLED_ARGS, { enabled: true, token: 'token-abc123' });
        ctx.result = null;

        assert.throws(() => response(ctx), (error) => {
            assert.ok(!error.message.includes('token-abc123'), error.message);
            return true;
        });
    });

    it('re-raises a datasource error', () => {
        const ctx = ctxFor(ENABLED_ARGS, undefined);
        ctx.error = { message: 'boom', type: 'DynamoDBException' };

        assert.throws(() => response(ctx), /DynamoDBException: boom/);
    });
});
