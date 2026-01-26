import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const shares = ctx.stash.sharesToDelete || [];
    
    // If no shares to delete, skip
    if (shares.length === 0) {
        return runtime.earlyReturn(true);
    }
    
    // Delete first share - datasource knows the table
    const share = shares[0];
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ profileId: share.profileId, targetAccountId: share.targetAccountId })
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
