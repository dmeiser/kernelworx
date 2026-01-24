import { util } from '@aws-appsync/utils';

/**
 * Pipeline resolver for deleteCatalog mutation.
 * WRITE ACCESS: Only the owner can delete (enforced in upstream GetCatalogForDelete function).
 * Orchestrates: GetCatalogForDelete -> CheckCatalogUsage -> DeleteCatalog
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Return true on successful deletion
    return ctx.prev.result || true;
}
