/**
 * Pipeline resolver for Campaign.catalog (see #332).
 *
 * 1. check_source_catalog: surface a batch-resolved catalog from a parent
 *    list query (listCampaignsByProfile), if present.
 * 2. get_campaign_catalog: skip the read when pre-resolved; otherwise the
 *    same single GetItem the previous VTL field resolver performed.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
