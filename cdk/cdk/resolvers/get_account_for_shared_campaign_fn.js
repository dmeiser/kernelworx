import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // accountId has ACCOUNT# prefix in DynamoDB
    const accountId = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ accountId: accountId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Account not found', 'NotFound');
    }
    ctx.stash.account = ctx.result;
    return ctx.result;
}
