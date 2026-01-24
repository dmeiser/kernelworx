import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NONE datasource - no actual request needed
    return {
        version: '2018-05-29'
    };
}

export function response(ctx) {
    // Check if the current user is the profile owner
    const ownerAccountId = ctx.source.ownerAccountId || '';
    const callerAccountId = ctx.identity.sub;
    
    // Owner ID is stored as "ACCOUNT#{sub}", so extract the sub part
    const profileOwnerId = ownerAccountId.startsWith('ACCOUNT#') 
        ? ownerAccountId.substring(8) 
        : ownerAccountId;
    
    return profileOwnerId === callerAccountId;
}
