import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.stash.catalogId;
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
        util.error('Catalog not found', 'NotFound');
    }
    
    // Store catalog in stash for CreateOrderFn
    ctx.stash.catalog = ctx.result;
    
    return ctx.result;
}
