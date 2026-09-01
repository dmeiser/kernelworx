import { util } from '@aws-appsync/utils';

const NOOP_CAMPAIGN_ID = 'NOOP';

export function request(ctx) {
    const campaign = ctx.stash.campaign;

    // If the lookup did not find the campaign, the delete was skipped and there
    // is nothing to verify. Issue a no-op query so the pipeline can return true.
    if (!campaign) {
        return {
            operation: 'Query',
            index: 'campaignId-index',
            query: {
                expression: 'campaignId = :campaignId',
                expressionValues: util.dynamodb.toMapValues({ ':campaignId': NOOP_CAMPAIGN_ID })
            },
            limit: 1
        };
    }

    // Verify the campaign is no longer visible in the campaignId-index GSI
    // before we report success. If the GSI entry is still present, the caller
    // should retry the idempotent delete.
    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaign.campaignId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (!ctx.stash.campaign) {
        return true;
    }

    const items = ctx.result.items || [];
    if (items.length > 0) {
        util.error('Campaign delete propagation pending; please retry', 'ConflictException');
    }

    return true;
}
