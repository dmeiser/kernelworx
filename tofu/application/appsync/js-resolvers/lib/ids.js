export function normalizeId(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return null;
    }
    return value.startsWith(prefix) ? value : prefix + value;
}

// normalizeId returns null for a falsy value, but a DynamoDB key attribute may
// never be null. A resolver building a key from a possibly-absent value uses
// this to keep a well-formed placeholder instead of copying the fallback into
// its own local shim.
export function normalizeIdOrPrefix(value, prefix) {
    const normalized = normalizeId(value, prefix);
    return normalized === null ? prefix : normalized;
}

// Inverse of normalizeId: remove `prefix` when present, pass everything else
// through untouched (including non-strings and missing values). Resolvers use
// this at the API boundary, where GraphQL ID fields are served without the
// DynamoDB key prefix.
export function stripIdPrefix(value, prefix) {
    if (typeof value !== 'string' || !value.startsWith(prefix)) {
        return value;
    }
    return value.substring(prefix.length);
}
