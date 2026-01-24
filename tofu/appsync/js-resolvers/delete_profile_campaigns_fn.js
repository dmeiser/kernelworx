import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const campaigns = ctx.stash.campaignsToDelete || [];
    
    // If no campaigns to delete, skip
    if (campaigns.length === 0) {
        return runtime.earlyReturn(true);
    }
    
    // Delete first campaign - datasource knows the table
    const campaign = campaigns[0];
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId })
    };
}

export function response(ctx) {
    // Ignore errors - best effort cleanup
    return true;
}
