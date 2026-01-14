export function request(ctx) {
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.args,
            stash: ctx.stash,
        },
    };
}

export function response(ctx) {
    return ctx.result;
}
