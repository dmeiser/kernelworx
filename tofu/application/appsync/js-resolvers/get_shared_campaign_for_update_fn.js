import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: ctx.args.input.sharedCampaignCode })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Shared Campaign not found', 'NOT_FOUND');
    }
    // Check ownership
    if (ctx.result.createdBy !== normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#')) {
        util.error('Only the creator can update this campaign sharedCampaign', 'FORBIDDEN');
    }
    ctx.stash.sharedCampaign = ctx.result;
    return ctx.result;
}
