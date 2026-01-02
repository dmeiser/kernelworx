import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'Query',
        index: 'isPublic-createdAt-index',
        query: {
            expression: 'isPublicStr = :isPublicStr',
            expressionValues: util.dynamodb.toMapValues({ ':isPublicStr': 'true' })
        },
        filter: {
            expression: 'attribute_not_exists(isDeleted) OR isDeleted = :false',
            expressionValues: util.dynamodb.toMapValues({ ':false': false })
        },
        scanIndexForward: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result.items || [];
}
