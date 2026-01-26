export function request(ctx) {
    // Pass through - stash will be populated by lookup_invite_fn
    return {};
}

export function response(ctx) {
    // Return the share that was created
    return ctx.prev.result;
}
