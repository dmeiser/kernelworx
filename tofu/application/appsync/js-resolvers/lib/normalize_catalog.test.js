import { describe, it } from 'node:test';
import assert from 'node:assert';
import { normalizeCatalogIsPublic, normalizeCatalogsIsPublic } from './normalize_catalog.js';

describe('normalizeCatalogIsPublic', () => {
    it('coerces a legacy String "true" to a Boolean', () => {
        const catalog = { catalogId: 'CAT-A', isPublic: 'true' };

        assert.deepStrictEqual(normalizeCatalogIsPublic(catalog), {
            catalogId: 'CAT-A',
            isPublic: true,
        });
    });

    it('coerces a legacy String "false" to a Boolean', () => {
        const catalog = { catalogId: 'CAT-A', isPublic: 'false' };

        assert.deepStrictEqual(normalizeCatalogIsPublic(catalog), {
            catalogId: 'CAT-A',
            isPublic: false,
        });
    });

    it('passes a native BOOL through untouched', () => {
        const catalog = { catalogId: 'CAT-A', isPublic: false };

        assert.deepStrictEqual(normalizeCatalogIsPublic(catalog), {
            catalogId: 'CAT-A',
            isPublic: false,
        });
    });

    it('leaves items without isPublic alone', () => {
        const catalog = { catalogId: 'CAT-A' };

        assert.deepStrictEqual(normalizeCatalogIsPublic(catalog), { catalogId: 'CAT-A' });
    });

    it('passes null and undefined through', () => {
        assert.strictEqual(normalizeCatalogIsPublic(null), null);
        assert.strictEqual(normalizeCatalogIsPublic(undefined), undefined);
    });
});

describe('normalizeCatalogsIsPublic', () => {
    it('normalizes each item in a list', () => {
        const catalogs = [
            { catalogId: 'CAT-A', isPublic: 'true' },
            { catalogId: 'CAT-B', isPublic: false },
            { catalogId: 'CAT-C', isPublic: 'false' },
        ];

        assert.deepStrictEqual(normalizeCatalogsIsPublic(catalogs), [
            { catalogId: 'CAT-A', isPublic: true },
            { catalogId: 'CAT-B', isPublic: false },
            { catalogId: 'CAT-C', isPublic: false },
        ]);
    });

    it('passes non-array inputs through', () => {
        assert.strictEqual(normalizeCatalogsIsPublic(null), null);
        assert.strictEqual(normalizeCatalogsIsPublic(undefined), undefined);
    });
});
