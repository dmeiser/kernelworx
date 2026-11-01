import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_settings_catalog_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the settings-write catalog gate. A public
// buyer picks products from this catalog, so enabling over a missing or
// soft-deleted catalog would publish an offer with nothing buyable.

describe('validate_public_settings_catalog_fn request', () => {
    it('GetItems the catalog the campaign step named, consistently', () => {
        const ctx = { stash: { publicSettingsCatalogId: 'CATALOG#cat-1' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('reads nothing when the save is not publishing (disable, rotate, method list)', () => {
        assert.strictEqual(request({ stash: {} }), null);
        assert.strictEqual(request({}), null);
    });
});

describe('validate_public_settings_catalog_fn response', () => {
    it('accepts a live catalog and stashes it', () => {
        const ctx = { stash: {}, result: { catalogId: 'CATALOG#cat-1', isDeleted: false } };

        assert.deepStrictEqual(response(ctx), ctx.result);
        assert.deepStrictEqual(ctx.stash.publicSettingsCatalog, ctx.result);
    });

    it('rejects a missing catalog with INVALID_INPUT, not a 404', () => {
        assert.throws(
            () => response({ stash: {}, result: null }),
            /INVALID_INPUT: The campaign catalog no longer exists/
        );
    });

    it('rejects a soft-deleted catalog with INVALID_INPUT', () => {
        assert.throws(
            () => response({ stash: {}, result: { catalogId: 'CATALOG#cat-1', isDeleted: true } }),
            /INVALID_INPUT: The campaign catalog has been deleted/
        );
    });

    it('propagates a datasource error unchanged', () => {
        const ctx = { error: { message: 'Throttled', type: 'DynamoDB:ThrottlingException' } };

        assert.throws(() => response(ctx), /DynamoDB:ThrottlingException: Throttled/);
    });
});
