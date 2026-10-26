import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './fetch_catalog_for_update_fn.js';

describe('fetch_catalog_for_update_fn request', () => {
    it('returns no-op GetItem request when skipCatalog is true in stash', () => {
        const ctx = {
            stash: { skipCatalog: true },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'NOOP' });
    });

    it('throws INVALID_INPUT when catalogId is missing from stash', () => {
        const ctx = {
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Catalog ID not found in stash/
        );
    });

    it('normalizes raw catalogId with CATALOG# prefix and issues consistent GetItem', () => {
        const ctx = {
            stash: { catalogId: 'cat-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-123' });
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat-123');
    });

    it('preserves catalogId that already carries CATALOG# prefix', () => {
        const ctx = {
            stash: { catalogId: 'CATALOG#cat-456' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-456' });
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat-456');
    });
});

describe('fetch_catalog_for_update_fn response', () => {
    it('returns null when skipCatalog is true in stash', () => {
        const ctx = {
            stash: { skipCatalog: true },
            result: null,
        };

        const result = response(ctx);

        assert.strictEqual(result, null);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: { catalogId: 'CATALOG#cat-123' },
            error: { message: 'DynamoDB failure', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: DynamoDB failure/
        );
    });

    it('throws NOT_FOUND naming the catalogId when result is missing', () => {
        const ctx = {
            stash: { catalogId: 'CATALOG#cat-not-found' },
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Catalog not found for id: CATALOG#cat-not-found/
        );
    });

    it('stashes catalog in ctx.stash.catalog and returns result on success', () => {
        const catalog = {
            catalogId: 'CATALOG#cat-123',
            catalogName: 'Fall Popcorn',
            products: [{ productId: 'PROD#p1', name: 'Caramel Corn' }],
        };
        const ctx = {
            stash: { catalogId: 'CATALOG#cat-123' },
            result: catalog,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
        assert.deepStrictEqual(ctx.stash.catalog, catalog);
    });
});
