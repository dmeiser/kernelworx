import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const authorized = ctx.stash.authorized;
    const profileId = ctx.stash.profileId || ctx.args.profileId;
    
    if (!authorized) {
        // Return empty query that yields no results
        return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': 'NONEXISTENT'
            })
        }
        };
    }
    
    // Owner is authorized - query invites table using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({
            ':profileId': profileId
        })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    // Get current time as epoch seconds for comparison
    const nowEpochSeconds = util.time.nowEpochSeconds();
    
    // Filter out expired and used invites
    // expiresAt is now stored as epoch seconds (number)
    const activeInvites = items.filter(invite => {
        // Skip if already used
        if (invite.used === true) {
        return false;
        }
        
        // Skip if expired (expiresAt is epoch seconds)
        if (invite.expiresAt && invite.expiresAt < nowEpochSeconds) {
        return false;
        }
        
        return true;
    });
    
    // Map DynamoDB field names to GraphQL schema names
    // Convert expiresAt from epoch to ISO string for API response
    return activeInvites.map(invite => ({
        inviteCode: invite.inviteCode,
        profileId: invite.profileId,
        permissions: invite.permissions,
        expiresAt: util.time.epochMilliSecondsToISO8601(invite.expiresAt * 1000),
        createdAt: invite.createdAt,
        createdByAccountId: invite.createdBy
    }));
}
