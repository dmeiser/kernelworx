/**
 * Batch-generate presigned QR code URLs for every payment method in a single
 * Lambda invocation.
 *
 * Replaces the per-method PaymentMethod.qrCodeUrl field resolver (N+1 Lambda
 * invocations — one per payment method per query; see #330). Runs as the last
 * step of both parent query pipelines:
 * - myPaymentMethods (owner is the caller; stash.ownerAccountId set without
 *   prefix by set_owner_account_id_in_stash)
 * - paymentMethodsForProfile (owner is the profile owner; stash.ownerAccountId
 *   carries the ACCOUNT# prefix, stash.profileId is set)
 *
 * Authorization is enforced once in the Lambda against the shared
 * owner/profile context, exactly as the old field resolver did.
 */
import { util, runtime } from '@aws-appsync/utils';

function extractS3Key(qrCodeUrl) {
    if (!qrCodeUrl.startsWith('http')) {
        return qrCodeUrl;
    }
    // Parse manually without the URL constructor (unavailable in AppSync runtime)
    const pathStart = qrCodeUrl.indexOf('/', 8);  // Skip https://
    if (pathStart > 0) {
        return qrCodeUrl.substring(pathStart + 1);  // Remove leading /
    }
    return qrCodeUrl;
}

export function request(ctx) {
    const methods = ctx.prev.result || [];

    const s3Keys = [];
    for (const method of methods) {
        if (method && method.qrCodeUrl) {
            s3Keys.push(extractS3Key(method.qrCodeUrl));
        }
    }

    // Nothing to sign (e.g. only the global Cash/Check methods): skip the
    // Lambda invocation entirely and let the response pass methods through.
    if (s3Keys.length === 0) {
        return runtime.earlyReturn({});
    }

    // For myPaymentMethods the owner is the caller; for
    // paymentMethodsForProfile it comes from the profile in the stash.
    let ownerAccountId = ctx.stash.ownerAccountId || ctx.identity.sub;
    if (ownerAccountId && ownerAccountId.startsWith('ACCOUNT#')) {
        ownerAccountId = ownerAccountId.substring(8);
    }

    return {
        operation: 'Invoke',
        payload: {
            s3Keys: s3Keys,
            ownerAccountId: ownerAccountId,
            profileId: ctx.stash.profileId || null,
            identity: ctx.identity,
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const methods = ctx.prev.result || [];
    const urlMap = ctx.result || {};

    return methods.map(method => {
        // Global methods and QR-hidden methods have no stored value; keep
        // them (and any other fields) untouched.
        if (!method || !method.qrCodeUrl) {
            return method;
        }
        const s3Key = extractS3Key(method.qrCodeUrl);
        return { ...method, qrCodeUrl: urlMap[s3Key] || null };
    });
}
