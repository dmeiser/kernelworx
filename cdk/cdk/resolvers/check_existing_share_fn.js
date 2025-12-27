import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId || ctx.stash.invite?.profileId;
    var targetAccountId = ctx.stash.targetAccountId;
    
    // Strip ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(8);
    }
    
    // Store clean ID for later use by CreateShareFn
    ctx.stash.cleanTargetAccountId = targetAccountId;
    
    // Normalize profileId to ensure PROFILE# prefix is used when querying shares
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;

    // Query shares table directly by PK+SK
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: dbProfileId, 
        targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store existing share info (if any) for CreateShareFn to reference
    if (ctx.result && ctx.result.profileId) {
        ctx.stash.existingShare = ctx.result;
    }
    
    return ctx.result;
}
