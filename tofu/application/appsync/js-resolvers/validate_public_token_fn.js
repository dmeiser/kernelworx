import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 1 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// locate the campaign through the campaignId-index GSI.
//
// This is the public replacement for the write-access pair the authenticated
// pipelines run (verify_profile_write_access + _step2 + check_share_permissions)
// - there is no caller identity on the API-key auth mode, so the pair cannot
// run at all. The GSI is a LOCATOR only, never the authorization (#545): step 2
// re-reads the row from the base table consistently and the share token in the
// request is what authorizes.
//
// A campaign belongs to exactly one profile, so the GSI projects it under one
// partition key. A second projection is a corrupt index, not a transfer window
// (campaigns are never re-keyed), and is refused rather than guessed: picking
// one of two to write under is exactly the #438 hazard. The identical NOT_FOUND
// every negative branch raises is deliberate: probing a campaign id cannot
// distinguish "no feature" from "bad token".
//
// Nothing here reads ctx.identity - identity is null under API_KEY, and a step
// that consulted it would fail closed on every legitimate buyer request.
export function request(ctx) {
    const input = ctx.args ? ctx.args.input : null;
    const rawCampaignId = input ? input.campaignId : null;
    const campaignId = normalizeId(rawCampaignId, 'CAMPAIGN#');

    if (!campaignId) {
        // Routed through the same NOT_FOUND as every other negative branch: a
        // malformed campaign id must not disclose that the campaign exists.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Stash the canonical id so step 2 and the write steps all key off the same
    // normalized value instead of re-normalizing the caller's raw argument.
    ctx.stash.campaignId = campaignId;

    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        limit: 2
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const items = (ctx.result && ctx.result.items) || [];
    if (items.length !== 1) {
        // Zero: no such campaign. Two: a corrupt projection.
        // Both answer the same way as a bad token.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const profileId = items[0].profileId;
    if (typeof profileId !== 'string' || profileId === '') {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Only the partition key travels. The projected item carries the share
    // token, and the pipeline never needs it in a result the caller can read.
    ctx.stash.profileId = profileId;

    return { located: true };
}
