import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    const expectedOwner = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: expectedOwner, profileId: dbProfileId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can create invites', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
