import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    // Normalize profileId before querying
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
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
    const callerAccountId = ctx.identity.sub;
    
    // Profile not found
    if (!profile) {
        ctx.stash.authorized = false;
        ctx.stash.isOwner = false;
        return profile;
    }
    
    // Check if caller is the owner - ownerAccountId now has 'ACCOUNT#' prefix
    const isOwner = profile.ownerAccountId === 'ACCOUNT#' + callerAccountId;
    
    ctx.stash.authorized = isOwner;
    ctx.stash.isOwner = isOwner;
    ctx.stash.profileId = ctx.args.profileId;
    
    return profile;
}
