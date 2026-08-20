import { util } from '@aws-appsync/utils';

// Transitionary placeholder for the old delete-campaign-orders Lambda wrapper.
// The deleteCampaign resolver no longer invokes this function; the data source
// is NONE and this file will be removed in the next deploy step.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return {};
}
