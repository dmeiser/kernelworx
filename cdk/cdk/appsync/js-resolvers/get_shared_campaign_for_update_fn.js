import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: ctx.args.input.sharedCampaignCode, SK: 'METADATA' })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Shared Campaign not found', 'NotFound');
    }
    // Check ownership
    if (ctx.result.createdBy !== ctx.identity.sub) {
        util.error('Only the creator can update this campaign sharedCampaign', 'Forbidden');
    }
    ctx.stash.sharedCampaign = ctx.result;
    return ctx.result;
}
