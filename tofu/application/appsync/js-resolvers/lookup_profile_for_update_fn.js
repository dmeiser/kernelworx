import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: expectedOwner,
            profileId: dbProfileId
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Profile not found or access denied', 'Forbidden');
    }
    ctx.stash.profile = profile;
    return profile;
}

