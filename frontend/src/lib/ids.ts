/**
 * Ensure an ID has the proper type prefix (e.g., PROFILE#uuid).
 * Used when sending IDs to the GraphQL API.
 */
export const ensurePrefixed = (prefix: string, id?: string | null) => {
  if (!id) return id || null;
  const wanted = `${prefix}#`;
  return id.startsWith(wanted) ? id : `${wanted}${id}`;
};

/**
 * Strip the type prefix from an ID to get the raw UUID.
 * Used for generating clean URLs (e.g., /scouts/uuid instead of /scouts/PROFILE%23uuid).
 */
export const stripPrefix = (id?: string | null): string => {
  if (!id) return '';
  const hashIndex = id.indexOf('#');
  return hashIndex >= 0 ? id.slice(hashIndex + 1) : id;
};

export const ensureProfileId = (id?: string | null) => ensurePrefixed('PROFILE', id);
export const ensureCampaignId = (id?: string | null) => ensurePrefixed('CAMPAIGN', id);
export const ensureCatalogId = (id?: string | null) => ensurePrefixed('CATALOG', id);
export const ensureProductId = (id?: string | null) => ensurePrefixed('PRODUCT', id);
export const ensureOrderId = (id?: string | null) => ensurePrefixed('ORDER', id);
export const ensureAccountId = (id?: string | null) => ensurePrefixed('ACCOUNT', id);

/**
 * Extract just the UUID from a prefixed ID for use in URLs.
 * Example: toUrlId("PROFILE#abc-123") returns "abc-123"
 */
export const toUrlId = stripPrefix;
