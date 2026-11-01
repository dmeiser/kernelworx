import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import {
    PUBLIC_METHOD_UNAVAILABLE,
    PUBLIC_ORDER_CAP,
    PUBLIC_ORDER_UNAVAILABLE,
    validateAndMapPublicOrderInput
} from './lib/public_order.js';
import { campaignIsActive } from './lib/public_settings.js';

// Step 2 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): the
// authorization step. One strongly consistent GetItem on the campaign under the
// partition key the locator stashed - an item returned under that key is the
// anchor campaign right now, which the eventually consistent GSI projection
// cannot show (#438/#545).
//
// Everything the anonymous request must satisfy is decided HERE, in one place:
//   - the feature is enabled and the share token matches,
//   - the campaign is still active,
//   - the campaign still has a catalog, and has not hit its order cap (the
//     pre-check here is a cheap early reject; the authoritative bound is the
//     increment step's condition),
//   - the payment method is on the seller's allowlist (case-insensitive). This
//     step owns allowlist membership; the write-step clone of the payment
//     method check owns only "does the method still exist on the account", and
//     both rejections share one indistinguishable message so the mutation
//     cannot enumerate the owner's stored method names,
//   - the buyer accepted the public-order terms,
//   - every input bound (names, contact, notes, line items, product id length).
//
// There is no campaignId echo check: the campaign IS the anchor, located by the
// request's own campaignId in step 1, so there is no second stored id to agree
// with. The seller's display name is NOT stashed here - it is read with the
// profile in step 3 - so a transfer-window stale read of the display name is
// the accepted, cosmetic failure mode.
//
// On success the validated, mapped field set goes into the stash and every
// later step reads the stash - never ctx.args.input. create_order_fn.js reads
// the raw input; the public clone must not, because the values that passed the
// checks are the trimmed, bounded ones, not the caller's originals.
//
// The token compare is a plain `===`. Constant-time comparison exists only on
// the Python offer path (hmac.compare_digest); the APPSYNC_JS runtime has no
// equivalent. That is a stated trade-off, not an oversight: the token is a
// ~122-bit random value over a network whose jitter dwarfs any timing signal.
export function request(ctx) {
    const profileId = ctx.stash ? ctx.stash.profileId : null;
    const campaignId = ctx.stash ? ctx.stash.campaignId : null;

    if (!profileId || !campaignId) {
        // Wiring fault: step 1 always stashes both before this step runs.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        consistentRead: true
    };
}

function tokenMatches(blob, submittedToken) {
    if (!blob || blob.enabled !== true) {
        return false;
    }
    const stored = blob.token;
    return typeof stored === 'string' && stored !== '' && typeof submittedToken === 'string'
        && submittedToken !== '' && submittedToken === stored;
}

function allowlistCovers(blob, paymentMethod) {
    const allowed = blob && Array.isArray(blob.allowedPaymentMethods) ? blob.allowedPaymentMethods : [];
    const target = paymentMethod.toLowerCase();
    for (const name of allowed) {
        if (typeof name === 'string' && name.trim().toLowerCase() === target) {
            return true;
        }
    }
    return false;
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const campaign = ctx.result;
    if (!campaign) {
        // The anchor is gone (deleted, or a projection left by a partial delete).
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const blob = campaign.publicOrders ? campaign.publicOrders : null;
    const input = ctx.args ? ctx.args.input : null;

    // Every NOT_FOUND branch below is deliberately identical: never enabled, a
    // disabled campaign, a missing blob, a bad token, and a dead campaign all
    // read the same way to a probe.
    if (!tokenMatches(blob, input ? input.token : null)) {
        // Marker counted by the public-token-mismatch CloudWatch metric filter
        // (tofu/application/modules/alarms/): a probe flood of bad tokens
        // answers HTTP 200 and is invisible to the AppSync 4XXError alarm.
        // Marker only - no token material, no caller PII.
        console.error('PUBLIC_ORDER_TOKEN_MISMATCH');
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Back-compat default shared with get_campaign_for_order_fn.js and
    // lookup_public_settings_campaign_fn.js: campaigns written before isActive
    // existed carry no attribute, and absence means active.
    const active = campaignIsActive(campaign);
    if (!active) {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Cap pre-check (cheap early reject; the authoritative gate is step 6).
    const served = typeof campaign.publicOrderCount === 'number' ? campaign.publicOrderCount : 0;
    if (served >= PUBLIC_ORDER_CAP) {
        util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
        return null;
    }

    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
        return null;
    }

    // INVALID_INPUT from here on: these are complaints about a request that is
    // already authorized, so they cannot become an existence oracle.
    if (input.acknowledgementsAccepted !== true) {
        util.error('The public order terms must be accepted', 'INVALID_INPUT');
        return null;
    }

    const mapped = validateAndMapPublicOrderInput(input);
    if (mapped === null) {
        return null;
    }

    if (!allowlistCovers(blob, mapped.paymentMethod)) {
        // The same message the AccountsDS clone emits, so a caller cannot tell a
        // method off the allowlist from one the seller deleted from the account.
        util.error(PUBLIC_METHOD_UNAVAILABLE, 'INVALID_INPUT');
        return null;
    }

    // The canonical ids the rest of the pipeline keys on. The campaign row read
    // here is the one every later step (and the order row itself) keys off.
    ctx.stash.campaign = campaign;
    // The throttle step (step 3) keys its fixed-window item off the SERVER-side
    // token just validated, never the caller's raw argument - a caller cannot
    // pick a fresh throttle identity by reformatting their token.
    ctx.stash.publicOrderToken = typeof blob.token === 'string' ? blob.token : '';
    // Normalized here so the reused get_catalog step (which reads
    // ctx.stash.catalogId) sees the DB key form.
    ctx.stash.catalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');
    ctx.stash.publicOrder = mapped;

    return { authorized: true };
}
