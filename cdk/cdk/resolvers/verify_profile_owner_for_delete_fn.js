import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
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
        util.error('Profile not found', 'NotFound');
    }
    // ownerAccountId now has 'ACCOUNT#' prefix
    if (profile.ownerAccountId !== 'ACCOUNT#' + ctx.identity.sub) {
        util.error('Forbidden: Only profile owner can delete profile', 'Unauthorized');
    }
    // Store profileId with prefix for next steps (DynamoDB operations need the prefix)
    ctx.stash.profileId = profile.profileId;  // This has PROFILE# prefix from DynamoDB
    ctx.stash.ownerAccountId = profile.ownerAccountId;
    return profile;
}
