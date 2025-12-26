import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // V2: Direct PK query on profileId (no GSI needed)
    return {
        operation: 'Query',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({
            ':profileId': profileId
        })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    ctx.stash.campaignsToDelete = ctx.result.items || [];
    return ctx.result.items;
}
