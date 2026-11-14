// Order origin capture has one owner (data model §5.6, API-FIX-05): both order
// minters (create_order_fn, create_public_order_fn) copy the Campaign's joined
// scope onto the Order row at creation, because the Campaign's own link is a
// latest-link that removal retains. These tests pin the three shapes that
// distinction produces.
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { orderOrigin } from './order_origin.js';

describe('orderOrigin', () => {
    it('copies the joined scope of a joined campaign', () => {
        assert.deepStrictEqual(
            orderOrigin({ unitId: 'UNIT#pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' }),
            { unitId: 'UNIT#pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' }
        );
    });

    it('records an independent campaign as null on both fields', () => {
        assert.deepStrictEqual(orderOrigin({ campaignId: 'CAMPAIGN#c1' }), { unitId: null, unitCampaignId: null });
        assert.deepStrictEqual(orderOrigin(null), { unitId: null, unitCampaignId: null });
    });

    it('records a half-linked campaign exactly as stored rather than inventing a scope', () => {
        // A join writes the pair atomically, so a lone half is pre-Stage-1 data.
        // Guessing the other half would manufacture an origin the unit never had.
        assert.deepStrictEqual(orderOrigin({ unitId: 'UNIT#crew-529' }), {
            unitId: 'UNIT#crew-529',
            unitCampaignId: null
        });
    });
});
