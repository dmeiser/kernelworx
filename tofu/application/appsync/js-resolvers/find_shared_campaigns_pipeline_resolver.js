/**
 * Pipeline resolver for findSharedCampaigns (see #332).
 *
 * 1. find_shared_campaigns_by_unit: GSI2 query on unitCampaignKey (the former
 *    unit resolver logic).
 * 2. batch_get_shared_campaign_catalogs: one BatchGetItem for every
 *    catalogId in the result, mapping each shared campaign to its catalog —
 *    replaces the per-item GetItem field resolver (N+1).
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
