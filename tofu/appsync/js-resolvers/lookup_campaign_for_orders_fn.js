import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaignId = ctx.args.campaignId;
    // Query campaignId-index GSI to find campaign (V2 schema: PK=profileId, SK=campaignId)
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
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        // Campaign not found - return empty, skip auth (will return empty array)
        ctx.stash.campaignNotFound = true;
        ctx.stash.authorized = false;
        return null;
    }
    
    const campaign = items[0];
    ctx.stash.campaign = campaign;
    ctx.stash.profileId = campaign.profileId;
    
    return campaign;
}
