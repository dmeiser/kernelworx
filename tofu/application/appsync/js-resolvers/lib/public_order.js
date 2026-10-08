import { util } from '@aws-appsync/utils';
import { normalizeId, stripIdPrefix } from './ids.js';
import { validateAddress, validatePhone } from './validation.js';

// Shared contract for the publicCreateOrder pipeline (#679 write slice,
// spec §5.3). The pipeline spreads across seven APPSYNC_JS functions, each
// allowed exactly one datastore call, so the rules that more than one step
// needs - the cap, the input bounds, the anonymous-write error vocabulary, and
// the receipt shape - live here and are pinned by lib/public_order.test.js.
//
// APPSYNC_JS 1.0.0 rejects constructs Node accepts (the `in` operator,
// Boolean(...), Number.isInteger, .call/.apply/.bind). Nothing in this file may
// use them; only `check_appsync_js_compatibility.test.ts` covers part of the
// list, so the rest is a review obligation.

// Lifetime cap per anchor campaign (spec D6/Q2). The AUTHORITATIVE bound is the
// ConditionExpression this constant feeds into increment_public_order_count_fn:
// the counter is the enforcement point, not a UI number. The create pipeline's
// read-side pre-check is only a cheap early reject, and the counter is never
// decremented, so it counts deleted orders too.
export const PUBLIC_ORDER_CAP = 500;

// One message for every NOT_FOUND branch of the create path. Distinct messages
// per reason would turn publicCreateOrder into an oracle over which profiles
// exist and which enabled the feature - the same rule the offer read follows.
export const PUBLIC_ORDER_UNAVAILABLE = 'Order could not be placed';

// One message for both "not on the seller's allowlist" and "no longer exists on
// the account". The authenticated validate_payment_method_fn.js embeds the
// submitted name in its rejection; a public caller could iterate the mutation
// to enumerate the owner's stored method names (including stale ones the offer
// filters out). The clone therefore never echoes the name.
export const PUBLIC_METHOD_UNAVAILABLE = 'Payment method is not available for this seller';

// Global pseudo-methods: never stored in preferences.paymentMethods, so the
// AccountsDS existence read is skipped for them (same NOOP shape as
// validate_payment_method_fn.js). Mirrors RESERVED_NAMES in
// src/utils/payment_methods.py.
export const GLOBAL_PAYMENT_METHODS = ['cash', 'check'];

// Anonymous write bounds (spec §9): every string input is maxLength-capped, so
// one request cannot exceed the 400KB item limit (which would surface as an
// untyped INTERNAL_ERROR to an anonymous caller) or bloat the seller's records.
export const MAX_NAME_LENGTH = 100;
export const MAX_NOTES_LENGTH = 500;
export const MAX_EMAIL_LENGTH = 254;
export const MAX_ADDRESS_FIELD_LENGTH = 400;
export const MAX_LINE_ITEMS = 20;
export const MAX_QUANTITY = 999;
// LineItemInput.productId is unbounded in the schema, and the unknown-product
// rejection echoes the raw value into the GraphQL error and the AppSync ERROR
// field log. Bounding it here bounds that echo surface.
export const MAX_PRODUCT_ID_LENGTH = 200;

// True when a DynamoDB ConditionalCheckFailedException reached the response.
// AppSync prefixes the type with the datasource kind, and older runtimes put
// the name only in the message, so both spellings are matched (the same
// tolerance write_public_order_settings_fn.js carries).
export function isConditionFailure(error) {
    if (!error) {
        return false;
    }
    const type = error.type === undefined ? '' : error.type;
    return type === 'DynamoDB:ConditionalCheckFailedException' || type === 'ConditionalCheckFailedException'
        || (typeof error.message === 'string' && error.message.includes('ConditionalCheckFailed'));
}

function invalidInput(message) {
    util.error(message, 'INVALID_INPUT');
}

function isFilledString(value) {
    return typeof value === 'string' && value.trim() !== '';
}

// A trimmed non-empty name within the cap, or INVALID_INPUT. The authenticated
// path validates only non-emptiness inline in create_order_fn.js; the public
// path adds the length cap because the caller is anonymous.
function validateName(value, label) {
    if (!isFilledString(value)) {
        invalidInput(label + ' is required');
        return null;
    }
    const trimmed = value.trim();
    if (trimmed.length > MAX_NAME_LENGTH) {
        invalidInput(label + ' must be at most ' + MAX_NAME_LENGTH + ' characters');
        return null;
    }
    return trimmed;
}

// The email is optional; when present it must be a plausible address within the
// cap. The schema's AWSEmail scalar already checks the shape, but the public
// path is the authorization boundary for anonymous input, so it re-checks here
// rather than trusting the transport layer.
function validateEmail(value) {
    if (value === undefined || value === null) {
        return null;
    }
    if (typeof value !== 'string' || value.length > MAX_EMAIL_LENGTH) {
        invalidInput('Email address must be at most ' + MAX_EMAIL_LENGTH + ' characters');
        return null;
    }
    const parts = value.trim().split('@');
    const domain = parts.length === 2 ? parts[1].split('.') : [];
    let domainLabelsOk = parts.length === 2 && parts[0] !== '' && domain.length >= 2;
    for (const label of domain) {
        if (label === '') {
            domainLabelsOk = false;
        }
    }
    if (!domainLabelsOk) {
        invalidInput('Email address is not valid');
        return null;
    }
    return value.trim();
}

// Free-text notes, capped so one anonymous request cannot bloat the item.
function validateNotes(value) {
    if (value === undefined || value === null) {
        return null;
    }
    if (typeof value !== 'string' || value.length > MAX_NOTES_LENGTH) {
        invalidInput('Notes must be at most ' + MAX_NOTES_LENGTH + ' characters');
        return null;
    }
    return value;
}

// Address fields are capped individually (D7 requires all four fields when an
// address is given at all; the shared validateAddress enforces completeness and
// the US ZIP rule).
function validateAddressFields(value) {
    const addressResult = validateAddress(value);
    if (!addressResult.valid) {
        invalidInput(addressResult.error);
        return null;
    }
    const cleaned = {};
    for (const field of ['street', 'city', 'state', 'zipCode']) {
        const raw = value[field];
        const text = typeof raw === 'string' ? raw.trim() : `${raw}`;
        if (text.length > MAX_ADDRESS_FIELD_LENGTH) {
            invalidInput('Address fields must be at most ' + MAX_ADDRESS_FIELD_LENGTH + ' characters');
            return null;
        }
        cleaned[field] = text;
    }
    return cleaned;
}

// Line-item shape only. Product existence and price math stay with the shared
// enrichLineItems core in the write step, exactly as on the authenticated path.
function validateLineItems(value) {
    if (!Array.isArray(value) || value.length === 0) {
        invalidInput('Order must have at least one line item');
        return null;
    }
    if (value.length > MAX_LINE_ITEMS) {
        invalidInput('Order must have at most ' + MAX_LINE_ITEMS + ' line items');
        return null;
    }
    const items = [];
    for (const item of value) {
        if (!item || typeof item !== 'object') {
            invalidInput('Line items must carry a product id and a quantity');
            return null;
        }
        const productId = item.productId;
        if (typeof productId !== 'string' || productId === '' || productId.length > MAX_PRODUCT_ID_LENGTH) {
            invalidInput('Product id must be between 1 and ' + MAX_PRODUCT_ID_LENGTH + ' characters');
            return null;
        }
        const quantity = item.quantity;
        if (typeof quantity !== 'number' || quantity < 1 || quantity > MAX_QUANTITY) {
            invalidInput('Quantity must be between 1 and ' + MAX_QUANTITY);
            return null;
        }
        items.push({ productId: productId, quantity: quantity });
    }
    return items;
}

// Validate the whole anonymous input and map it onto the stored order's
// attribute names. Returns null when any rule rejected the request (util.error
// has already been called, which aborts the step in the runtime and throws in
// unit tests). The mapping lives here so the create step reads one authoritative
// shape from the stash instead of re-deriving field names from caller input -
// create_order_fn.js reads ctx.args.input, and the public clone must not.
export function validateAndMapPublicOrderInput(input) {
    if (!input || typeof input !== 'object') {
        invalidInput('Order input is required');
        return null;
    }

    const firstName = validateName(input.firstName, 'First name');
    if (firstName === null) {
        return null;
    }
    const lastName = validateName(input.lastName, 'Last name');
    if (lastName === null) {
        return null;
    }

    // D7: at least one reachable contact channel. A phone must be a 10-digit US
    // number; an address, if given at all, must be complete.
    const phoneGiven = input.phone !== undefined && input.phone !== null && `${input.phone}`.trim() !== '';
    const addressGiven = input.address !== undefined && input.address !== null;
    if (!phoneGiven && !addressGiven) {
        invalidInput('A phone number or a complete address is required');
        return null;
    }

    let customerPhone = null;
    if (phoneGiven) {
        const phoneResult = validatePhone(`${input.phone}`);
        if (!phoneResult.valid) {
            invalidInput(phoneResult.error);
            return null;
        }
        customerPhone = phoneResult.value;
    }

    let customerAddress = null;
    if (addressGiven) {
        customerAddress = validateAddressFields(input.address);
        if (customerAddress === null) {
            return null;
        }
    }

    const customerEmail = validateEmail(input.email);
    const notes = validateNotes(input.notes);
    const lineItems = validateLineItems(input.lineItems);
    if (lineItems === null) {
        return null;
    }

    if (!isFilledString(input.paymentMethod)) {
        invalidInput('Payment method is required');
        return null;
    }

    return {
        customerFirstName: firstName,
        customerLastName: lastName,
        // customerName stays the display concatenation, exactly as the
        // authenticated path stores it.
        customerName: firstName + ' ' + lastName,
        customerEmail: customerEmail,
        customerPhone: customerPhone,
        customerAddress: customerAddress,
        notes: notes,
        paymentMethod: input.paymentMethod.trim(),
        lineItems: lineItems,
        // The buyer's form does not carry an order date; the public path
        // synthesizes one so the shared write shape stays uniform.
        orderDate: util.time.nowISO8601()
    };
}

// The buyer-facing receipt (PublicOrderReceipt). The order id is
// ORDER#<campaignId>#<suffix>; the '#' cannot enter a URL path, so the receipt
// link splits it into the two path segments the receipt route expects
// (/r/<campaignId>/<orderSuffix>/<receiptToken>) - the same split the frontend
// route and lib/ids.js toUrlId convention require.
//
// receiptUrl is SITE-RELATIVE on purpose: a JS resolver has no environment and
// the API-key request carries no usable site origin (the /graphql behavior
// forwards every viewer header except Host), so the client resolves the path
// against its own origin (frontend/src/lib/publicOrders.ts resolveReceiptUrl).
// The emailed copy of the link is composed absolutely from the SITE_URL env in
// the email slice, where there is no browser origin to inherit.
//
// confirmationEmailSent is false because no send path exists yet: the SES slice
// owns it, and the honesty contract (§6.3) forbids claiming a send that never
// happened. buyerEmailProvided is the honest "the buyer gave us an address".
export function composePublicOrderReceipt(order) {
    if (!order || typeof order.orderId !== 'string') {
        util.error('Order could not be written', 'INTERNAL_ERROR');
        return null;
    }

    const parts = order.orderId.split('#');
    const orderSuffix = parts.length === 3 ? parts[2] : '';
    const receiptToken = typeof order.receiptToken === 'string' ? order.receiptToken : '';
    const campaignId = typeof order.campaignId === 'string' ? stripIdPrefix(order.campaignId, 'CAMPAIGN#') : '';

    let receiptUrl = null;
    if (orderSuffix !== '' && receiptToken !== '' && campaignId !== '') {
        receiptUrl = '/r/' + campaignId + '/' + orderSuffix + '/' + receiptToken;
    }

    return {
        orderId: order.orderId,
        receiptUrl: receiptUrl,
        totalAmount: order.totalAmount,
        buyerEmailProvided: typeof order.customerEmail === 'string' && order.customerEmail !== '',
        confirmationEmailSent: false
    };
}

// The canonical campaign id the create pipeline works from: the offer echoed a
// bare id, the stored anchor is canonical, and both normalize to the same
// CAMPAIGN# form before any comparison.
export function canonicalCampaignId(value) {
    return normalizeId(value, 'CAMPAIGN#');
}
