import { util, runtime } from '@aws-appsync/utils';

/**
 * GetItem step of the Campaign.catalog pipeline field resolver (see #332).
 *
 * When the parent campaign already carries a batch-resolved `catalog` (list
 * queries), the read is skipped entirely. Otherwise this performs the same
 * single GetItem the previous VTL field resolver did, returning the raw
 * catalog item — including soft-deleted ones, matching the old
 * campaign_catalog_response.vtl contract.
 */
export function request(ctx) {
    // Catalog already resolved by a parent list pipeline's BatchGetItem:
    // skip the per-item read.
    const prevResult = ctx.prev ? ctx.prev.result : undefined;
    if (prevResult !== undefined && prevResult !== null) {
        return runtime.earlyReturn(prevResult);
    }
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: ctx.source.catalogId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
