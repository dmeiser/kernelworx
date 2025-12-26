import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;
    
    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};
    
    if (input.campaignName !== undefined) {
        updates.push('campaignName = :campaignName');
        exprValues[':campaignName'] = input.campaignName;
    }
    if (input.startDate !== undefined) {
        updates.push('startDate = :startDate');
        exprValues[':startDate'] = input.startDate;
    }
    if (input.endDate !== undefined) {
        updates.push('endDate = :endDate');
        exprValues[':endDate'] = input.endDate;
    }
    if (input.catalogId !== undefined) {
        updates.push('catalogId = :catalogId');
        exprValues[':catalogId'] = input.catalogId;
    }
    
    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();
    
    if (updates.length === 0) {
        return campaign; // No updates, return original
    }
    
    const updateExpression = 'SET ' + updates.join(', ');
    
    // V2: Use composite key (profileId, campaignId) - campaignId is the SK
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId }),
        update: {
        expression: updateExpression,
        expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined,
        expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;
    
    // Build response object with updated values
    const result = {
        campaignId: campaign.campaignId,  // Map DynamoDB campaignId to GraphQL campaignId
        profileId: campaign.profileId,
        campaignName: input.campaignName !== undefined ? input.campaignName : campaign.campaignName,
        startDate: input.startDate !== undefined ? input.startDate : campaign.startDate,
        endDate: input.endDate !== undefined ? input.endDate : campaign.endDate,
        catalogId: input.catalogId !== undefined ? input.catalogId : campaign.catalogId,
        createdAt: campaign.createdAt,
        updatedAt: util.time.nowISO8601()
    };
    
    return result;
}
