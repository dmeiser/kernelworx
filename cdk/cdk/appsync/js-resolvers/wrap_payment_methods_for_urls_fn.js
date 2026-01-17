/**
 * Wrap payment methods array with account ID for URL generation.
 * 
 * This function takes the payment methods array from the previous pipeline step
 * and wraps it with the authenticated user's account ID, preparing it for
 * the generate_presigned_urls Lambda function.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Pass through - no DynamoDB operation needed
    return {};
}

export function response(ctx) {
    // Get payment methods from previous step (array)
    const paymentMethods = ctx.prev.result || [];
    
    // Get authenticated user's account ID
    const ownerAccountId = ctx.identity.sub;
    
    if (!ownerAccountId) {
        util.error('Authentication required', 'Unauthorized');
    }
    
    // Return wrapped format expected by generate_presigned_urls Lambda
    return {
        paymentMethods,
        ownerAccountId
    };
}
