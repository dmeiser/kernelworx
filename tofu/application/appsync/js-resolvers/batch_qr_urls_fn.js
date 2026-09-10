/**
 * Batch-generate presigned QR code URLs for every payment method in a single
 * Lambda invocation.
 *
 * Replaces the per-method PaymentMethod.qrCodeUrl field resolver (N+1 Lambda
 * invocations — one per payment method per query; see #330). Runs as the last
 * step of the pipelines returning PaymentMethod(s):
 * - myPaymentMethods (array; owner is the caller; stash.ownerAccountId set
 *   without prefix by set_owner_account_id_in_stash)
 * - paymentMethodsForProfile (array; owner is the profile owner;
 *   stash.ownerAccountId carries the ACCOUNT# prefix, stash.profileId is set)
 * - updatePaymentMethod and confirmPaymentMethodQRCodeUpload (single
 *   PaymentMethod; caller is the owner, so the identity.sub fallback applies)
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

function toMethodList(prev) {
    if (prev == null) {
        return [];
    }
    return Array.isArray(prev) ? prev : [prev];
}

export function request(ctx) {
    const prev = ctx.prev.result;
    const single = prev != null && !Array.isArray(prev);
    const methods = toMethodList(prev);

    const s3Keys = [];
    for (const method of methods) {
        if (method && method.qrCodeUrl) {
            s3Keys.push(extractS3Key(method.qrCodeUrl));
        }
    }

    // Nothing to sign (e.g. only the global Cash/Check methods): skip the
    // Lambda invocation entirely and let the response pass methods through.
    if (s3Keys.length === 0) {
        return runtime.earlyReturn(single ? methods[0] : methods);
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
    // #337: the decorated generate-qr-code-presigned-url handler returns a
    // structured error payload instead of raising; surface it rather than
    // mapping every qrCodeUrl to null.
    if (ctx.result && ctx.result.__isError) {
        util.error(ctx.result.message, ctx.result.errorCode, null, { errorCode: ctx.result.errorCode });
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const prev = ctx.prev.result;
    const single = prev != null && !Array.isArray(prev);
    const methods = toMethodList(prev);
    const urlMap = ctx.result || {};

    const mapped = methods.map(method => {
        // Global methods and QR-hidden methods have no stored value; keep
        // them (and any other fields) untouched.
        if (!method || !method.qrCodeUrl) {
            return method;
        }
        const s3Key = extractS3Key(method.qrCodeUrl);
        return { ...method, qrCodeUrl: urlMap[s3Key] || null };
    });

    return single ? mapped[0] : mapped;
}
