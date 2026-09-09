/**
 * Delete a payment method's QR code object from S3 via the delete-qr-code Lambda.
 *
 * Runs after get_payment_method_for_delete (which stashes whether the method
 * has a QR code) and before delete_payment_method_from_prefs so the Lambda
 * still finds the method in the account's preferences.
 *
 * Best-effort by design: a QR deletion failure must not block the payment
 * method deletion, mirroring the Python delete_payment_method path. Failures
 * are logged at error level, stashed for diagnostics, and the pipeline
 * continues so the method is still removed from preferences.
 */
import { runtime } from '@aws-appsync/utils';

export function request(ctx) {
    if (!ctx.stash.hasQR) {
        return runtime.earlyReturn({ qrDeleted: false });
    }

    return {
        operation: 'Invoke',
        payload: {
            arguments: {
                paymentMethodName: ctx.stash.paymentMethodName,
            },
            identity: {
                sub: ctx.stash.accountId,
            },
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        console.error(
            `Failed to delete QR code for payment method '${ctx.stash.paymentMethodName}': ${ctx.error.message}`
        );
        ctx.stash.qrCleanupError = ctx.error.message;
        return { qrDeleted: false };
    }

    ctx.stash.qrDeleted = true;
    return { qrDeleted: true };
}
