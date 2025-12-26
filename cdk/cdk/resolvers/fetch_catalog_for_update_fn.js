import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (ctx.stash.skipCatalog) {
        // Return no-op request
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: 'NOOP' })
        };
    }
    
    const catalogId = ctx.stash.catalogId;
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
        util.error('Catalog not found', 'NotFound');
    }
    
    // Store catalog in stash for UpdateOrderFn
    ctx.stash.catalog = ctx.result;
    return ctx.result;
}
