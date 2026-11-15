import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { currentUnitCampaignId } from './lib/order_origin.js';

// The membership guard read (§5.6): the single strongly consistent read that says
// which Unit Campaign a Scout Campaign is joined to at this moment. The Campaign
// row's own unitId/unitCampaignId pair cannot answer that -- removal keeps it --
// and the campaignId-index projection adds eventual consistency on top.
//
// Keyed by the campaign alone, so no pipeline step has to know the Unit Campaign
// to find out whether there is one.

export function request(ctx) {
    const stash = ctx.stash || {};
    const campaignId = normalizeId(stash.campaignId, 'CAMPAIGN#');
    if (!campaignId) {
        util.error('campaignId is required to read the join guard', 'INVALID_INPUT');
    }
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            pk: 'SCOUT_CAMPAIGN#' + campaignId,
            sk: 'MEMBERSHIP_GUARD'
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Absent guard row is not an error: an independent campaign has none, and the
    // origin it produces is two nulls, which is the recorded fact.
    const guard = ctx.result || null;
    ctx.stash.membershipGuard = guard;
    ctx.stash.activeUnitCampaignId = currentUnitCampaignId(guard);
    return ctx.stash.activeUnitCampaignId;
}
