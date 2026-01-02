import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    // Query invites table using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
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
    ctx.stash.invitesToDelete = ctx.result.items || [];
    return ctx.result.items;
}
