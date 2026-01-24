export function request(ctx) {
    const input = ctx.arguments && ctx.arguments.input;
    if (!input || !Array.isArray(input.lineItems)) {
        return {};
    }

    for (const li of input.lineItems) {
        // Remove client-sent productName if not a string
        if (typeof li.productName !== 'string') {
            li.productName = null;
        }
        // Coerce quantity to a number
        if (typeof li.quantity !== 'number') {
            const n = Number(li.quantity);
            li.quantity = (n === n && Math.abs(n) !== Infinity) ? n : 0;
        }
        // Ensure productId is a string
        if (typeof li.productId !== 'string') {
            li.productId = null;
        }
        // Remove any unexpected nested plain objects in the line item
        for (const key of Object.keys(li)) {
            const val = li[key];
            if (val && typeof val === 'object' && !Array.isArray(val)) {
                li[key] = null;
            }
        }
    }

    // Updated input is written back into ctx.arguments
    ctx.arguments.input = input;
    return {};
}

export function response(ctx) {
    return ctx.prev && ctx.prev.result;
}
