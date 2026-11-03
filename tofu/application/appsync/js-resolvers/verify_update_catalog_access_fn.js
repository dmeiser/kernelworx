import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

/**
 * Pipeline step for updateCampaign (#706): when the input changes the
 * campaign's catalogId, fetch the target catalog and verify the caller has
 * access to it (public, ADMIN_MANAGED, or owned by the caller). Without this
 * check any authenticated user could point their campaign at another user's
 * private catalog (IDOR) and block the owner from deleting it (DoS via
 * check_catalog_usage).
 *
 * When catalogId is absent from the input the step is a NOOP.
 */
export function request(ctx) {
    const input = ctx.args.input || ctx.args;
    if (input.catalogId === undefined || input.catalogId === null) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ catalogId: 'NOOP' }),
        };
    }
    const catalogId = normalizeIdOrPrefix(input.catalogId, 'CATALOG#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true,
    };
}

export function response(ctx) {
    const input = ctx.args.input || ctx.args;
    if (input.catalogId === undefined || input.catalogId === null) {
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
