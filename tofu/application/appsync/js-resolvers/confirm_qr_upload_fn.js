/**
 * Invoke the confirm-qr-upload Lambda as the first step of the
 * confirmPaymentMethodQRCodeUpload pipeline.
 *
 * The Lambda validates the uploaded S3 object, deletes any replaced QR
 * object, stores the new key in the caller's payment methods, and returns the
 * payment method with its raw S3 key. The final batch_qr_urls pipeline step
 * signs that key into a fresh presigned URL (#330).
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.args,
            identity: ctx.identity,
        },
    };
}

export function response(ctx) {
    // #337: the decorated confirm-qr-upload handler returns a structured
    // error payload instead of raising; abort the pipeline so batch_qr_urls
    // never signs an error payload.
    if (ctx.result && ctx.result.__isError) {
        util.error(ctx.result.message, ctx.result.errorCode, null, { errorCode: ctx.result.errorCode });
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
