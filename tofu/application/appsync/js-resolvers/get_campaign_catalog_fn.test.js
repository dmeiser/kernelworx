import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_campaign_catalog_fn.js';

describe('get_campaign_catalog_fn request', () => {
    it('skips the GetItem when the catalog was batch-resolved by a parent pipeline', () => {
        const catalog = { catalogId: 'CAT-A', catalogName: 'Fall Sale' };
        const ctx = {
            prev: { result: catalog },
            source: { campaignId: 'C1', catalogId: 'CAT-A' },
        };

        const result = request(ctx);

        // runtime.earlyReturn is mocked to return its value in tests.
        assert.deepStrictEqual(result, catalog);
        assert.strictEqual(result.operation, undefined);
    });

    it('performs the singular GetItem when the source has no batch-resolved catalog', () => {
        const ctx = { source: { campaignId: 'C1', catalogId: 'CAT-A' } };

        const result = request(ctx);

        assert.deepStrictEqual(result, {
            operation: 'GetItem',
            key: { catalogId: 'CAT-A' },
        });
    });
});

describe('get_campaign_catalog_fn response', () => {
    it('returns the raw catalog item (singular path, unchanged contract)', () => {
        const catalog = { catalogId: 'CAT-A', catalogName: 'Fall Sale', isDeleted: true };
        const ctx = { result: catalog };

        assert.deepStrictEqual(response(ctx), catalog);
    });

    it('returns null when the catalog is missing', () => {
        assert.strictEqual(response({ result: null }), null);
    });

    it('propagates resolver errors', () => {
        const ctx = { error: { message: 'boom', type: 'DynamoDB:InternalServerError' } };

        assert.throws(() => response(ctx), /DynamoDB:InternalServerError: boom/);
    });
});
