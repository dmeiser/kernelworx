import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: ctx.args.sharedCampaignCode })
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
    if (ctx.result.createdBy !== `ACCOUNT#${ctx.identity.sub}`) {
        util.error('Only the creator can delete this campaign sharedCampaign', 'FORBIDDEN');
    }
    ctx.stash.sharedCampaign = ctx.result;
    return ctx.result;
}
