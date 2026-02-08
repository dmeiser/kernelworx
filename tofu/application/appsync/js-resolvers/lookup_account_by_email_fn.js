import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const email = ctx.args.input.targetAccountEmail;
    return {
        operation: 'Query',
        index: 'email-index',
        query: {
        expression: 'email = :email',
        expressionValues: util.dynamodb.toMapValues({ ':email': email })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('No account found with email ' + ctx.args.input.targetAccountEmail, 'NotFound');
    }
    
    const account = ctx.result.items[0];
    // accountId is now the primary key directly
    ctx.stash.targetAccountId = account.accountId;
    
    return account;
}
