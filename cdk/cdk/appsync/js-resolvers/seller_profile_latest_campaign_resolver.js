import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.source.profileId;
    // Add PROFILE# prefix for DynamoDB query if not present
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    return {
        operation: 'Query',
        index: 'profileId-createdAt-index',  // Use GSI sorted by createdAt
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        },
        filter: {
            expression: 'isActive = :isActive OR attribute_not_exists(isActive)',
            expressionValues: util.dynamodb.toMapValues({ ':isActive': true })
        },
        scanIndexForward: false  // Descending order (newest first)
        // Note: No limit here because DynamoDB applies limit BEFORE filter
        // We filter in the response function instead
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        return null;  // No active campaigns for this profile
    }
    
    // GSI sorts by createdAt descending, filter reduces to active campaigns
    // With limit: 1, we get exactly the most recent active campaign
    const campaign = items[0];
    
    // Set default value for null/undefined isActive (backward compatibility)
    if (campaign.isActive == null) {
        campaign.isActive = true;
    }
    
    return campaign;
}
