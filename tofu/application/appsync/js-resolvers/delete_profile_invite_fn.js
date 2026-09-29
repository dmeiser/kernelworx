import { util } from '@aws-appsync/utils';
import { ownerGetItemRequest } from './lib/owner_key.js';
import { normalizeId } from './lib/ids.js';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    ctx.stash.profileId = normalizeId(profileId, 'PROFILE#');
    return ownerGetItemRequest(ctx.identity.sub, profileId);
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
