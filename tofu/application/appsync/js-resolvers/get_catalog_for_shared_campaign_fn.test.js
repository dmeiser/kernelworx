import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_catalog_for_shared_campaign_fn.js';

describe('get_catalog_for_shared_campaign_fn request', () => {
    it('requests the catalog by catalogId from input', () => {
        const ctx = {
            args: { input: { catalogId: 'catalog-abc' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'catalog-abc' });
    });
});

describe('get_catalog_for_shared_campaign_fn response', () => {
    it('stashes and returns a non-deleted catalog', () => {
        const catalog = { catalogId: 'catalog-abc', products: [] };
        const ctx = { stash: {}, result: catalog };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
        assert.strictEqual(ctx.stash.catalog, catalog);
    });

    it('throws NotFound when the catalog does not exist', () => {
        const ctx = { stash: {}, result: null };

        assert.throws(
            () => response(ctx),
            /NotFound: Catalog not found/
        );
    });

    it('throws NotFound when the catalog has been soft-deleted', () => {
        const ctx = { stash: {}, result: { catalogId: 'catalog-abc', isDeleted: true } };

        assert.throws(
            () => response(ctx),
            /NotFound: Catalog has been deleted/
        );
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB timeout', type: 'InternalServerError' },
        };

        assert.throws(
            () => response(ctx),
            /InternalServerError: DynamoDB timeout/
        );
    });
});
