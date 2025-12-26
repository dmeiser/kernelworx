import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    // Add PROFILE# prefix for DynamoDB query (field resolver strips it for API responses)
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // NEW STRUCTURE: Query profileId-index GSI to find profile
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
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile) {
        util.error('Profile not found or access denied', 'Forbidden');
    }
    // Check ownership
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (profile.ownerAccountId !== expectedOwner) {
        util.error('Profile not found or access denied', 'Forbidden');
    }
    ctx.stash.profile = profile;
    return profile;
}
