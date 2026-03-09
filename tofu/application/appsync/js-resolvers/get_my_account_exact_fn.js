import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'GetItem',
        consistentRead: true,
        key: util.dynamodb.toMapValues({ accountId: `ACCOUNT#${ctx.identity.sub}` })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    return ctx.result || null;
}
