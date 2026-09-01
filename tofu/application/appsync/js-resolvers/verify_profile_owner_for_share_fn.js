import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    // Normalize profileId for key
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // Read directly from the base table to avoid profileId-index GSI propagation races.
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: expectedOwner, profileId: dbProfileId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // If the item exists under the caller's partition key, they are the owner.
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can share profiles', 'Unauthorized');
    }
    ctx.stash.profile = profile;
    return profile;
}
