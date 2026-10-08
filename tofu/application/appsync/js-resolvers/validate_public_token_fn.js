import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 1 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// locate the profile through the profileId-index GSI.
//
// This is the public replacement for the write-access pair the authenticated
// pipelines run (verify_profile_write_access + _step2 + check_share_permissions)
// - there is no caller identity on the API-key auth mode, so the pair cannot
// run at all. The GSI is a LOCATOR only, never the authorization (#545): step 2
// re-reads the row from the base table consistently and the share token in the
// request is what authorizes.
//
// More than one projection is refused outright. A profile transfer leaves both
// the old and the new owner's row projected for a few seconds, and the offer
// path resolves that with a consistent read per candidate; on the write path a
// second consistent read per attempt buys nothing an immediate retry would not,
// and guessing which projection to write under is exactly the #438 hazard. The
// identical NOT_FOUND every negative branch raises is deliberate: probing a
// profile id cannot distinguish "no feature" from "bad token".
//
// Nothing here reads ctx.identity - identity is null under API_KEY, and a step
// that consulted it would fail closed on every legitimate buyer request.
export function request(ctx) {
    const input = ctx.args ? ctx.args.input : null;
    const rawProfileId = input ? input.profileId : null;
    const profileId = normalizeId(rawProfileId, 'PROFILE#');

    if (!profileId) {
        // Routed through the same NOT_FOUND as every other negative branch: a
        // malformed profile id must not disclose that the profile exists.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Stash the canonical id so step 2 and the write steps all key off the same
    // normalized value instead of re-normalizing the caller's raw argument.
    ctx.stash.profileId = profileId;

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
        // Zero: no such profile. Two: a transfer window or a corrupt projection.
        // Both answer the same way as a bad token.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const ownerAccountId = items[0].ownerAccountId;
    if (typeof ownerAccountId !== 'string' || ownerAccountId === '') {
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    // Only the partition key travels. The projected item carries the share
    // token, and the pipeline never needs it in a result the caller can read.
    ctx.stash.ownerAccountId = ownerAccountId;

    return { located: true };
}
