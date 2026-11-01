import { util } from '@aws-appsync/utils';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 3 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// LOCATE the profile on the profileId-index GSI. The GSI is a locator only,
// never the source of the owner account id: its projection is eventually
// consistent, and during a profile-ownership transfer the deleted old-owner row
// can remain projected (or be the ONLY projection) for seconds. Trusting it
// would forward the stale ownerAccountId to the payment-method read and the
// mailer Lambda, emailing buyer PII (name, email, phone, address, items) to the
// FORMER owner. Step 4 (get_profile_for_public_order_step2_fn.js) therefore
// re-reads the profile from the BASE table with a strongly consistent GetItem
// keyed by the located owner before anything else touches the owner id - the
// same confirm-ownership pattern public_orders_offer.py uses on the read path
// (#545) and the same two-function shape the authenticated pipelines use
// (fetch_profile + fetch_profile_step2, #438).
//
// A second projection is a transfer window and is refused rather than guessed
// (the #438 hazard), and the buyer gets the identical NOT_FOUND every other
// negative branch raises.
export function request(ctx) {
    const profileId = ctx.stash ? ctx.stash.profileId : null;

    if (!profileId) {
        // Wiring fault: step 1 always stashes the campaign's profile key.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
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
        // Zero: the profile is gone. Two: a transfer window. Both answer the
        // same way as a bad token.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const ownerAccountId = items[0].ownerAccountId;
    if (typeof ownerAccountId !== 'string' || ownerAccountId === '') {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Candidates only. Step 4's consistent base-table read decides whether this
    // projection is still the owner of record and re-stashes the values the
    // rest of the pipeline actually uses.
    ctx.stash.ownerAccountId = ownerAccountId;

    return { located: true };
}
