import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query by PK (ownerAccountId)
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'Query',
        query: {
        expression: 'ownerAccountId = :ownerAccountId',
        expressionValues: util.dynamodb.toMapValues({ ':ownerAccountId': ownerAccountId })
        },
        limit: 500
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result.items || [];
}
