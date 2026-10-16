import { util } from '@aws-appsync/utils';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 3 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// fetch the profile for the owner account id and the seller display name.
//
// Step 1-2 located and authorized the campaign; the campaign row carries the
// profile's partition key but not its owner, so the owner account (the
// payment-method account the write validates against) and the seller's display
// name (denormalized into the order row in the create step) come from the
// profile. The GSI is a locator only: a transfer window leaves both the old
// and the new owner's row projected for a few seconds, and a second consistent
// read per candidate buys nothing an immediate retry would not - so a second
// projection is refused rather than guessed (the #438 hazard), and the buyer
// gets the identical NOT_FOUND every other negative branch raises.
//
// A stale owner id or display name across a transfer window is the accepted
// failure mode: the order is still written under the campaign's profile key,
// and the write step's account read answers with the same enumeration-safe message
// either way.
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

    // The owner key the account read (step 5) keys off, and the display name
    // the create step (step 7) denormalizes into the order row.
    ctx.stash.ownerAccountId = ownerAccountId;
    ctx.stash.sellerName = typeof items[0].sellerName === 'string' ? items[0].sellerName : '';

    return { located: true };
}
