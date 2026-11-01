import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    return {};
}

export function response(ctx) {
    const callerAccountId = ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    // Handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = normalizeIdOrPrefix(callerAccountId, 'ACCOUNT#');
    return expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId;
}
