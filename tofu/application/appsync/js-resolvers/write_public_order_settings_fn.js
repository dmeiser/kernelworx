import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import {
    ACK_VERSION,
    acknowledgementIsBehind,
    resolveAllowedPaymentMethods,
    resolveCampaignId,
    stashedProfileId,
    storedPublicOrders
} from './lib/public_settings.js';

// ProfilesDS write step of the updateProfilePublicOrderSettings pipeline
// (#679 settings slice). One conditioned UpdateItem on the profile item, built
// from the profile the ownership pair stashed - never from the caller's
// identity, so the key cannot be steered by an argument.
//
// The whole publicOrders map is written as one attribute, merged over the
// stored blob, so disabling preserves the token and every other field (only
// `enabled` flips) and an unknown sub-attribute added by a later slice
// survives. There is deliberately NO optimistic lock against concurrent owner
// edits: the surface is owner-only, so clobbering requires the same person
// saving twice at once, and the spec accepts that trade-off. The one race that
// does matter - two first-enables minting different tokens - is closed by the
// attribute_not_exists(publicOrders.token) guard, so the loser fails instead of
// silently overwriting the winner's share URL.
//
// Argument semantics live in lib/public_settings.js so this step and the
// CampaignsDS validation step resolve omitted-vs-explicit-null identically.
export function request(ctx) {
    const args = ctx.args || {};
    const stored = storedPublicOrders(ctx);
    const profileId = stashedProfileId(ctx);

    if (!profileId) {
        // The owner gate proved a stashed profile exists; this is a wiring
        // fault, not a caller error.
        util.error('Profile not found', 'NOT_FOUND');
        return;
    }

    const ownerAccountId =
        ctx.stash && ctx.stash.profile && ctx.stash.profile.ownerAccountId
            ? ctx.stash.profile.ownerAccountId
            : normalizeIdOrPrefix(ctx.identity && ctx.identity.sub, 'ACCOUNT#');

    const enabled = args.enabled === true;
    const campaignId = resolveCampaignId(ctx);
    const methods = resolveAllowedPaymentMethods(ctx);

    if (enabled) {
        if (!campaignId) {
            util.error('campaignId is required to enable public orders', 'INVALID_INPUT');
            return;
        }
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
    if (campaignId) {
        blob.campaignId = campaignId;
    }
    if (methods !== null) {
        blob.allowedPaymentMethods = methods;
    }
    if (token) {
        blob.token = token;
    }
    // The acknowledgement is evidence, so it is stamped only when the owner
    // actually accepted it. A re-save with a current ackVersion leaves the
    // original timestamp alone.
    if (enabled && args.acknowledgementsAccepted === true) {
        blob.acknowledgedAt = util.time.nowISO8601();
        blob.ackVersion = ACK_VERSION;
    }

    const conditions = ['attribute_exists(ownerAccountId)'];
    if (minted) {
        conditions.push('attribute_not_exists(publicOrders.token)');
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: ownerAccountId, profileId: profileId }),
        update: {
            expression: 'SET publicOrders = :publicOrders, updatedAt = :updatedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':publicOrders': blob,
                ':updatedAt': util.time.nowISO8601()
            })
        },
        condition: { expression: conditions.join(' AND ') }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (
            ctx.error.type === 'DynamoDB:ConditionalCheckFailedException' ||
            (ctx.error.message && ctx.error.message.includes('ConditionalCheckFailed'))
        ) {
            // The first-enable guard: another save minted the token first, so
            // this one wrote nothing and the winner's share URL stands.
            util.error('Public order settings were already saved; try again', 'CONFLICT');
            return;
        }
        util.error(ctx.error.message, ctx.error.type);
        return;
    }
    return ctx.result;
}
