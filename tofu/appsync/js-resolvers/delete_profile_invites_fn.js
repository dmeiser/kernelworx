import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const invites = ctx.stash.invitesToDelete || [];
    
    // If no invites to delete, skip
    if (invites.length === 0) {
        return runtime.earlyReturn(true);
    }
    
    // Delete first invite - datasource knows the table
    const invite = invites[0];
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ inviteCode: invite.inviteCode })
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
