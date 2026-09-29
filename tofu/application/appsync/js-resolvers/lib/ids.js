export function normalizeId(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return null;
    }
    return value.startsWith(prefix) ? value : prefix + value;
}

export function stripIdPrefix(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return value;
    }
    return value.startsWith(prefix) ? value.substring(prefix.length) : value;
}
