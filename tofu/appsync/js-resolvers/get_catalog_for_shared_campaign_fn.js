import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: ctx.args.input.catalogId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found', 'NotFound');
    }
    
    // READ ACCESS: Anyone can read catalog by ID (no authorization check).
    // Security relies on UUID obscurity - catalogIds are not guessable.
    // WRITE ACCESS: Only owner can update/delete (checked in update/delete resolvers).
    const catalog = ctx.result;
    ctx.stash.catalog = catalog;
    return catalog;
}
