/**
 * Create payment method in DynamoDB.
 * 
 * Adds the new payment method to the user's preferences.paymentMethods array.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const methodName = ctx.stash.paymentMethodName;
    const existingMethods = ctx.stash.existingPaymentMethods || [];
    
    // Create new payment method object
    const newMethod = {
        name: methodName,
        qrCodeUrl: null  // No QR code initially
    };
    
    // Add to existing methods array
    const updatedMethods = [...existingMethods, newMethod];
    
    // Update preferences.paymentMethods in the account item
    const key = {
        accountId: `ACCOUNT#${accountId}`
    };
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues(key),
        update: {
            expression: 'SET #prefs.#pm = :methods',
            expressionNames: {
                '#prefs': 'preferences',
                '#pm': 'paymentMethods'
            },
            expressionValues: util.dynamodb.toMapValues({
                ':methods': updatedMethods
            })
        },
        condition: {
            expression: 'attribute_exists(accountId)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Return the created payment method
    return {
        name: ctx.stash.paymentMethodName,
        qrCodeUrl: null
    };
}
