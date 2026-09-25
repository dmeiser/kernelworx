import { util } from '@aws-appsync/utils';

// #453: an invite stamps the ownerAccountId at creation time. If the profile
// was transferred since then, the profiles-table item moves to the new owner's
// partition, so a base-table GetItem under the invited owner key only succeeds
// while that owner still owns the profile. This guards redemption: a stale
// invite is rejected instead of stamping a share with the old owner.
export function request(ctx) {
    const invite = ctx.stash.invite;
    const profileId = invite.profileId && invite.profileId.startsWith('PROFILE#') ? invite.profileId : `PROFILE#${invite.profileId}`;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: invite.ownerAccountId, profileId: profileId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Invite is no longer valid: profile ownership has changed', 'ConflictException');
    }
    ctx.stash.profile = ctx.result;
    return ctx.result;
}
