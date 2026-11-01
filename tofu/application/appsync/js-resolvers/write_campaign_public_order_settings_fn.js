import { util } from '@aws-appsync/utils';
import { isConditionFailure } from './lib/public_order.js';
import {
    ACK_VERSION,
    acknowledgementIsBehind,
    resolveAllowedPaymentMethods,
    stashedCampaignId,
    stashedProfileId,
    storedPublicOrders
} from './lib/public_settings.js';

// CampaignsDS write step of the updateCampaignPublicOrderSettings pipeline
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). One conditioned UpdateItem on the campaign
// item, keyed from the campaign the pipeline stashed - never from the caller's
// identity, so the key cannot be steered by an argument.
//
// The whole publicOrders map is written as one attribute, merged over the stored
// blob, so disabling preserves the token and every other field (only `enabled`
// flips) and an unknown sub-attribute added by a later slice survives. Because
// the map lives on the campaign item, deleting the campaign destroys the
// settings, the share token and the counter atomically with it - which is why
// rev 7 needs no campaign-delete auto-disable hook at all.
//
// The campaign's ordinary edit path (update_campaign_fn.js) builds its SET
// expression from an explicit allowlist of campaign fields and never touches
// publicOrders, so standard campaign edits cannot clobber these settings.
//
// There is deliberately NO optimistic lock against concurrent owner edits: the
// surface is owner-only, so clobbering requires the same person saving twice at
// once, and the spec accepts that trade-off. The one race that does matter - two
// first-enables minting different tokens - is closed by the
// attribute_not_exists(publicOrders.#token) guard, so the loser fails instead of
// silently overwriting the winner's share URL. `token` is a DynamoDB reserved
// word, so the condition escapes it through condition.expressionNames.
export function request(ctx) {
    const args = (ctx.args && ctx.args.input) || {};
    const stored = storedPublicOrders(ctx);
    const profileId = stashedProfileId(ctx);
    const campaignId = stashedCampaignId(ctx);

    if (!profileId || !campaignId) {
        // The owner gate proved a campaign exists; this is a wiring fault, not a
        // caller error.
        util.error('Campaign not found', 'NOT_FOUND');
        return;
    }

    const enabled = args.enabled === true;
    const methods = resolveAllowedPaymentMethods(ctx);

    if (enabled) {
        if (!methods || methods.length === 0) {
            util.error(
                'At least one payment method must be allowed to enable public orders',
                'INVALID_INPUT'
            );
            return;
        }
        if (acknowledgementIsBehind(ctx) && args.acknowledgementsAccepted !== true) {
            util.error(
                'The public order acknowledgements must be accepted to enable public orders',
                'INVALID_INPUT'
            );
            return;
        }
    }

    // Token lifecycle: minted on first enable, replaced only by an explicit
    // rotateToken, and kept through a disable so the share URL stays stable
    // across disable -> re-enable. Rotating while parked is allowed - it is the
    // only revocation path and must work without first re-enabling.
    const hadToken = !!(stored && stored.token);
    let token = hadToken ? stored.token : null;
    let minted = false;
    if (args.rotateToken === true) {
        token = util.autoId();
        minted = !hadToken;
    } else if (enabled && !token) {
        token = util.autoId();
        minted = true;
    }

    const blob = { ...stored };
    blob.enabled = enabled;
    if (methods !== null) {
        blob.allowedPaymentMethods = methods;
    }
    if (token) {
        blob.token = token;
    }
    // acknowledgedAt/ackVersion record the last acceptance the API recorded:
    // they are (re)stamped whenever a save arrives with enabled:true and
    // acknowledgementsAccepted:true, whatever the stored version says. Whether
    // the flag is required at all is the re-prompt rule's job
    // (acknowledgementIsBehind), not this stamp's.
    if (enabled && args.acknowledgementsAccepted === true) {
        blob.acknowledgedAt = util.time.nowISO8601();
        blob.ackVersion = ACK_VERSION;
    }

    // campaignId is the table's range key, so it exists on every campaign row:
    // the guard means "the campaign is still here", which is what makes a
    // concurrent deleteCampaign fail this write instead of resurrecting the
    // settings on a row that is going away.
    const conditions = ['attribute_exists(campaignId)'];
    if (minted) {
        conditions.push('attribute_not_exists(publicOrders.#token)');
    }

    const condition = { expression: conditions.join(' AND ') };
    if (minted) {
        // TOKEN is a DynamoDB reserved word: the unescaped document path is
        // rejected with a ValidationException before the condition evaluates.
        condition.expressionNames = { '#token': 'token' };
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        update: {
            expression: 'SET publicOrders = :publicOrders, updatedAt = :updatedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':publicOrders': blob,
                ':updatedAt': util.time.nowISO8601()
            })
        },
        condition
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (
            isConditionFailure(ctx.error)
        ) {
            // Either the first-enable guard (another save minted the token
            // first, so this one wrote nothing and the winner's share URL
            // stands) or a concurrent campaign delete.
            util.error('Public order settings were already saved; try again', 'CONFLICT');
            return;
        }
        util.error(ctx.error.message, ctx.error.type);
        return;
    }
    return ctx.result;
}
