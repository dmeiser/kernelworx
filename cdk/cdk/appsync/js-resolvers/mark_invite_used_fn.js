import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const invite = ctx.stash.invite;
    const now = util.time.nowISO8601();
    
    // Update invite in invites table using inviteCode as key
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ inviteCode: invite.inviteCode }),
        update: {
        expression: 'SET used = :used, usedBy = :usedBy, usedAt = :usedAt',
        expressionValues: util.dynamodb.toMapValues({
            ':used': true,
            ':usedBy': ctx.identity.sub,
            ':usedAt': now,
            ':false': false
        })
        },
        condition: { expression: 'attribute_exists(inviteCode) AND used = :false' }
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
