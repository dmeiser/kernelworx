import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Build the composite key for GSI2
    // Format: {unitType}#{unitNumber}#{city}#{state}#{campaignName}#{campaignYear}
    // Use string concatenation (array.join() not available in APPSYNC_JS)
    const unitNumStr = '' + ctx.args.unitNumber;
    const campaignYearStr = '' + ctx.args.campaignYear;
    const unitCampaignKey = ctx.args.unitType + '#' + unitNumStr + '#' + ctx.args.city + '#' + ctx.args.state + '#' + ctx.args.campaignName + '#' + campaignYearStr;
    
    return {
        operation: 'Query',
        index: 'GSI2',
        query: {
            expression: 'unitCampaignKey = :unitCampaignKey',
            expressionValues: util.dynamodb.toMapValues({ ':unitCampaignKey': unitCampaignKey })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Filter out inactive  shared campaigns
    const items = ctx.result.items || [];
    const activeItems = [];
    for (const item of items) {
        // Set default value for null/undefined isActive
        if (item.isActive == null) {
            item.isActive = true;
        }
        
        if (item.isActive !== false) {
            activeItems.push(item);
        }
    }
    return activeItems;
}
