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
    
    // Access rules (public/private visibility, soft-delete, ownership) are enforced
    // by the getCatalog response template and the Campaign.catalog /
    // SharedCampaign.catalog field response templates.
    const catalog = ctx.result;
    ctx.stash.catalog = catalog;
    return catalog;
}
