import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_source_catalog_fn.js';

describe('check_source_catalog_fn', () => {
    it('surfaces a batch-resolved catalog from the source object', () => {
        const catalog = { catalogId: 'CAT-A', catalogName: 'Fall Sale' };
        const ctx = { source: { campaignId: 'C1', catalogId: 'CAT-A', catalog: catalog } };

        assert.deepStrictEqual(response(ctx), catalog);
    });

    it('surfaces an explicit null catalog (batch-confirmed missing)', () => {
        const ctx = { source: { campaignId: 'C1', catalogId: 'CAT-MISSING', catalog: null } };

        assert.strictEqual(response(ctx), null);
    });

    it('returns undefined when the source has no catalog (singular path)', () => {
        const ctx = { source: { campaignId: 'C1', catalogId: 'CAT-A' } };

        assert.strictEqual(response(ctx), undefined);
    });

    it('returns undefined when the source is null', () => {
        assert.strictEqual(response({ source: null }), undefined);
    });

    it('request is a no-op on the NONE datasource', () => {
        assert.deepStrictEqual(request({}), {});
    });
});
