import { util, runtime } from '@aws-appsync/utils';

// CatalogsDS validation step of the updateProfilePublicOrderSettings pipeline
// (#679 settings slice). The anchor campaign's catalog lives in a different
// table, so this is a second function with a second datasource - one GetItem.
//
// A public buyer picks products from this catalog, so enabling public orders
// over a catalog that is gone or soft-deleted would publish an offer with no
// buyable products. Both cases are INVALID_INPUT: the seller's own campaign
// points at a catalog they deleted, which is a fixable input problem (re-point
// the campaign or restore the catalog), not a missing-resource 404 for the
// settings form.
//
// Products are not individually soft-deletable - the flag is catalog-level
// only - so the catalog row is the whole check.
export function request(ctx) {
    const catalogId = ctx.stash ? ctx.stash.publicSettingsCatalogId : null;
    if (!catalogId) {
        // The campaign step read nothing (a disable-only save), so there is no
        // catalog to confirm.
        return runtime.earlyReturn(null);
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const catalog = ctx.result;
    if (!catalog) {
        util.error('The campaign catalog no longer exists; pick a campaign with a catalog', 'INVALID_INPUT');
        return;
    }
    if (catalog.isDeleted === true) {
        util.error('The campaign catalog has been deleted; pick a campaign with a catalog', 'INVALID_INPUT');
        return;
    }

    if (ctx.stash) {
        ctx.stash.publicSettingsCatalog = catalog;
    }
    return catalog;
}
