import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.stash.profileId;
    const ownerAccountId = ctx.stash.ownerAccountId;
    
    // NEW STRUCTURE: Delete profile using ownerAccountId as PK and profileId as SK
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
        ownerAccountId: ownerAccountId, 
        profileId: profileId 
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        // Log but don't fail - shares/invites were already deleted
        console.log('Warning: Failed to delete profile metadata', ctx.error);
    }
    return true;
}
