/**
 * Read-side catalog item normalization, shared by every resolver that returns
 * a raw DynamoDB catalog item to a Catalog-typed GraphQL field.
 *
 * User-created catalogs written before the create/update request-template fix
 * persisted `isPublic` as the DynamoDB Strings "true"/"false" (only the
 * separate `isPublicStr` key is legitimately a String, for the GSI). The
 * GraphQL schema declares `isPublic: Boolean!`, so a raw item with a legacy
 * String must have it coerced back to a real Boolean before serialization.
 * Items already carrying a native BOOL pass through untouched.
 *
 * NOTE: this file is bundled (lib is inlined) into js-resolvers that Terraform
 * loads via templatefile() (batch_get_catalogs_fn.js and
 * batch_get_shared_campaign_catalogs_fn.js), which interpolates every literal
 * `${...}` in the bundled text. Keep this file free of dollar-brace sequences.
 */

/**
 * Coerce a legacy String isPublic on a single catalog item, in place.
 *
 * @param {Object|null|undefined} catalog raw DynamoDB catalog item
 * @returns the same item, with isPublic as a Boolean when it was "true"/"false"
 */
export function normalizeCatalogIsPublic(catalog) {
    if (catalog && (catalog.isPublic === 'true' || catalog.isPublic === 'false')) {
        catalog.isPublic = catalog.isPublic === 'true';
    }
    return catalog;
}

/**
 * Coerce legacy String isPublic values across a list of catalog items.
 *
 * @param {Array|null|undefined} catalogs raw DynamoDB catalog items
 * @returns the normalized list (null/undefined inputs pass through)
 */
export function normalizeCatalogsIsPublic(catalogs) {
    if (!Array.isArray(catalogs)) {
        return catalogs;
    }
    return catalogs.map(catalog => normalizeCatalogIsPublic(catalog));
}
