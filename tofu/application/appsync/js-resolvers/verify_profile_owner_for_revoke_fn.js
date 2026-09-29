import { util } from '@aws-appsync/utils';
import { ownerGetItemRequest } from './lib/owner_key.js';

export function request(ctx) {
    const profileId = ctx.args && ctx.args.input ? ctx.args.input.profileId : null;
    const sub = ctx.identity ? ctx.identity.sub : null;
    return ownerGetItemRequest(sub, profileId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can revoke shares', 'FORBIDDEN');
    }
    ctx.stash.profile = profile;
    return profile;
}
