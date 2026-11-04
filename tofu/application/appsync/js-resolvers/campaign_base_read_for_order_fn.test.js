import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './campaign_base_read_for_order_fn.js';

function makeCtx(overrides = {}) {
    return Object.assign(
        {
            stash: {
                campaign: { campaignId: 'CAMPAIGN#c1', profileId: 'PROFILE#p1', catalogId: 'CATALOG#cat1' },
            },
        },
        overrides
    );
}

describe('campaign_base_read_for_order request', () => {
    it('reads the campaigns base table by the locator stashed key', () => {
        const req = request(makeCtx());
        assert.strictEqual(req.operation, 'GetItem');
        assert.deepStrictEqual(req.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(req.consistentRead, true);
    });

    it('tolerates a GSI projection that omitted catalogId (read decides, not the locator)', () => {
        const req = request(makeCtx({ stash: { campaign: { campaignId: 'c1', profileId: 'p1' } } }));
        assert.strictEqual(req.operation, 'GetItem');
    });
});

describe('campaign_base_read_for_order response', () => {
    it('replaces the stashed locator projection with the consistent item', () => {
        const ctx = makeCtx();
        ctx.result = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            catalogId: 'CATALOG#cat2',
            unitId: 'unit-pack-3149-aurora',
            unitCampaignId: 'uc-pack-3149-fall-2026',
        };
        response(ctx);
        assert.strictEqual(ctx.stash.campaign.unitCampaignId, 'uc-pack-3149-fall-2026');
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat2');
    });

    it('applies the back-compat isActive default', () => {
        const ctx = makeCtx();
        ctx.result = { campaignId: 'CAMPAIGN#c1', profileId: 'PROFILE#p1', catalogId: 'CATALOG#cat1' };
        response(ctx);
        assert.strictEqual(ctx.stash.campaign.isActive, true);
    });

    it('errors NOT_FOUND when the base row is gone', () => {
        assert.throws(() => response(makeCtx({ result: null })), /NOT_FOUND: Campaign not found/);
    });

    it('errors NOT_FOUND on a missing locator stash (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Campaign not found/);
    });
});
