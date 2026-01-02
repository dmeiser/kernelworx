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
    // Check if catalog is accessible (public or owned by user)
    const catalog = ctx.result;
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const isPublic = catalog.isPublic === true || catalog.isPublic === 'true';
    const isOwner = catalog.ownerAccountId === callerAccountId;
    if (!isPublic && !isOwner) {
        util.error('Catalog not accessible', 'Forbidden');
    }
    ctx.stash.catalog = catalog;
    return catalog;
}
