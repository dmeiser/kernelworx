import { util } from '@aws-appsync/utils';
import { ownerGetItemRequest } from './lib/owner_key.js';

export function request(ctx) {
    return ownerGetItemRequest(ctx.identity.sub, ctx.args.input.profileId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can create invites', 'FORBIDDEN');
    }
    ctx.stash.profile = profile;
    return profile;
}
