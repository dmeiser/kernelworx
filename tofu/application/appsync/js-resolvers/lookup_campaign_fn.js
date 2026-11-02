import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const campaignId = normalizeIdOrPrefix(
        ctx.args.campaignId || ctx.args.input.campaignId,
        'CAMPAIGN#',
    );
    // Query campaignId-index GSI to find the campaign (V2: PK=profileId, SK=campaignId)
    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('Campaign not found', 'NOT_FOUND');
    }
    // Store campaign in stash for next function
    ctx.stash.campaign = ctx.result.items[0];
    return ctx.result.items[0];
}
