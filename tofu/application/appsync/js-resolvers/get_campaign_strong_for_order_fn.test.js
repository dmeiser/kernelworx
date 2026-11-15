import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_campaign_strong_for_order_fn.js';

describe('get_campaign_strong_for_order_fn request', () => {
    it('gets the campaign by its base-table key, strongly, which only the locator could supply', () => {
        const result = request({ stash: { campaign: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' } } });
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
    });

    it('refuses when the locator found nothing to address', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Campaign not found/);
        assert.throws(() => request({ stash: { campaign: { campaignId: 'CAMPAIGN#c1' } } }), /NOT_FOUND: Campaign not found/);
    });
});

describe('get_campaign_strong_for_order_fn response', () => {
    it('replaces the projection with the base-table item downstream steps trust', () => {
        const stash = { campaign: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#old', isActive: true } };
        const campaign = response({
            stash,
            result: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', catalogId: 'raw-catalog', isActive: false }
        });
        assert.strictEqual(stash.campaign.catalogId, 'raw-catalog');
        assert.strictEqual(stash.catalogId, 'CATALOG#raw-catalog');
        assert.strictEqual(stash.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(campaign.isActive, false);
    });

    it('treats a projection the base table no longer holds as a deleted campaign', () => {
        // The GSI can still show an item that was just deleted; the order must not
        // be written against it.
        assert.throws(() => response({ stash: {}, result: null }), /NOT_FOUND: Campaign not found/);
    });

    it('defaults a missing isActive to true and refuses a campaign with no catalog', () => {
        const stash = {};
        const campaign = response({ stash, result: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#c' } });
        assert.strictEqual(campaign.isActive, true);
        assert.throws(
            () => response({ stash: {}, result: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' } }),
            /INVALID_INPUT: Campaign has no catalog assigned/
        );
    });
});
