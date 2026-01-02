import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const rawCatalogId = ctx.stash.catalogId;
    if (!rawCatalogId) {
        util.error('Catalog ID not found in stash', 'BadRequest');
    }
    // Normalize to DB format: ensure it starts with CATALOG#
    const catalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : 'CATALOG#' + rawCatalogId;
    // Save normalized id back to stash so downstream functions see the DB key
    ctx.stash.catalogId = catalogId;
    console.log('GetCatalog: Looking up catalogId:', catalogId);
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
        // Include the looked-up catalogId in the error to aid debugging
        console.log('GetCatalog: No catalog found for id:', ctx.stash.catalogId);
        util.error('Catalog not found for id: ' + ctx.stash.catalogId, 'NotFound');
    }
    
    console.log('GetCatalog: Found catalog with', ctx.result.products ? ctx.result.products.length : 0, 'products');
    // Store catalog in stash for CreateOrderFn
    ctx.stash.catalog = ctx.result;
    
    return ctx.result;
}
