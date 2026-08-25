import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const campaign = ctx.stash.campaign;

    // If campaign doesn't exist, skip the Lambda invocation
    if (!campaign) {
        return runtime.earlyReturn({ deletedCount: 0 });
    }

    return {
        operation: 'Invoke',
        payload: {
            arguments: {
                campaignId: campaign.campaignId,
            },
            identity: {
                sub: ctx.identity.sub,
            },
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const result = ctx.result || {};
    ctx.stash.deletedOrdersCount = result.deletedCount || 0;
    return result;
}
