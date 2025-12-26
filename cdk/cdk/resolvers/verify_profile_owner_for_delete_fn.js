import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    // ownerAccountId now has 'ACCOUNT#' prefix
    if (profile.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can delete profile', 'Unauthorized');
    }
    // Store for next steps
    ctx.stash.profileId = ctx.args.profileId;
    ctx.stash.ownerAccountId = profile.ownerAccountId;
    return profile;
}
