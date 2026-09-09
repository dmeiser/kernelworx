import { util, runtime } from '@aws-appsync/utils';
import { extractUniqueCatalogIds, attachCatalogs } from './lib/batch_catalogs.js';

// WARNING: this file is loaded via Terraform templatefile() (see
// modules/appsync/functions_catalogs.tf), so every dollar-brace sequence in
// this file is Terraform-interpolated, not a JS template literal. The
// table_name placeholder below is the only intended one; do NOT add other
// dollar-brace sequences here — Terraform will try to substitute them and
// the plan will fail or substitute the wrong value. (Switching to file() is
// deferred per #284.)
const tableName = '${table_name}';

// DynamoDB caps BatchGetItem at 100 keys per request.
const BATCH_GET_LIMIT = 100;

/**
 * Batch-fetch every catalog referenced by a shared-campaign array in a
 * single BatchGetItem, then attach each shared campaign's `catalog` from the
 * batch result.
 *
 * Replaces the per-campaign SharedCampaign.catalog GetItem field resolver
 * (N+1 reads in list queries — see #332). Runs as the last step of the
 * listMySharedCampaigns and findSharedCampaigns pipelines. Deleted-catalog
 * contract matches the removed shared_campaign_catalog_response.vtl field
 * resolver: soft-deleted or missing catalogs resolve to null. (The Campaign
 * variant — which returned the raw item — is batch_get_catalogs_fn.js.)
 */
export function request(ctx) {
    const campaigns = ctx.prev.result || [];
    const catalogIds = extractUniqueCatalogIds(campaigns);

    // No catalogs to fetch: skip the DynamoDB call entirely. The pipeline
    // resolver response passes the campaigns through unchanged.
    if (catalogIds.length === 0) {
        return runtime.earlyReturn(campaigns);
    }

    if (catalogIds.length > BATCH_GET_LIMIT) {
        util.error('Too many catalogs to batch fetch (' + catalogIds.length + ')', 'BadRequest');
    }

    const keys = [];
    for (const catalogId of catalogIds) {
        keys.push(util.dynamodb.toMapValues({ catalogId: catalogId }));
    }

    return {
        operation: 'BatchGetItem',
        tables: {
            [tableName]: { keys: keys }
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const campaigns = ctx.prev.result || [];
    const tableData = ctx.result && ctx.result.data ? ctx.result.data[tableName] : null;
    const unprocessed = ctx.result && ctx.result.unprocessedKeys ? ctx.result.unprocessedKeys[tableName] : null;
    if (unprocessed && unprocessed.length > 0) {
        util.error('Failed to fetch ' + unprocessed.length + ' catalog(s)', 'InternalError');
    }

    return attachCatalogs(campaigns, tableData, true);
}
