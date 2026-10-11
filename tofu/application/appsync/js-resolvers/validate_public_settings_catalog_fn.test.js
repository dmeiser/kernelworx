import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_settings_catalog_fn.js';

// #679 settings slice: the write pipeline's CatalogsDS step. The anchor
// campaign's catalog is a different table, so this is a second function with a
// second datasource; enabling public orders over a missing or soft-deleted
// catalog would publish an offer with nothing buyable.

describe('validate_public_settings_catalog_fn request', () => {
    it('GetItems the catalog key the campaign step stashed', () => {
        const ctx = { stash: { publicSettingsCatalogId: 'CATALOG#cat1' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('reads nothing when the campaign step read nothing', () => {
        const ctx = { stash: {} };
        assert.strictEqual(request(ctx), null);
    });
});

describe('validate_public_settings_catalog_fn response', () => {
    it('passes a live catalog through and stashes it', () => {
        const ctx = { stash: { publicSettingsCatalogId: 'CATALOG#cat1' }, result: { catalogId: 'CATALOG#cat1', isDeleted: false } };

        const result = response(ctx);

        assert.strictEqual(result.catalogId, 'CATALOG#cat1');
        assert.strictEqual(ctx.stash.publicSettingsCatalog.catalogId, 'CATALOG#cat1');
    });

    it('treats a catalog row with no isDeleted attribute as live', () => {
        const ctx = { stash: { publicSettingsCatalogId: 'CATALOG#cat1' }, result: { catalogId: 'CATALOG#cat1' } };
        assert.strictEqual(response(ctx).catalogId, 'CATALOG#cat1');
    });

    it('rejects a missing catalog', () => {
        const ctx = { stash: { publicSettingsCatalogId: 'CATALOG#cat1' }, result: null };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: The campaign catalog no longer exists; pick a campaign with a catalog/
        );
    });

    it('rejects a soft-deleted catalog', () => {
        const ctx = {
            stash: { publicSettingsCatalogId: 'CATALOG#cat1' },
            result: { catalogId: 'CATALOG#cat1', isDeleted: true }
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: The campaign catalog has been deleted; pick a campaign with a catalog/
        );
    });

    it('re-raises a datasource error', () => {
        const ctx = {
            stash: { publicSettingsCatalogId: 'CATALOG#cat1' },
            error: { message: 'boom', type: 'DynamoDBException' }
        };

        assert.throws(() => response(ctx), /DynamoDBException: boom/);
    });
});
