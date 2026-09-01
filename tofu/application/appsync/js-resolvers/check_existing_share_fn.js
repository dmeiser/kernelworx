import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const profileId = input.profileId || (ctx.stash && ctx.stash.invite ? ctx.stash.invite.profileId : undefined);
    const targetAccountId = ctx.stash ? ctx.stash.targetAccountId : undefined;
    
    // Ensure targetAccountId has ACCOUNT# prefix when querying the shares table
    const dbTargetAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#')
        ? targetAccountId
        : (targetAccountId ? `ACCOUNT#${targetAccountId}` : targetAccountId);
    
    // Store clean ID (without ACCOUNT# prefix) for stash consistency
    const cleanTargetAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#')
        ? targetAccountId.substring(8)
        : targetAccountId;
    if (ctx.stash) {
        ctx.stash.cleanTargetAccountId = cleanTargetAccountId;
    }
    
    // Normalize profileId to ensure PROFILE# prefix is used when querying shares table
    const dbProfileId = profileId && profileId.startsWith('PROFILE#')
        ? profileId
        : (profileId ? `PROFILE#${profileId}` : profileId);

    // Query shares table directly by PK+SK
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            profileId: dbProfileId,
            targetAccountId: dbTargetAccountId,
        }),
        consistentRead: true,
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store existing share info (if any) for CreateShareFn to reference
    if (ctx.result && ctx.result.profileId && ctx.stash) {
        ctx.stash.existingShare = ctx.result;
    }
    
    return ctx.result;
}
