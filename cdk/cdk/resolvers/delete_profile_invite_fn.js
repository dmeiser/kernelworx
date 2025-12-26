import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    const profileId = ctx.args.profileId;
    
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
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    
    // Check if caller is the owner
    if (!profile || profile.ownerAccountId !== callerAccountId) {
        util.error('Forbidden: Only profile owner can delete invites', 'Unauthorized');
    }
    
    // Store profile info for next function
    ctx.stash.profileId = ctx.args.profileId;
    ctx.stash.inviteCode = ctx.args.inviteCode;
    ctx.stash.authorized = true;
    
    return true;
}
