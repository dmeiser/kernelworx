import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    var targetAccountId = ctx.args.input.targetAccountId;
    
    // Normalize profileId to ensure PROFILE# prefix is used in delete key
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    // Normalize targetAccountId to ensure ACCOUNT# prefix (shares are stored with prefix)
    const dbTargetAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#') 
        ? targetAccountId 
        : `ACCOUNT#${targetAccountId}`;

    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
        profileId: dbProfileId, 
        targetAccountId: dbTargetAccountId 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
