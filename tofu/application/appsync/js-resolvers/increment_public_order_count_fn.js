import { util } from '@aws-appsync/utils';
import { PUBLIC_ORDER_CAP, isConditionFailure } from './lib/public_order.js';

// Step 6 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): the
// cap gate. This is where the 500-order bound is ENFORCED - the counter is the
// enforcement point, not a UI number, because the bound rides the condition
// expression of an atomic ADD.
//
// Why the condition carries the bound: a plain read-then-write overshoots. N
// concurrent writers at 499 all pass a pre-read, and the ADD's atomicity
// prevents lost updates but not bound breaches. `attribute_not_exists(...) OR
// publicOrderCount < :cap` makes the counter itself decide, so overshoot past
// the cap is impossible and the loser of the race writes no order row at all
// (the pipeline aborts before step 7).
//
// Why the increment runs BEFORE the PutItem, and why no compensation exists: an
// APPSYNC_JS function gets exactly one datastore call, and a failed step aborts
// the pipeline before any later step could undo the increment - so a compensating
// ADD -1 is not implementable in this shape. The drift direction is therefore
// OVERCOUNT: a create whose write step fails burns one unit of cap. Accepted in
// the spec - the bound is an abuse ceiling, and occasional overcount on internal
// failures stays within its stated meaning. The counter is never decremented,
// not even when an order is deleted, which is why the settings copy says the
// count includes deleted orders.
//
// `publicOrderCount` is escaped as an expression-name placeholder rather than
// written bare: it is not a DynamoDB reserved word today, but a name that
// contains one (`count`) is exactly the kind of identifier that starts failing
// with a ValidationException after an unrelated refactor, and the placeholder
// costs nothing.
export function request(ctx) {
    const profileId = ctx.stash ? ctx.stash.profileId : null;
    const campaignId = ctx.stash ? ctx.stash.campaignId : null;

    if (!profileId || !campaignId) {
        // Wiring fault: steps 1-3 stash both before this step runs.
        util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
        return null;
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        update: {
            expression: 'ADD #publicOrderCount :one',
            expressionNames: { '#publicOrderCount': 'publicOrderCount' },
            expressionValues: util.dynamodb.toMapValues({ ':one': 1 })
        },
        condition: {
            // attribute_exists(campaignId) is the row-existence guard: the
            // campaign cannot be deleted between step 3's read and this write
            // without the increment refusing to run.
            expression:
                'attribute_exists(campaignId) AND (attribute_not_exists(#publicOrderCount) OR #publicOrderCount < :cap)',
            expressionNames: { '#publicOrderCount': 'publicOrderCount' },
            expressionValues: util.dynamodb.toMapValues({ ':cap': PUBLIC_ORDER_CAP })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (isConditionFailure(ctx.error)) {
            // At the cap (or the campaign row vanished). No order row was
            // written, and the counter is unchanged - the condition failed, so
            // the ADD did not apply.
            util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    return ctx.result;
}
