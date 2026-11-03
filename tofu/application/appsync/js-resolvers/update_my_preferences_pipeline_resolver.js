/**
 * Pipeline resolver for the updateMyPreferences mutation (#510).
 *
 * 1. Read the caller's account item and stash the raw `preferences` snapshot.
 * 2. Replace the blob, conditioned on that snapshot (optimistic lock).
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
