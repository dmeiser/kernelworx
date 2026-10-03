import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;
    if (!sharedCampaign) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ catalogId: 'NOOP' }),
        };
    }

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

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;
    if (!sharedCampaign) {
        return null;
    }

    const catalog = ctx.result;
    if (!sharedCampaign.catalogId || !catalog || catalog.isDeleted === true) {
        util.error('Shared Campaign ' + sharedCampaign.sharedCampaignCode + ' is no longer available', 'INVALID_INPUT');
    }

    return catalog;
}