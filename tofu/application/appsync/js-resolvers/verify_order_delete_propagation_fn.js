import { util } from '@aws-appsync/utils';

const NOOP_ORDER_ID = 'NOOP';

export function request(ctx) {
    const order = ctx.stash.order;

    // If the lookup did not find the order, the delete was skipped and there is
    // nothing to verify. Issue a no-op query so the pipeline can return true.
    if (!order) {
        return {
            operation: 'Query',
            index: 'orderId-index',
            query: {
                expression: 'orderId = :orderId',
                expressionValues: util.dynamodb.toMapValues({ ':orderId': NOOP_ORDER_ID })
            },
            limit: 1
        };
    }

    // Verify the order is no longer visible in the orderId-index GSI before we
    // report success. If the GSI entry is still present, the caller should retry
    // the idempotent delete.
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
            expression: 'orderId = :orderId',
            expressionValues: util.dynamodb.toMapValues({ ':orderId': order.orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (!ctx.stash.order) {
        return true;
    }

    const items = ctx.result.items || [];
    if (items.length > 0) {
        util.error('Order delete propagation pending; please retry', 'ConflictException');
    }

    return true;
}
