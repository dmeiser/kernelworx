import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// Step 5b of the createOrder pipeline: one strongly consistent base-table
// GetItem for the campaign whose order is about to be written. The GSI
// locator step (campaignId-index) before this one cannot serve ConsistentRead,
// so its projection can still show a pre-join campaign inside the index
// replication window - the same eventually-consistent-GSI class the repo
// rejects for authorization (#438/#545). ORD-API-01 reads the scope the
// create step stamps (unitId / unitCampaignId) off the base item guarded by
// this step instead.
export function request(ctx) {
    const located = (ctx.stash && ctx.stash.campaign) || null;
    const profileId = located ? located.profileId : null;
    const campaignId = located ? located.campaignId : null;
    if (!profileId || !campaignId) {
        // Wiring fault: the locator always stashes the campaign first.
        util.error('Campaign not found', 'NOT_FOUND');
        return null;
    }
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const campaign = ctx.result;
    if (!campaign) {
        util.error('Campaign not found', 'NOT_FOUND');
        return null;
    }

    // Back-compat default shared with get_campaign_for_order_fn.js: campaigns
    // written before isActive existed carry no attribute, and absence means
    // active.
    if (campaign.isActive == null) {
        campaign.isActive = true;
    }

    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
        return null;
    }

    // Replace the stashed (potentially stale) locator projection with the
    // strongly consistent item, and refresh the stashed catalog id with it.
    ctx.stash.campaign = campaign;
    ctx.stash.catalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');
    return campaign;
}
