import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// Strongly consistent re-read of the campaign the locator step found through the
// campaignId-index GSI.
//
// The GSI Query is only able to say *where* the campaign item is: the base table
// is keyed by (profileId, campaignId), and campaignId is not enough to address it.
// Everything downstream -- the catalog assignment, the isActive gate, and the
// origin stamped on an Order -- must therefore come from this Get, not from the
// projection, which can lag a write by up to a second and would otherwise let a
// just-changed campaign decide what a just-created Order says about it.

export function request(ctx) {
    const located = (ctx.stash || {}).campaign;
    if (!located || !located.profileId || !located.campaignId) {
        util.error('Campaign not found', 'NOT_FOUND');
    }
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            profileId: String(located.profileId),
            campaignId: String(located.campaignId)
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        // The locator saw a projection the base table no longer holds: the
        // campaign was deleted between the two reads.
        util.error('Campaign not found', 'NOT_FOUND');
    }
    const campaign = ctx.result;
    if (campaign.isActive == null) {
        campaign.isActive = true;
    }
    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
    }
    ctx.stash.campaign = campaign;
    ctx.stash.catalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');
    ctx.stash.campaignId = String(campaign.campaignId);
    return campaign;
}
