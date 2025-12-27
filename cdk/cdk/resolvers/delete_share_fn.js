import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    var targetAccountId = ctx.args.input.targetAccountId;
    
    // Strip ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(8);
    }
    // Also strip old SHARE#ACCOUNT# prefix if present
    if (targetAccountId && targetAccountId.startsWith('SHARE#ACCOUNT#')) {
        targetAccountId = targetAccountId.substring(14);
    }
    // Also strip old SHARE# prefix if present
    if (targetAccountId && targetAccountId.startsWith('SHARE#')) {
        targetAccountId = targetAccountId.substring(6);
    }
    
    // Normalize profileId to ensure PROFILE# prefix is used in delete key
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;

    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
        profileId: dbProfileId, 
        targetAccountId: targetAccountId 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
