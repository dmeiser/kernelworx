import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;
    if (sharedCampaign) {
        const rawCatalogId = sharedCampaign.catalogId;
        if (!rawCatalogId) {
            return {
                operation: 'GetItem',
                key: util.dynamodb.toMapValues({ catalogId: 'NOOP' }),
            };
        }
        const catalogId = normalizeIdOrPrefix(rawCatalogId, 'CATALOG#');
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ catalogId: catalogId }),
            consistentRead: true,
        };
    }

    // #706: direct path (no sharedCampaignCode) — validate the catalog the
    // caller is attaching to their new campaign. Without this, any
    // authenticated user could reference another user's private catalogId.
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const rawCatalogId = input.catalogId;
    if (!rawCatalogId || (typeof rawCatalogId === 'string' && rawCatalogId.trim() === '')) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ catalogId: 'NOOP' }),
        };
    }
    const catalogId = normalizeIdOrPrefix(rawCatalogId, 'CATALOG#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true,
    };
}

export function response(ctx) {
    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;

    if (sharedCampaign) {
        if (ctx.error) {
            util.error(ctx.error.message, ctx.error.type);
        }
        if (!sharedCampaign.catalogId) {
            return null;
        }
        const catalog = ctx.result;
        if (!catalog || catalog.isDeleted === true) {
            util.error('Shared Campaign ' + sharedCampaign.sharedCampaignCode + ' is no longer available', 'INVALID_INPUT');
        }

        // #706: the catalog must still be accessible to the shared campaign
        // creator (public, admin-managed, or owned by createdBy). This is
        // defense-in-depth: the catalog was validated at shared-campaign
        // creation time, but ownership or visibility may have changed since.
        const creatorAccountId = sharedCampaign.createdBy;
        if (!(catalog.isPublic === true || catalog.catalogType === 'ADMIN_MANAGED' || catalog.ownerAccountId === creatorAccountId)) {
            util.error('Shared Campaign ' + sharedCampaign.sharedCampaignCode + ' is no longer available', 'INVALID_INPUT');
        }

        return catalog;
    }

    // Direct path: validate the catalog the caller is attaching.
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    if (!input.catalogId || (typeof input.catalogId === 'string' && input.catalogId.trim() === '')) {
        return null;
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const catalog = ctx.result;
    if (!catalog) {
        util.error('Catalog not found', 'NOT_FOUND');
    }
    if (catalog.isDeleted === true) {
        util.error('Catalog has been deleted', 'NOT_FOUND');
    }

    // #706: enforce the same visibility rule as getCatalog (#509).
    const callerAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    if (!(catalog.isPublic === true || catalog.catalogType === 'ADMIN_MANAGED' || catalog.ownerAccountId === callerAccountId)) {
        util.error('Catalog not found', 'NOT_FOUND');
    }

    return catalog;
}