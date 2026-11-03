import { util, runtime } from '@aws-appsync/utils';

// Campaign.totalRevenue field resolver (#746).
//
// Two read paths, same semantics as the VTL resolver this replaced:
//   1. Migrated campaigns carry the denormalized counter on the item, served
//      directly - the stored DynamoDB decimal is exact to cents by
//      construction (every writer sends cent-quantized values), so no
//      rounding is needed on this path. Math.round stays as defense in depth
//      against a future writer that skips the cents quantization.
//   2. Campaigns that predate the counters fall back to projecting
//      totalAmount and summing. That sum runs in IEEE-754 doubles and drifts
//      (three 19.99 orders give 59.970000000000006), so it is rounded to
//      cents here - VTL has no rounding helper ($util.math only offers
//      random*), which is why this resolver is APPSYNC_JS and not a mapping
//      template.
export function request(ctx) {
    if (ctx.source.totalRevenue !== undefined && ctx.source.totalRevenue !== null) {
        return runtime.earlyReturn(roundToCents(ctx.source.totalRevenue));
    }

    return {
        operation: 'Query',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': ctx.source.campaignId })
        },
        projection: {
            expression: 'totalAmount'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    let total = 0;
    for (const order of ctx.result.items) {
        total += order.totalAmount;
    }
    return roundToCents(total);
}

function roundToCents(value) {
    return Math.round(value * 100) / 100;
}
