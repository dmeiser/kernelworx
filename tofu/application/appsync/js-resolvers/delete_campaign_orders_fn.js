import { util, runtime } from '@aws-appsync/utils';

// WARNING: this file is loaded via Terraform templatefile() (see
// modules/appsync/functions_campaigns.tf), so every `${...}` below is
// Terraform-interpolated, not a JS template literal. `${table_name}` is the
// only intended placeholder; do NOT add other `${...}` sequences here —
// Terraform will try to substitute them and the plan will fail or substitute
// the wrong value. (Switching to file() is deferred per #284.)
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
