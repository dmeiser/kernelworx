import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const profileId = input.profileId;
    const permissions = input.permissions;
    const callerAccountId = ctx.identity.sub;
    
    // Get ownerAccountId from profile in stash (for BatchGetItem on profiles table)
    const ownerAccountId = ctx.stash.profile ? ctx.stash.profile.ownerAccountId : null;
    
    // Generate invite code (first 10 chars of UUID, uppercase)
    const inviteCode = util.autoId().substring(0, 10).toUpperCase();
    
    // Calculate expiry (default 14 days, or custom expiresInDays if provided)
    const daysUntilExpiry = input.expiresInDays || 14;
    const expirySeconds = daysUntilExpiry * 24 * 60 * 60;
    const expiresAtEpoch = util.time.nowEpochSeconds() + expirySeconds;
    const now = util.time.nowISO8601();
    const expiresAtISO = util.time.epochMilliSecondsToISO8601(expiresAtEpoch * 1000);
    
    // Invites table uses inviteCode as PK
    const key = {
        inviteCode: inviteCode
    };
    
    const attributes = {
        inviteCode: inviteCode,
        profileId: profileId,
        ownerAccountId: ownerAccountId,  // Store for BatchGetItem on profiles table
        permissions: permissions,
        createdBy: callerAccountId,
        createdAt: now,
        expiresAt: expiresAtEpoch,
        used: false
    };
    
    // Store values in stash for response function
    ctx.stash.inviteCode = inviteCode;
    ctx.stash.profileId = profileId;
    ctx.stash.permissions = permissions;
    ctx.stash.createdBy = callerAccountId;
    ctx.stash.createdAt = now;
    ctx.stash.expiresAtISO = expiresAtISO;
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues(key),
        attributeValues: util.dynamodb.toMapValues(attributes),
        condition: {
            expression: 'attribute_not_exists(inviteCode)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Invite code collision, please retry', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Use values from stash since PutItem doesn't return the item
    return {
        inviteCode: ctx.stash.inviteCode,
        profileId: ctx.stash.profileId,
        permissions: ctx.stash.permissions,
        expiresAt: ctx.stash.expiresAtISO,
        createdByAccountId: ctx.stash.createdBy,
        createdAt: ctx.stash.createdAt
    };
}
