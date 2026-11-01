import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const campaignId = normalizeIdOrPrefix(ctx.args.campaignId, 'CAMPAIGN#');
    // V2: Query campaignId-index GSI since PK is now profileId
    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    if (!ctx.result || !ctx.result.items || ctx.result.items.length === 0) {
        // Campaign not found - return null (auth check will be skipped)
        ctx.stash.campaignNotFound = true;
        return null;
    }
    
    const campaign = ctx.result.items[0];
    ctx.stash.campaign = campaign;
    
    return campaign;
}
