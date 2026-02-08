import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.input.profileId;
    // Normalize profileId for query
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Check ownership - ownerAccountId uses ACCOUNT# prefix now
    const profile = ctx.result.items && ctx.result.items[0];
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (!profile || profile.ownerAccountId !== expectedOwner) {
        util.error('Forbidden: Only profile owner can share profiles', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
