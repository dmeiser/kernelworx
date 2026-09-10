/**
 * Pure helpers for the batch catalog resolution step (#332), shared by the
 * Campaign and SharedCampaign list-query pipelines. Kept in lib/ so the
 * deleted-catalog contract for both templatefile variants is unit-testable
 * without rendering Terraform.
 */

/**
 * Extract the de-duplicated set of catalogIds from a campaign array,
 * preserving first-seen order.
 */
export function extractUniqueCatalogIds(campaigns) {
    const seen = {};
    const catalogIds = [];
    for (const campaign of campaigns) {
        const catalogId = campaign ? campaign.catalogId : null;
        if (catalogId && !seen[catalogId]) {
            seen[catalogId] = true;
            catalogIds.push(catalogId);
        }
    }
    return catalogIds;
}

/**
 * Map each campaign to its catalog from a BatchGetItem result. Campaigns with
 * a catalogId missing from the batch (dangling reference or unprocessed key)
 * get catalog = null, so the catalog field-resolver pipeline short-circuits
 * without a redundant GetItem.
 *
 * treatDeletedAsNull mirrors the removed VTL field-resolver contracts:
 * Campaign.catalog returned the raw item (false), SharedCampaign.catalog
 * mapped soft-deleted/missing catalogs to null (true).
 */
export function attachCatalogs(campaigns, tableData, treatDeletedAsNull) {
    const catalogMap = {};
    if (Array.isArray(tableData)) {
        for (const catalog of tableData) {
            if (catalog && catalog.catalogId) {
                catalogMap[catalog.catalogId] = catalog;
            }
        }
    }

    return campaigns.map(campaign => {
        if (!campaign || !campaign.catalogId) {
            return campaign;
        }
        const catalog = catalogMap[campaign.catalogId] || null;
        if (catalog && treatDeletedAsNull && catalog.isDeleted == true) {
            return { ...campaign, catalog: null };
        }
        return { ...campaign, catalog: catalog };
    });
}
