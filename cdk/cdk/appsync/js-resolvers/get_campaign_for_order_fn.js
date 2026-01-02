import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaignId = ctx.args.input.campaignId;
    console.log('GetCampaignForOrder: request for campaignId=', campaignId, 'args=', JSON.stringify(ctx.args || {}));
    // Query campaignId-index GSI to find campaign (V2 schema)
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
        util.error('Campaign not found', 'NotFound');
    }
    
    const campaign = items[0];
    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'BadRequest');
    }

    // Normalize catalogId to DB format (ensure CATALOG# prefix) and store
    const rawCatalogId = campaign.catalogId;
    const normalizedCatalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : 'CATALOG#' + rawCatalogId;

    // Store campaign and normalized catalogId in stash for next function
    ctx.stash.campaign = campaign;
    ctx.stash.catalogId = normalizedCatalogId;
    console.log('GetCampaignForOrder: Set stash.catalogId to', ctx.stash.catalogId);
    
    return campaign;
}
