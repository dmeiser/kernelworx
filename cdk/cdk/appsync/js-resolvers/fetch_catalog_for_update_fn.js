import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (ctx.stash.skipCatalog) {
        // Return no-op request
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: 'NOOP' })
        };
    }
    
    const rawCatalogId = ctx.stash.catalogId;
    if (!rawCatalogId) {
        util.error('Catalog ID not found in stash', 'BadRequest');
    }
    // Normalize to DB format: ensure it starts with CATALOG#
    const catalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : 'CATALOG#' + rawCatalogId;
    ctx.stash.catalogId = catalogId;
    // Direct GetItem on catalogs table using catalogId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.stash.skipCatalog) {
        return null;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result) {
        // Include the looked-up catalogId in the error to aid debugging
        util.error('Catalog not found for id: ' + ctx.stash.catalogId, 'NotFound');
    }
    
    // Store catalog in stash for UpdateOrderFn
    ctx.stash.catalog = ctx.result;
    return ctx.result;
}
