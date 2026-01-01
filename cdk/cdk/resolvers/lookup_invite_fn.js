import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.args.input.inviteCode;
    // Direct GetItem on invites table using inviteCode as PK
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ inviteCode: inviteCode }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result || !ctx.result.inviteCode) {
        util.error('Invalid invite code', 'NotFound');
    }
    
    const invite = ctx.result;
    
    // Check if invite is already used
    if (invite.used) {
        util.error('Invite code has already been used', 'ConflictException');
    }
    
    // Check if invite is expired (expiresAt is epoch seconds)
    const now = util.time.nowEpochSeconds();
    if (invite.expiresAt && invite.expiresAt < now) {
        util.error('Invite code has expired', 'ConflictException');
    }
    
    ctx.stash.invite = invite;
    ctx.stash.targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;
    
    return invite;
}
