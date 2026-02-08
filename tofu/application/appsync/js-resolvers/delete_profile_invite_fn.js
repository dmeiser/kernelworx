import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.profileId;
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // Save normalized profileId to stash for downstream steps
    ctx.stash.profileId = dbProfileId;

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
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    
    // Check if caller is the owner
    if (!profile || profile.ownerAccountId !== callerAccountId) {
        util.error('Forbidden: Only profile owner can delete invites', 'Unauthorized');
    }
    
    // Store profile info for next function (profileId already normalized in stash)
    ctx.stash.inviteCode = ctx.args.inviteCode;
    ctx.stash.authorized = true;
    
    return true;
}
