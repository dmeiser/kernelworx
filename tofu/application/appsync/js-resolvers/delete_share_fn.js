import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const targetAccountId = ctx.args.input.targetAccountId;
    
    // Normalize profileId to ensure PROFILE# prefix is used in delete key
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    // Normalize targetAccountId to ensure ACCOUNT# prefix (shares are stored with prefix)
    const dbTargetAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#') 
        ? targetAccountId 
        : `ACCOUNT#${targetAccountId}`;

    const callerAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;

    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: dbProfileId, 
            targetAccountId: dbTargetAccountId 
        }),
        condition: {
            expression: 'ownerAccountId = :caller',
            expressionValues: util.dynamodb.toMapValues({ ':caller': callerAccountId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            // The caller is authenticated and merely not the share's owner, so this is a
            // permission failure. UNAUTHORIZED is reserved for "session invalid, sign in
            // again" (frontend isAuthError) and would mislead the user.
            util.error('Not authorized to revoke this share or share not found', 'FORBIDDEN');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
