import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = 'ACCOUNT#' + ctx.identity.sub;
    const preferences = ctx.args.preferences;
    const now = util.time.nowISO8601();
    
    // Use UpdateItem with attribute_exists condition to ensure account exists
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId: accountId }),
        update: {
            expression: 'SET preferences = :preferences, updatedAt = :updatedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':preferences': preferences,
                ':updatedAt': now
            })
        },
        condition: {
            expression: 'attribute_exists(accountId)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
        util.error('Account not found. Please sign out and sign in again.', 'NotFound');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
