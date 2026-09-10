/**
 * Pipeline resolver for listMySharedCampaigns (see #332).
 *
 * 1. query_my_shared_campaigns: GSI1 query on createdBy (the former unit
 *    resolver logic).
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
