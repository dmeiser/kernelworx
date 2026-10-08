import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import { PUBLIC_ORDER_CAP, PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 3 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): read
// the anchor campaign and pre-check the order cap.
//
// The GetItem is keyed by the stashed profile's own partition key plus the
// canonical campaign id step 2 took from the STORED settings blob. That is a
// deliberate improvement over get_campaign_for_order_fn.js, which Queries the
// campaignId-index GSI: a strong base-table read under the owner's key cannot
// return another profile's campaign, and it is not exposed to the GSI's
// eventual consistency.
//
// The cap pre-check here is a cheap early reject only. The authoritative bound
// is the ConditionExpression of the increment step: N concurrent writers at 499
// all pass a read-side check, and only the atomic ADD's condition makes the
// bound hold. PUBLIC_ORDER_LIMIT_EXCEEDED is non-retryable on purpose -
// RESOURCE_BUSY would tell the buyer to retry a permanent condition.
export function request(ctx) {
    const profileId = ctx.stash ? ctx.stash.profileId : null;
    const campaignId = ctx.stash ? ctx.stash.campaignId : null;

    if (!profileId || !campaignId) {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
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
        // The anchor is gone (deleted, or a pointer left by a partial delete).
        // Same NOT_FOUND as the token branches: a dead anchor is not the
        // buyer's error and must not read as one.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Back-compat default shared with get_campaign_for_order_fn.js and
    // lookup_public_settings_campaign_fn.js: campaigns written before isActive
    // existed carry no attribute, and absence means active.
    const active = campaign.isActive == null ? true : campaign.isActive === true;
    if (!active) {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // An absent counter is zero orders served, not a missing attribute to fail
    // on: the counter is created by this same write path.
    const served = typeof campaign.publicOrderCount === 'number' ? campaign.publicOrderCount : 0;
    if (served >= PUBLIC_ORDER_CAP) {
        util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
        return null;
    }

    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
        return null;
    }

    ctx.stash.campaign = campaign;
    // Normalized here so the reused get_catalog step (which reads
    // ctx.stash.catalogId) sees the DB key form.
    ctx.stash.catalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');

    return campaign;
}
