import { util } from '@aws-appsync/utils';
import { normalizeId, normalizeIdOrPrefix, stripIdPrefix } from './lib/ids.js';

export function request(ctx) {
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const profileId = input.profileId || (ctx.stash && ctx.stash.invite ? ctx.stash.invite.profileId : undefined);
    const targetAccountId = ctx.stash ? ctx.stash.targetAccountId : undefined;
    
    // Ensure targetAccountId has ACCOUNT# prefix when querying the shares table
    const dbTargetAccountId = targetAccountId ? normalizeId(targetAccountId, 'ACCOUNT#') : targetAccountId;
    
    // Store clean ID (without ACCOUNT# prefix) for stash consistency
    const cleanTargetAccountId = stripIdPrefix(targetAccountId, 'ACCOUNT#');
    if (ctx.stash) {
        ctx.stash.cleanTargetAccountId = cleanTargetAccountId;
    }
    
    // Normalize profileId to ensure PROFILE# prefix is used when querying shares table;
    // a missing profileId passes through untouched, exactly as before (#534).
    const dbProfileId = profileId ? normalizeId(profileId, 'PROFILE#') : profileId;

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
