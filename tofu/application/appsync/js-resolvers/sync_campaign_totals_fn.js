import { util, runtime } from '@aws-appsync/utils';
import { isConditionFailure } from './lib/public_order.js';

// Denormalized campaign totals for Campaign.totalOrders / Campaign.totalRevenue
// (#746). Before this function the fields were served by unpaginated VTL COUNT
// / SUM queries per campaign, so a list of N campaigns ran 2*N DynamoDB
// queries, a campaign past the 1 MB query page returned short totals, and the
// VTL float sum drifted (19.990000000000002). The counters below ride the
// campaign item that every campaign read already fetches, so once migrated a
// campaign serves both fields with zero extra datastore calls; the VTL field
// resolvers keep their old queries as the fallback for campaigns that have
// not seen an order mutation since this shipped (same migration story as
// #331's latestCampaignId).
//
// A producer step in each authenticated order-write pipeline stashes the
// delta on ctx.stash.totalsDelta before this function runs:
//   createOrder                    count +1, revenue +totalAmount
//   updateOrder (lineItems changed)  count 0,  revenue = new - old, rounded
//   deleteOrder                    count -1, revenue -totalAmount
// publicCreateOrder is different: its resolver already carries 10 functions
// (AppSync's hard cap - adding this step fails the apply with "A resolver can
// only be composed of 10 functions"), so its totals update rides INSIDE
// create_public_order's TransactWriteItems as the conditioned UpdateItem on
// the campaign item (merged with the ARCH-1 existence guard, since DynamoDB
// rejects two operations on one item in a transaction) - atomic with the
// order row, so the partial-failure drift documented above cannot occur on
// that path.
// Order rows carry the campaigns-table key (profileId + campaignId, both
// prefix-normalized), so no lookup is needed to address the counter row.
//
// The ADD is one atomic DynamoDB operation: concurrent writers cannot lose
// each other's increments, and DynamoDB numbers are exact decimals, so the
// stored counter never accumulates binary float error. The only float exposed
// is the JS-side delta subtraction in updateOrder, which is rounded to cents
// (all order totals are cent-quantized by lib/line_items.js); serving code
// rounds to 2dp again as defense in depth.
//
// Failure semantics (mirroring increment_public_order_count_fn's documented
// trade-off): this step runs AFTER the order write, and an APPSYNC_JS
// function gets exactly one datastore call with no compensating write, so a
// failed ADD leaves the counters behind the orders table until the campaign's
// next order mutation. The mutation result is unaffected: the response passes
// the previous step's result through, so a counter sync never changes what
// the caller sees.
//
// The condition attribute_exists(campaignId) swallows the race where
// deleteCampaign removes the campaign between the order write and this ADD:
// the counter row is gone with the campaign, and delete_campaign_orders
// sweeps the orphaned order, so there is nothing to sync and no error to
// raise. Every other failure (throttle, etc.) aborts the mutation.
export function request(ctx) {
    const delta = ctx.stash ? ctx.stash.totalsDelta : null;

    // No delta means the mutation did not change order totals (an updateOrder
    // that touched no lineItems, or an idempotent deleteOrder of an order
    // that was already gone). Pass the pipeline result through untouched.
    if (!delta || (delta.count === 0 && delta.revenue === 0)) {
        return runtime.earlyReturn(ctx.prev.result);
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: delta.profileId, campaignId: delta.campaignId }),
        update: {
            expression: 'ADD #totalOrders :count, #totalRevenue :revenue',
            expressionNames: { '#totalOrders': 'totalOrders', '#totalRevenue': 'totalRevenue' },
            expressionValues: util.dynamodb.toMapValues({
                ':count': delta.count,
                ':revenue': roundToCents(delta.revenue)
            })
        },
        condition: {
            // The campaign vanished mid-mutation (concurrent deleteCampaign):
            // no counter row exists to update, which is not an error.
            expression: 'attribute_exists(campaignId)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (isConditionFailure(ctx.error)) {
            return ctx.prev.result;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }
    // The previous step's result is the mutation result (the created/updated
    // order, the delete's true, the public receipt); this step only touched
    // the campaign row, so pass it through unchanged.
    return ctx.prev.result;
}

function roundToCents(value) {
    return Math.round(value * 100) / 100;
}
