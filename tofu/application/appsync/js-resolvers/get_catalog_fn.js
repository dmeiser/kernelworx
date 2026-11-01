import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

/**
 * Retrieves a catalog by catalogId.
 * INTERNAL: this is the catalog lookup step of the createOrder pipeline —
 * it is NOT the getCatalog query resolver. Read authorization for the
 * getCatalog query is enforced in
 * tofu/application/appsync/mapping-templates/get_catalog_response.vtl.
 */
export function request(ctx) {
    const rawCatalogId = ctx.stash.catalogId;
    if (!rawCatalogId) {
        util.error('Catalog ID not found in stash', 'INVALID_INPUT');
    }
    // Normalize to DB format: ensure it starts with CATALOG#
    const catalogId = normalizeIdOrPrefix(rawCatalogId, 'CATALOG#');
    // Save normalized id back to stash so downstream functions see the DB key
    ctx.stash.catalogId = catalogId;
    // Direct GetItem on catalogs table
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
    if (!ctx.result) {
        util.error('Catalog not found for id: ' + ctx.stash.catalogId, 'NOT_FOUND');
    }

    // Store catalog in stash for CreateOrderFn
    ctx.stash.catalog = ctx.result;
    
    return ctx.result;
}
