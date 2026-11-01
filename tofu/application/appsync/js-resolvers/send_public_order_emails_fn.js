import { util, runtime } from '@aws-appsync/utils';

// Step 8 of the publicCreateOrder pipeline (KW-PUBLIC-ORDERS-SES-1, spec §5.3):
// the best-effort order-confirmation email invoke, run AFTER the order is
// committed. There is no info.fieldName in an Invoke payload, so the payload
// carries an explicit operation discriminator (the same shape
// delete_campaign_orders_lambda_fn.js uses); the handler routes on it. Identity
// is null under API_KEY auth and is deliberately not forwarded — the mailer
// must never call get_caller_id.
//
// Best-effort at TWO levels, by contract:
// - the Lambda swallows its own send errors and reports booleans;
// - this function's response() also swallows invoke-level failures (throttle,
//   timeout) AND a structured __isError from the decorated handler.
// An AppSync-level error after the order is committed would show the buyer a
// failure for a durable order and invite duplicate retries (spec Q7), so no
// path here may util.error. The receipt from the write step (ctx.prev.result)
// is passed through with only confirmationEmailSent updated — the three honest
// states stay distinguishable: not offered (buyerEmailProvided=false),
// sent (true/true), failed (true/false).
export const SEND_ORDER_EMAILS_OPERATION = 'send_order_emails';

export function request(ctx) {
    const stash = ctx.stash || {};
    const receipt = ctx.prev && ctx.prev.result ? ctx.prev.result : null;
    const orderItem = stash.orderItem;
    const campaign = stash.campaign || {};

    if (!receipt || typeof receipt.orderId !== 'string' || !orderItem) {
        // Wiring fault: the write step must have produced the receipt and
        // stashed the stored row. The order is already committed either way,
        // so this step degrades to "email not configured" rather than failing
        // the order.
        if (receipt) {
            receipt.confirmationEmailSent = false;
        }
        return runtime.earlyReturn(receipt);
    }

    return {
        operation: 'Invoke',
        payload: {
            operation: SEND_ORDER_EMAILS_OPERATION,
            // The stored row as written: enriched line items, totals, buyer
            // contact, receiptToken. The mailer never re-reads orders (spec
            // §5.3 step 8 keeps the email path free of orders access).
            order: orderItem,
            ownerAccountId: typeof stash.ownerAccountId === 'string' ? stash.ownerAccountId : '',
            campaignName: typeof campaign.campaignName === 'string' ? campaign.campaignName : '',
            // Site-relative; the handler absolutizes it from SITE_URL for the
            // emailed copy (a JS resolver has no environment).
            receiptUrl: typeof receipt.receiptUrl === 'string' ? receipt.receiptUrl : null,
        },
    };
}

export function response(ctx) {
    const receipt = ctx.prev && ctx.prev.result ? ctx.prev.result : null;
    if (!receipt || typeof receipt.orderId !== 'string') {
        // No committed order to report: only a miswired pipeline reaches here,
        // and failing loudly is correct (the schema promises a non-null receipt).
        util.error('Order could not be placed', 'INTERNAL_ERROR');
        return null;
    }

    if (ctx.error) {
        // Invoke-level failure (throttle, timeout): the order is committed and
        // the buyer must never see an error for it.
        receipt.confirmationEmailSent = false;
        return receipt;
    }

    const result = ctx.result || {};
    if (result.__isError) {
        // The decorated handler's structured failure: swallow exactly like an
        // invoke-level error (it is best-effort by the same contract).
        receipt.confirmationEmailSent = false;
        return receipt;
    }

    // True only when the handler actually sent the buyer email (it gates on
    // configured + buyer address provided + send success).
    receipt.confirmationEmailSent = result.confirmationEmailSent === true;
    return receipt;
}
