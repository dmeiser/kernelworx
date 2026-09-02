import { util } from '@aws-appsync/utils';

const NOOP_CAMPAIGN_ID = 'NOOP';
const NOOP_ORDER_ID = 'NOOP';

export function request(ctx) {
    const order = ctx.stash.order;

    // If the lookup did not find the order, the delete was skipped and there is
    // nothing to verify. Issue a no-op read so the pipeline can return true.
    if (!order) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ campaignId: NOOP_CAMPAIGN_ID, orderId: NOOP_ORDER_ID }),
            consistentRead: true
        };
    }

    // Confirm the order is actually gone before reporting success. The
    // orderId-index GSI is eventually consistent, so a GSI read can keep
    // showing a deleted row for an unbounded time; a strongly consistent
    // base-table read deterministically reflects the completed delete.
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (!ctx.stash.order) {
        return true;
    }

    // ctx.result is the item for GetItem, or null when it is absent. If the
    // row is still present the delete did not take effect; the delete is
    // idempotent, so the caller may retry it.
    if (ctx.result) {
        util.error('Order deletion could not be confirmed; please retry', 'ConflictException');
    }

    return true;
}
