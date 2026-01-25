/**
 * Direct Lambda resolver for deletePaymentMethodQRCode mutation.
 * Invokes Lambda function which deletes S3 object and updates DynamoDB.
 */
export function request(ctx) {
    return {
        arguments: ctx.arguments,
        identity: ctx.identity,
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Lambda returns {success: true}, extract boolean for GraphQL Boolean! type
    return ctx.result.success === true;
}
