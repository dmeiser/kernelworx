import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.source.profileId;
    const targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;
    
    // Query for share record: PK=profileId, SK=targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            profileId: profileId,
            targetAccountId: targetAccountId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If share exists, return permissions; otherwise return empty array (no special permissions)
    if (ctx.result && ctx.result.permissions) {
        return ctx.result.permissions;
    }
    return [];
}
