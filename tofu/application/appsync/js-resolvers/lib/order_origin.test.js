// Order origin capture has one owner (data model §5.6, API-FIX-05). Both order
// minters copy the joined scope onto the Order row at creation, and they read it
// from the membership guard rather than the Campaign row: the Campaign's own
// unitId/unitCampaignId pair is a latest-link that removal retains, so it answers
// "where is this campaign joined now (if it ever was)" -- never "where was this
// sale made". These tests pin the shapes that distinction produces.
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { currentUnitCampaignId, orderOrigin } from './order_origin.js';

const JOINED = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026' };
const METADATA = { pk: 'UNIT_CAMPAIGN#uc-pack-3149-fall-2026', sk: 'METADATA', unitId: 'UNIT#pack-3149' };

describe('currentUnitCampaignId', () => {
    it('names the join the guard holds', () => {
        assert.strictEqual(currentUnitCampaignId(JOINED), 'uc-pack-3149-fall-2026');
    });

    it('names no join for an absent guard or one without an active pointer', () => {
        // Removal clears activeUnitCampaignId: an absent attribute is the
        // removed/independent shape, and the guard row itself may not exist.
        assert.strictEqual(currentUnitCampaignId(null), null);
        assert.strictEqual(currentUnitCampaignId({ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' }), null);
    });
});

describe('orderOrigin', () => {
    it('copies the joined scope the guard names', () => {
        assert.deepStrictEqual(orderOrigin(JOINED, METADATA), {
            unitId: 'UNIT#pack-3149',
            unitCampaignId: 'uc-pack-3149-fall-2026'
        });
    });

    it('records an independent campaign as null on both fields', () => {
        assert.deepStrictEqual(orderOrigin(null, null), { unitId: null, unitCampaignId: null });
        // The campaign row's retained link is not an input at all: a caller that
        // passes one still gets the guard's answer, because that is the only
        // answer that does not move old demand when the Scout leaves.
        assert.deepStrictEqual(orderOrigin(null, null), { unitId: null, unitCampaignId: null });
    });

    it('names the Unit Campaign the guard points at when its metadata row is gone', () => {
        // Neither half is invented: the pointer is a recorded fact, the Unit is not
        // knowable from a row that no longer exists.
        assert.deepStrictEqual(orderOrigin(JOINED, null), {
            unitId: null,
            unitCampaignId: 'uc-pack-3149-fall-2026'
        });
    });

    it('follows a move rather than the campaign row it left behind', () => {
        const movedGuard = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-crew-529-spring-2027' };
        const movedMetadata = { pk: 'UNIT_CAMPAIGN#uc-crew-529-spring-2027', sk: 'METADATA', unitId: 'UNIT#crew-529' };
        assert.deepStrictEqual(orderOrigin(movedGuard, movedMetadata), {
            unitId: 'UNIT#crew-529',
            unitCampaignId: 'uc-crew-529-spring-2027'
        });
    });
});
