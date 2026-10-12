import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import {
    PUBLIC_METHOD_UNAVAILABLE,
    PUBLIC_ORDER_UNAVAILABLE,
    canonicalCampaignId,
    validateAndMapPublicOrderInput
} from './lib/public_order.js';

// Step 2 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): the
// authorization step. One strongly consistent GetItem on the base table under
// the owner the locator stashed - an item returned under that partition key
// belongs to that account right now, which the eventually consistent GSI
// projection cannot show (#438/#545).
//
// Everything the anonymous request must satisfy is decided HERE, in one place:
//   - the feature is enabled and the share token matches,
//   - the campaignId the offer echoed equals the stored anchor (D3: a seller
//     re-picking a campaign between page load and submit cannot silently
//     re-file the order into the new campaign),
//   - the payment method is on the seller's allowlist (case-insensitive). This
//     step owns allowlist membership; the write-step clone of the payment
//     method check owns only "does the method still exist on the account", and
//     both rejections share one indistinguishable message so the mutation
//     cannot enumerate the owner's stored method names,
//   - the buyer accepted the public-order terms,
//   - every input bound (names, contact, notes, line items, product id length).
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
    const ownerAccountId = ctx.stash ? ctx.stash.ownerAccountId : null;
    const profileId = ctx.stash ? ctx.stash.profileId : null;

    if (!ownerAccountId || !profileId) {
        // Wiring fault: step 1 always stashes both before this step runs.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: ownerAccountId, profileId: profileId }),
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

    const profile = ctx.result;
    const blob = profile && profile.publicOrders ? profile.publicOrders : null;
    const input = ctx.args ? ctx.args.input : null;

    // Every NOT_FOUND branch below is deliberately identical: never enabled, a
    // disabled profile, a missing blob, a bad token, and a campaign echo
    // mismatch all read the same way to a probe.
    if (!tokenMatches(blob, input ? input.token : null)) {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const storedCampaignId = canonicalCampaignId(blob.campaignId);
    const echoedCampaignId = canonicalCampaignId(input ? input.campaignId : null);
    if (!echoedCampaignId || echoedCampaignId !== storedCampaignId) {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
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

    // The canonical ids the rest of the pipeline keys on. The anchor campaign is
    // taken from the STORED blob, never from the echoed argument: equality was
    // just proven, and the stored value is the one the seller controls.
    ctx.stash.campaignId = storedCampaignId;
    ctx.stash.sellerName = typeof profile.sellerName === 'string' ? profile.sellerName : '';
    ctx.stash.publicOrder = mapped;

    return { authorized: true };
}
