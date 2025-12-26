import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.stash.inviteCode;
    
    // Delete from invites table using inviteCode as PK
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ 
        inviteCode: inviteCode
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
