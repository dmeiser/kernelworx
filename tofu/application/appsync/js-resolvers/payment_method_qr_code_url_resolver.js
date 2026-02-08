/**
 * Field resolver for PaymentMethod.qrCodeUrl
 * 
 * Generates presigned S3 URLs for QR codes on-demand.
 * 
 * Authorization:
 * - For myPaymentMethods: ownerAccountId from stash (set to ctx.identity.sub)
 * - For paymentMethodsForProfile: ownerAccountId from stash (set by pipeline)
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const qrCodeUrl = ctx.source.qrCodeUrl;
    const methodName = ctx.source.name;
    
    // For myPaymentMethods: use authenticated user's ID
    // For paymentMethodsForProfile: use ownerAccountId from source (set by pipeline)
    let ownerAccountId = ctx.source.ownerAccountId || ctx.identity.sub;
    
    // Extract S3 key from URL if it's a full URL (strip domain)
    let s3Key = qrCodeUrl;
    if (qrCodeUrl && qrCodeUrl.startsWith('http')) {
        // Extract path from URL: https://dev.kernelworx.app/payment-qr-codes/... -> payment-qr-codes/...
        // Parse manually without using URL constructor (may not be available in AppSync runtime)
        const pathStart = qrCodeUrl.indexOf('/', 8);  // Skip https://
        if (pathStart > 0) {
            s3Key = qrCodeUrl.substring(pathStart + 1);  // Remove leading /
        }
    }
    
    // Strip ACCOUNT# prefix if present (from paymentMethodsForProfile pipeline)
    if (ownerAccountId && ownerAccountId.startsWith('ACCOUNT#')) {
        ownerAccountId = ownerAccountId.substring(8);  // Remove "ACCOUNT#"
    }
    
    return {
        operation: 'Invoke',
        payload: {
            qrCodeUrl: qrCodeUrl,
            ownerAccountId: ownerAccountId,
            methodName: methodName,
            s3Key: s3Key,
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Lambda returns the presigned URL string or null
    return ctx.result;
}
