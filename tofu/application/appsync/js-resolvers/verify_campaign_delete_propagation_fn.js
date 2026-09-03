import { util } from '@aws-appsync/utils';

const NOOP_PROFILE_ID = 'NOOP';
const NOOP_CAMPAIGN_ID = 'NOOP';

export function request(ctx) {
    const campaign = ctx.stash.campaign;

    // If the lookup did not find the campaign, the delete was skipped and there
    // is nothing to verify. Issue a no-op read so the pipeline can return true.
    if (!campaign) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: NOOP_PROFILE_ID, campaignId: NOOP_CAMPAIGN_ID }),
            consistentRead: true
        };
    }

    // Confirm the campaign is actually gone before reporting success. The
    // campaignId-index GSI is eventually consistent, so a GSI read can keep
    // showing a deleted row for an unbounded time; a strongly consistent
    // base-table read deterministically reflects the completed delete.
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (!ctx.stash.campaign) {
        return true;
    }

    // ctx.result is the item for GetItem, or null when it is absent. If the
    // row is still present the delete did not take effect; the delete is
    // idempotent, so the caller may retry it.
    if (ctx.result) {
        util.error('Campaign deletion could not be confirmed; please retry', 'ConflictException');
    }

    return true;
}
