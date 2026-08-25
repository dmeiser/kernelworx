import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_catalog_fn.js';

describe('get_catalog_fn request', () => {
    it('normalizes an unprefixed catalogId to the DB key format', () => {
        const ctx = { stash: { catalogId: 'abc-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.catalogId, 'CATALOG#abc-123');
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#abc-123');
    });

    it('keeps an already-prefixed catalogId unchanged', () => {
        const ctx = { stash: { catalogId: 'CATALOG#abc-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.catalogId, 'CATALOG#abc-123');
    });

    it('errors when no catalogId is in stash', () => {
        const ctx = { stash: {} };

        assert.throws(
            () => request(ctx),
            /BadRequest: Catalog ID not found in stash/
        );
    });
});

describe('get_catalog_fn response', () => {
    it('stashes and returns the found catalog', () => {
        const catalog = { catalogId: 'CATALOG#abc-123', products: [{ productId: 'PRODUCT#1' }] };
        const ctx = { stash: {}, result: catalog };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
        assert.strictEqual(ctx.stash.catalog, catalog);
    });

    it('errors when the catalog is not found', () => {
        const ctx = { stash: { catalogId: 'CATALOG#missing' }, result: null };

        assert.throws(
            () => response(ctx),
            /NotFound: Catalog not found for id: CATALOG#missing/
        );
    });
});
