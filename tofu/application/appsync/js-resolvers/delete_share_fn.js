import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const targetAccountId = ctx.args.input.targetAccountId;
    
    // Normalize profileId to ensure PROFILE# prefix is used in delete key
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    
    // Normalize targetAccountId to ensure ACCOUNT# prefix (shares are stored with prefix)
    const dbTargetAccountId = normalizeIdOrPrefix(targetAccountId, 'ACCOUNT#');

    const callerAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');

    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
            profileId: dbProfileId, 
            targetAccountId: dbTargetAccountId 
        }),
        condition: {
            // Guard the share's recorded owner, tolerating legacy shares that predate
            // ownerAccountId (missing attribute fails a plain equality condition, which
            // made pre-migration shares impossible to revoke). Profile ownership is the
            // real authorization check and runs first in verify_profile_owner_for_revoke.
            expression: 'attribute_not_exists(ownerAccountId) OR ownerAccountId = :caller',
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
