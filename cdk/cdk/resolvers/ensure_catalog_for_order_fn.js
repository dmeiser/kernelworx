import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaignId = ctx.args.input && ctx.args.input.campaignId;
    if (!campaignId) {
        // If there's no campaignId on the input, nothing we can do
        util.error('campaignId missing from request', 'BadRequest');
    }

    // Query GSI5 (campaignId-index) to find the campaign (V2 schema)
    return {
        operation: 'Query',
        index: 'GSI5',
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
        util.error('Campaign not found while ensuring catalog', 'NotFound');
    }

    const campaign = items[0];

    // Only set the stash.catalogId if it isn't already present
    if (!ctx.stash.catalogId) {
        if (!campaign.catalogId) {
            util.error('Campaign has no catalog assigned', 'BadRequest');
        }
        // Normalize stored campaign.catalogId to DB format (CATALOG#...)
        const rawCatalogId = campaign.catalogId;
        const normalizedCatalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : 'CATALOG#' + rawCatalogId;
        ctx.stash.catalogId = normalizedCatalogId;
        console.log('EnsureCatalogForOrder: Set stash.catalogId to', ctx.stash.catalogId);
    } else {
        console.log('EnsureCatalogForOrder: stash.catalogId already present:', ctx.stash.catalogId);
    }

    // Return campaign info (not used downstream directly but useful in logs)
    return campaign;
}
