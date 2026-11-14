import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_active_unit_campaign_for_order_fn.js';

describe('get_active_unit_campaign_for_order_fn request', () => {
    it('gets the Unit Campaign metadata row the guard points at', () => {
        const result = request({ stash: { activeUnitCampaignId: 'uc-1' } });
        assert.strictEqual(result.operation, 'Get');
        assert.deepStrictEqual(result.key, { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'METADATA' });
    });

    it('does not touch the table when the campaign is joined to nothing', () => {
        // Returning null means the table is never called; the origin stays null
        // rather than being guessed from the campaign's retained link.
        assert.strictEqual(request({ stash: { activeUnitCampaignId: null } }), null);
        assert.strictEqual(request({ stash: {} }), null);
    });
});

describe('get_active_unit_campaign_for_order_fn response', () => {
    it('stashes the Unit Campaign row that names the Unit', () => {
        const stash = {};
        response({ stash, result: { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'METADATA', unitId: 'UNIT#pack-3149' } });
        assert.strictEqual(stash.activeUnitCampaign.unitId, 'UNIT#pack-3149');
    });

    it('stashes nothing when the pointed-at row is gone', () => {
        const stash = {};
        assert.strictEqual(response({ stash, result: null }), null);
        assert.strictEqual(stash.activeUnitCampaign, null);
    });

    it('surfaces a data source failure instead of reading it as no Unit', () => {
        assert.throws(
            () => response({ stash: {}, error: { message: 'throttled', type: 'THROTTLED' } }),
            /THROTTLED: throttled/
        );
    });
});
