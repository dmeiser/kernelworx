import { util, runtime } from '@aws-appsync/utils';

// Campaign.totalOrders field resolver (#746).
//
// Two read paths, same semantics as the VTL resolver this replaces:
//   1. Migrated campaigns carry the denormalized counter on the item (written
//      by sync_campaign_totals_fn / create_public_order's transaction), so
//      list/get reads serve the field with zero extra datastore calls.
//   2. Campaigns that predate the counters (or lost a sync to a partial
//      failure) fall back to the COUNT Query the field always ran.
//
// The null check is key presence by value: a counter of 0 after deleting the
// last order is a real value, not a missing one - only an absent (null or
// undefined) attribute takes the fallback.
export function request(ctx) {
    if (ctx.source.totalOrders !== undefined && ctx.source.totalOrders !== null) {
        return runtime.earlyReturn(ctx.source.totalOrders);
    }

    return {
        operation: 'Query',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': ctx.source.campaignId })
        },
        select: 'COUNT'
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // COUNT Query: scannedCount is the matched item count (a 1 MB page caps
    // this fallback, which is why the counter path above is the answer).
    return ctx.result.scannedCount;
}
