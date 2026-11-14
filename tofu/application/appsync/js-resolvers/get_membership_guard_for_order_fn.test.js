import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_membership_guard_for_order_fn.js';

describe('get_membership_guard_for_order_fn request', () => {
    it('gets the guard addressed by the campaign alone, strongly', () => {
        const result = request({ stash: { campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(result.operation, 'Get');
        assert.deepStrictEqual(result.key, { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' });
    });

    it('normalizes an unprefixed campaignId to the stored DB form', () => {
        const result = request({ stash: { campaignId: 'c1' } });
        assert.strictEqual(result.key.pk, 'SCOUT_CAMPAIGN#CAMPAIGN#c1');
    });

    it('refuses to read a guard for a campaign it cannot name', () => {
        assert.throws(() => request({ stash: {} }), /INVALID_INPUT: campaignId is required to read the join guard/);
    });
});

describe('get_membership_guard_for_order_fn response', () => {
    it('stashes the guard and the Unit Campaign it points at', () => {
        const stash = {};
        const returned = response({ stash, result: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-1' } });
        assert.strictEqual(stash.activeUnitCampaignId, 'uc-1');
        assert.strictEqual(stash.membershipGuard.activeUnitCampaignId, 'uc-1');
        assert.strictEqual(returned, 'uc-1');
    });

    it('stashes no join when the guard row is absent, which is not an error', () => {
        // An independent campaign has no guard row. The Order it produces records
        // a null scope, so a later join cannot look like this sale's origin.
        const stash = {};
        assert.strictEqual(response({ stash, result: null }), null);
        assert.strictEqual(stash.membershipGuard, null);
        assert.strictEqual(stash.activeUnitCampaignId, null);
    });

    it('stashes no join for a guard whose pointer was cleared by removal', () => {
        const stash = {};
        response({ stash, result: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' } });
        assert.strictEqual(stash.activeUnitCampaignId, null);
    });

    it('surfaces a data source failure instead of reading it as no join', () => {
        assert.throws(
            () => response({ stash: {}, error: { message: 'throttled', type: 'THROTTLED' } }),
            /THROTTLED: throttled/
        );
    });
});
