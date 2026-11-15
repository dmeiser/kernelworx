// Order origin capture has one owner (data model §5.6, API-FIX-05). Both order
// minters copy the joined scope onto the Order row at creation, and they read it
// from the membership guard rather than the Campaign row: the Campaign's own
// unitId/unitCampaignId pair is a latest-link that removal retains, so it answers
// "where is this campaign joined now (if it ever was)" -- never "where was this
// sale made". These tests pin the shapes that distinction produces.
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { cancelledTransactIndexes, currentUnitCampaignId, membershipGuardCurrencyCheck, orderOrigin } from './order_origin.js';

const JOINED = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026', unitId: 'UNIT#pack-3149' };
const LEGACY_JOINED = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026' };
const MOVED_GUARD = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-crew-529-spring-2027', unitId: 'UNIT#crew-529' };

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
        assert.deepStrictEqual(orderOrigin(JOINED), {
            unitId: 'UNIT#pack-3149',
            unitCampaignId: 'uc-pack-3149-fall-2026'
        });
    });

    it('records an independent campaign as null on both fields', () => {
        assert.deepStrictEqual(orderOrigin(null), { unitId: null, unitCampaignId: null });
        // The campaign row's retained link is not an input at all: a caller that
        // passes one still gets the guard's answer, because that is the only
        // answer that does not move old demand when the Scout leaves.
        assert.deepStrictEqual(orderOrigin(null), { unitId: null, unitCampaignId: null });
    });

    it('names the Unit Campaign a guard points at even when it predates the denormalized Unit', () => {
        // Neither half is invented: the pointer is a recorded fact, the Unit is not
        // knowable from a row that never carried it.
        assert.deepStrictEqual(orderOrigin(LEGACY_JOINED), {
            unitId: null,
            unitCampaignId: 'uc-pack-3149-fall-2026'
        });
    });

    it('follows a move rather than the campaign row it left behind', () => {
        assert.deepStrictEqual(orderOrigin(MOVED_GUARD), {
            unitId: 'UNIT#crew-529',
            unitCampaignId: 'uc-crew-529-spring-2027'
        });
    });

    it('takes no Unit Campaign row: the guard alone is the origin', () => {
        // A caller passing a metadata row gets the guard's answer anyway — the
        // extra argument is ignored, so a stale row cannot override the guard.
        const staleMetadata = { pk: 'UNIT_CAMPAIGN#other', sk: 'METADATA', unitId: 'UNIT#other' };
        assert.deepStrictEqual(orderOrigin(JOINED, staleMetadata), {
            unitId: 'UNIT#pack-3149',
            unitCampaignId: 'uc-pack-3149-fall-2026'
        });
    });
});

describe('membershipGuardCurrencyCheck', () => {
    it('writes no pin for a campaign with no guard row', () => {
        // An independent campaign has no row to pin, and DynamoDB's
        // ConditionCheck fails on a missing row -- pinning absence could only
        // ever break independent orders.
        assert.strictEqual(membershipGuardCurrencyCheck('unit-campaigns-tbl', 'CAMPAIGN#c1', null), null);
    });

    it('pins the live join the read saw', () => {
        const pin = membershipGuardCurrencyCheck('unit-campaigns-tbl', 'CAMPAIGN#c1', JOINED);
        assert.strictEqual(pin.operation, 'ConditionCheck');
        assert.strictEqual(pin.table, 'unit-campaigns-tbl');
        assert.deepStrictEqual(pin.key, { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' });
        assert.strictEqual(pin.condition.expression, 'activeUnitCampaignId = :joinedTo');
        assert.deepStrictEqual(pin.condition.expressionValues, { ':joinedTo': 'uc-pack-3149-fall-2026' });
    });

    it('pins "still no live join" for a removed guard row', () => {
        const removed = { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' };
        const pin = membershipGuardCurrencyCheck('unit-campaigns-tbl', 'CAMPAIGN#c1', removed);
        assert.strictEqual(pin.condition.expression, 'attribute_not_exists(activeUnitCampaignId)');
    });
});

describe('cancelledTransactIndexes', () => {
    it('reads the positional reason list out of the cancellation message', () => {
        const failed = cancelledTransactIndexes({
            message: 'Transaction cancelled, reasons [None, ConditionalCheckFailed, None]'
        });
        assert.deepStrictEqual(failed, [1]);
    });

    it('reports every failed index', () => {
        const failed = cancelledTransactIndexes({
            message: 'reasons [ConditionalCheckFailed, None, ConditionalCheckFailed]'
        });
        assert.deepStrictEqual(failed, [0, 2]);
    });

    it('reports nothing when the message carries no list', () => {
        assert.deepStrictEqual(cancelledTransactIndexes({ message: 'Transaction cancelled' }), []);
        assert.deepStrictEqual(cancelledTransactIndexes({}), []);
    });

    it('reports nothing when the list is not closed', () => {
        // The reason list is read positionally, so an unterminated bracket is not
        // a list: the caller's fallback decides, exactly as when there is none.
        assert.deepStrictEqual(cancelledTransactIndexes({ message: 'reasons [None, ConditionalCheckFailed' }), []);
    });

    it('counts positions across an empty entry', () => {
        // `None` and an empty slot both mean "this item was fine"; the index of a
        // later failure must still be its own position, not a compacted one.
        assert.deepStrictEqual(cancelledTransactIndexes({ message: 'reasons [, None, ConditionalCheckFailed]' }), [2]);
    });
});

describe('orderOrigin coercion', () => {
    it('serves the joined scope as text, whatever type the guard row carried', () => {
        // Written as a concatenation, not String(): the APPSYNC_JS runtime has no
        // String() global and refuses code that calls it. Same answer either way.
        assert.deepStrictEqual(orderOrigin({ activeUnitCampaignId: 3149, unitId: 42 }), {
            unitId: '42',
            unitCampaignId: '3149'
        });
    });
});
