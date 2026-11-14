import { util } from '@aws-appsync/utils';

// Reads the Unit Campaign the join guard currently points at, strongly, to name
// the Unit an Order belongs to. When the guard names no current join the request
// returns null and the table is never called: an independent campaign's Order
// records a null scope rather than an inferred one.

export function request(ctx) {
    const unitCampaignId = ctx.stash.activeUnitCampaignId;
    if (!unitCampaignId) {
        return null;
    }
    return {
        operation: 'Get',
        key: util.dynamodb.toMapValues({
            pk: 'UNIT_CAMPAIGN#' + unitCampaignId,
            sk: 'METADATA'
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // A guard pointing at a Unit Campaign whose metadata row is gone records the
    // unitCampaignId it did name and no unitId: neither half is invented.
    ctx.stash.activeUnitCampaign = ctx.result || null;
    return ctx.stash.activeUnitCampaign;
}
