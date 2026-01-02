import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const sharedCampaign = ctx.stash.sharedCampaign;
    
    // Build update expression for allowed fields only
    const expressionNames = {};
    const expressionValues = {};
    const updateParts = [];
    
    if (input.creatorMessage !== undefined && input.creatorMessage !== null) {
        expressionNames['#creatorMessage'] = 'creatorMessage';
        expressionValues[':creatorMessage'] = input.creatorMessage;
        updateParts.push('#creatorMessage = :creatorMessage');
    }
    
    if (input.description !== undefined) {
        expressionNames['#description'] = 'description';
        expressionValues[':description'] = input.description;
        updateParts.push('#description = :description');
    }
    
    if (input.isActive !== undefined && input.isActive !== null) {
        expressionNames['#isActive'] = 'isActive';
        expressionValues[':isActive'] = input.isActive;
        updateParts.push('#isActive = :isActive');
    }
    
    if (updateParts.length === 0) {
        // No updates provided, just return existing shared campaign
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ sharedCampaignCode: input.sharedCampaignCode, SK: 'METADATA' })
        };
    }
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: input.sharedCampaignCode, SK: 'METADATA' }),
        update: {
            expression: 'SET ' + updateParts.join(', '),
            expressionNames: expressionNames,
            expressionValues: util.dynamodb.toMapValues(expressionValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
