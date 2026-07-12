import { util, runtime } from '@aws-appsync/utils';

const tableName = '${table_name}';

export function request(ctx) {
    const ordersToDelete = ctx.stash.ordersToDelete || [];

    if (ordersToDelete.length === 0) {
        return runtime.earlyReturn(true);
    }

    const keys = ordersToDelete.map((order) => util.dynamodb.toMapValues({
        campaignId: order.campaignId,
        orderId: order.orderId
    }));

    return {
        operation: 'BatchDeleteItem',
        tables: {
            [tableName]: keys
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const tableData = ctx.result && ctx.result.data ? ctx.result.data[tableName] : null;
    const unprocessed = ctx.result && ctx.result.unprocessedKeys ? ctx.result.unprocessedKeys[tableName] : null;
    if (unprocessed && unprocessed.length > 0) {
        util.error('Failed to delete ' + unprocessed.length + ' order(s)', 'InternalError');
    }
    const deleted = Array.isArray(tableData)
        ? tableData.filter((item) => item !== null).length
        : 0;
    ctx.stash.deletedOrdersCount = deleted;
    return deleted;
}
