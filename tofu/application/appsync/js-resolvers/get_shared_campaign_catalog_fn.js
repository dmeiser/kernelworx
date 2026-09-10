import { util, runtime } from '@aws-appsync/utils';

/**
 * GetItem step of the SharedCampaign.catalog pipeline field resolver (#332).
 *
 * When the parent shared campaign already carries a batch-resolved `catalog`
 * (listMySharedCampaigns / findSharedCampaigns), the read is skipped
 * entirely. Otherwise this performs the same single GetItem the previous VTL
 * field resolver did. A soft-deleted (or missing) catalog resolves to null,
 * matching the old shared_campaign_catalog_response.vtl contract.
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
    if (!ctx.result || ctx.result.isDeleted == true) {
        return null;
    }
    return ctx.result;
}
