import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const inviteCode = ctx.stash.inviteCode;
    const profileId = ctx.stash.profileId;

    // Delete from invites table using inviteCode as PK,
    // guarded by a condition that the invite belongs to the verified profile.
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({
            inviteCode: inviteCode
        }),
        condition: {
            expression: 'profileId = :profileId',
            expressionAttributeValues: util.dynamodb.toMapValues({ ':profileId': profileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Invite does not belong to this profile', 'FORBIDDEN');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
