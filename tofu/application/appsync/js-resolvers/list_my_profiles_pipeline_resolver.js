/**
 * Pipeline resolver for the listMyProfiles query.
 *
 * 1. list_my_profiles_fn queries the profiles table and returns a
 *    SellerProfileConnection ({ profiles, nextToken }).
 * 2. batch_latest_campaigns_fn attaches latestCampaign to every profile that
 *    carries the denormalized latestCampaignId field in ONE BatchGetItem
 *    call (#331). Profiles without the field fall through to the
 *    SellerProfile.latestCampaign field resolver, which keeps the per-item
 *    Query as an unmigrated-row fallback.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result;
}
