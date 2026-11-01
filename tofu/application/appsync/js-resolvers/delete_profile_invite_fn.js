import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    const expectedOwner = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    ctx.stash.profileId = dbProfileId;
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
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can delete invites', 'FORBIDDEN');
    }
    ctx.stash.inviteCode = ctx.args.inviteCode;
    ctx.stash.authorized = true;
    return true;
}
