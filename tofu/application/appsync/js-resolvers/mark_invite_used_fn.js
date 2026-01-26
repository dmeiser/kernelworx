import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invite = ctx.stash.invite;
    
    // Delete invite after successful redemption
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ inviteCode: invite.inviteCode }),
        condition: { expression: 'attribute_exists(inviteCode)' },
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Invite has already been used', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result;
}
