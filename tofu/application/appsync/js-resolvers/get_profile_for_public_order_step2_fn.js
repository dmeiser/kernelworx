import { util } from '@aws-appsync/utils';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 4 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): the
// OWNERSHIP CONFIRMATION. Step 3 located the profile through the eventually
// consistent profileId-index GSI and stashed a CANDIDATE ownerAccountId; this
// step proves it with a strongly consistent GetItem on the Profiles base table
// keyed {ownerAccountId, profileId} - an item returned under that key exists
// right now, which the GSI projection cannot show (#545). An absent item means
// the projection was stale (the profile was transferred or deleted out from
// under the write), and the pipeline fails closed with the same NOT_FOUND as
// every other negative branch: no payment-method read, no order write, and no
// email dispatch against a former owner's account. This closes the buyer-PII
// leak where a transfer-lag GSI projection forwarded the old owner's id to the
// mailer Lambda.
//
// Two function resources over this and the step-3 file because a pipeline may
// list a function id only once (#438).
export function request(ctx) {
    const stash = ctx.stash || {};
    const profileId = stash.profileId;
    const ownerAccountId = stash.ownerAccountId;

    if (!profileId || !ownerAccountId) {
        // Wiring fault: step 3 always stashes both before this step runs.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: ownerAccountId, profileId: profileId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const profile = ctx.result;
    const stash = ctx.stash || {};
    if (
        !profile ||
        profile.ownerAccountId !== stash.ownerAccountId ||
        profile.profileId !== stash.profileId
    ) {
        // The located projection was stale: the profile no longer exists under
        // this owner (transfer or delete won the race). Fail closed, identical
        // to a bad token, before payment validation or email dispatch.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // The seller display name and owner key the rest of the pipeline (payment
    // validation, the order row, the mailer) uses now come from the STRONGLY
    // CONSISTENT base read, not the GSI projection.
    ctx.stash.sellerName = typeof profile.sellerName === 'string' ? profile.sellerName : '';

    return { confirmed: true };
}
