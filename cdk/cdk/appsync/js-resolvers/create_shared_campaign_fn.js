import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const account = ctx.stash.account;
    const now = util.time.nowISO8601();
    
    // Generate shared campaign code: UNITTYPE + UNITNUMBER + CAMPAIGN + YEAR
    // Convert numbers to strings using template literal (String() not available in APPSYNC_JS)
    const campaignYearStr = '' + input.campaignYear;
    const unitNumStr = '' + input.unitNumber;
    const campaignAbbrev = input.campaignName.substring(0, 4).toUpperCase();
    const yearAbbrev = campaignYearStr.substring(2);
    const sharedCampaignCode = input.unitType.toUpperCase() + unitNumStr + '-' + campaignAbbrev + '-' + input.state.toUpperCase() + '-' + yearAbbrev;
    
    // Build unit+campaign composite key for GSI2
    const unitCampaignKey = input.unitType + '#' + unitNumStr + '#' + input.city + '#' + input.state + '#' + input.campaignName + '#' + campaignYearStr;
    
    // Build display name from account
    let createdByName = 'Unknown';
    if (account.givenName && account.familyName) {
        createdByName = account.givenName + ' ' + account.familyName;
    } else if (account.email) {
        createdByName = account.email;
    }
    
    const item = {
        sharedCampaignCode: sharedCampaignCode,
        catalogId: input.catalogId,
        campaignName: input.campaignName,
        campaignYear: input.campaignYear,
        unitType: input.unitType,
        unitNumber: input.unitNumber,
        city: input.city,
        state: input.state,
        createdBy: ctx.identity.sub,
        createdByName: createdByName,
        creatorMessage: input.creatorMessage,
        isActive: true,
        createdAt: now,
        unitCampaignKey: unitCampaignKey
    };
    
    // Add optional fields
    if (input.startDate) {
        item.startDate = input.startDate;
    }
    if (input.endDate) {
        item.endDate = input.endDate;
    }
    if (input.description) {
        item.description = input.description;
    }
    
    // Add SK to item for sort key
    item.SK = 'METADATA';
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: sharedCampaignCode, SK: 'METADATA' }),
        attributeValues: util.dynamodb.toMapValues(item),
        condition: {
            expression: 'attribute_not_exists(sharedCampaignCode)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('A Shared Campaign with this code already exists. Please try again.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
