import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_token_step2_fn.js';

// #679 write slice, spec §10.1: the authorization step of the public create
// pipeline. One consistent GetItem, then every rule the anonymous request must
// satisfy, then the mapped field set the later steps read from the stash.

const NOT_FOUND = /NOT_FOUND: Order could not be placed/;

function profile(overrides) {
    return {
        ownerAccountId: 'ACCOUNT#owner-1',
        profileId: 'PROFILE#p1',
        sellerName: 'Troop 42',
        publicOrders: {
            enabled: true,
            token: 'share-token-abc',
            campaignId: 'CAMPAIGN#c1',
            allowedPaymentMethods: ['Venmo', 'Cash'],
            ...(overrides || {})
        }
    };
}

// A profile row whose publicOrders attribute is absent entirely - the shape a
// profile that never enabled the feature actually has.
function profileWithoutBlob() {
    return { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1', sellerName: 'Troop 42' };
}

function profileWithBlob(blob) {
    return { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1', sellerName: 'Troop 42', publicOrders: blob };
}

function validInput(overrides) {
    return {
        profileId: 'p1',
        token: 'share-token-abc',
        campaignId: 'c1',
        acknowledgementsAccepted: true,
        firstName: 'Ada',
        lastName: 'Lovelace',
        phone: '555-123-4567',
        paymentMethod: 'Venmo',
        lineItems: [{ productId: 'prod-1', quantity: 2 }],
        ...(overrides || {})
    };
}

function run(input, storedProfile) {
    const ctx = {
        args: { input },
        stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1' },
        result: storedProfile === undefined ? profile() : storedProfile,
        error: null
    };
    return { ctx, result: response(ctx) };
}

describe('validate_public_token_step2_fn request', () => {
    it('GetItems the profile consistently under the stashed owner key', () => {
        const ctx = { args: { input: validInput() }, stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1' } };
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('answers NOT_FOUND rather than emitting a malformed key when the stash is empty', () => {
        const ctx = { args: { input: validInput() }, stash: {} };
        assert.throws(() => request(ctx), NOT_FOUND);
    });
});

describe('validate_public_token_step2_fn authorization branches', () => {
    it('accepts a valid token, enabled blob, and matching campaign echo', () => {
        const { ctx, result } = run(validInput());
        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.campaignId, 'CAMPAIGN#c1');
        // The seller's display name rides the stash so the write step can
        // denormalize it onto the order row (the receipt read is one GetItem).
        assert.strictEqual(ctx.stash.sellerName, 'Troop 42');
    });

    it('normalizes the bare echoed campaign id to the canonical form before comparing', () => {
        const { ctx } = run(validInput({ campaignId: 'c1' }));
        assert.strictEqual(ctx.stash.campaignId, 'CAMPAIGN#c1');
    });

    it('rejects a token mismatch with NOT_FOUND', () => {
        assert.throws(() => run(validInput({ token: 'wrong' })), NOT_FOUND);
    });

    it('rejects a profile that never enabled the feature with the same NOT_FOUND', () => {
        assert.throws(() => run(validInput(), profileWithoutBlob()), NOT_FOUND);
    });

    it('rejects a disabled profile with the same NOT_FOUND', () => {
        assert.throws(
            () => run(validInput(), profileWithBlob({ enabled: false, token: 'share-token-abc', campaignId: 'CAMPAIGN#c1', allowedPaymentMethods: ['Venmo'] })),
            NOT_FOUND
        );
    });

    it('rejects a blob without a token with the same NOT_FOUND', () => {
        assert.throws(
            () => run(validInput(), profileWithBlob({ enabled: true, campaignId: 'CAMPAIGN#c1', allowedPaymentMethods: ['Venmo'] })),
            NOT_FOUND
        );
    });

    it('rejects a campaign echo that differs from the stored anchor with the same NOT_FOUND', () => {
        assert.throws(() => run(validInput({ campaignId: 'other-campaign' })), NOT_FOUND);
    });

    it('rejects a missing profile row with the same NOT_FOUND', () => {
        assert.throws(() => run(validInput(), null), NOT_FOUND);
    });

    it('answers the identical message for every NOT_FOUND branch', () => {
        const messages = [];
        const cases = [
            [validInput({ token: 'wrong' }), undefined],
            [validInput(), profileWithoutBlob()],
            [validInput(), profileWithBlob({ enabled: false, token: 'share-token-abc' })],
            [validInput({ campaignId: 'other' }), undefined]
        ];
        for (const [input, stored] of cases) {
            try {
                run(input, stored);
                assert.fail('expected NOT_FOUND');
            } catch (error) {
                messages.push(error.message);
            }
        }
        assert.strictEqual(new Set(messages).size, 1);
    });

    it('names no token value in a rejection message', () => {
        try {
            run(validInput({ token: 'share-token-abc' }), profileWithoutBlob());
            assert.fail('expected NOT_FOUND');
        } catch (error) {
            assert.ok(!String(error.message).includes('share-token-abc'));
        }
    });

    it('surfaces a datastore error unchanged', () => {
        const ctx = {
            args: { input: validInput() },
            stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1' },
            result: null,
            error: { type: 'DynamoDB:ThrottlingException', message: 'slow down' }
        };
        assert.throws(() => response(ctx), /ThrottlingException/);
    });
});

describe('validate_public_token_step2_fn allowlist and acknowledgement', () => {
    it('accepts a case-variant of an allowlisted method', () => {
        const { result } = run(validInput({ paymentMethod: 'venmo' }));
        assert.deepStrictEqual(result, { authorized: true });
    });

    it('accepts Cash when the seller allowlisted it', () => {
        const { result } = run(validInput({ paymentMethod: 'Cash' }));
        assert.deepStrictEqual(result, { authorized: true });
    });

    it('rejects a method off the allowlist with the shared no-oracle message', () => {
        assert.throws(
            () => run(validInput({ paymentMethod: 'PayPal' })),
            /INVALID_INPUT: Payment method is not available for this seller/
        );
    });

    it('never echoes the submitted method name in the rejection', () => {
        try {
            run(validInput({ paymentMethod: 'PayPal' }));
            assert.fail('expected INVALID_INPUT');
        } catch (error) {
            assert.ok(!String(error.message).includes('PayPal'));
        }
    });

    it('rejects acknowledgementsAccepted false', () => {
        assert.throws(() => run(validInput({ acknowledgementsAccepted: false })), /INVALID_INPUT: The public order terms must be accepted/);
    });

    it('rejects a missing acknowledgement', () => {
        const input = validInput();
        delete input.acknowledgementsAccepted;
        assert.throws(() => run(input), /INVALID_INPUT: The public order terms must be accepted/);
    });
});

describe('validate_public_token_step2_fn input bounds', () => {
    const boundary = (length, char) => char.repeat(length);

    it('maps the validated input onto the stored order attribute names', () => {
        const { ctx } = run(validInput({ email: 'buyer@example.com', notes: 'Leave at the door' }));
        const mapped = ctx.stash.publicOrder;

        assert.strictEqual(mapped.customerFirstName, 'Ada');
        assert.strictEqual(mapped.customerLastName, 'Lovelace');
        assert.strictEqual(mapped.customerName, 'Ada Lovelace');
        assert.strictEqual(mapped.customerEmail, 'buyer@example.com');
        assert.strictEqual(mapped.customerPhone, '+15551234567');
        assert.strictEqual(mapped.notes, 'Leave at the door');
        assert.strictEqual(mapped.paymentMethod, 'Venmo');
        assert.deepStrictEqual(mapped.lineItems, [{ productId: 'prod-1', quantity: 2 }]);
        assert.strictEqual(typeof mapped.orderDate, 'string');
    });

    it('trims the names it stores', () => {
        const { ctx } = run(validInput({ firstName: '  Ada  ', lastName: ' Lovelace ' }));
        assert.strictEqual(ctx.stash.publicOrder.customerName, 'Ada Lovelace');
    });

    it('accepts a complete address in place of a phone', () => {
        const { ctx } = run(validInput({ phone: null, address: { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' } }));
        assert.strictEqual(ctx.stash.publicOrder.customerAddress.zipCode, '62701');
        assert.strictEqual(ctx.stash.publicOrder.customerPhone, null);
    });

    it('rejects an incomplete address', () => {
        assert.throws(
            () => run(validInput({ phone: null, address: { street: '1 Main St' } })),
            /INVALID_INPUT: Address is missing required fields/
        );
    });

    it('rejects neither phone nor address', () => {
        assert.throws(() => run(validInput({ phone: null })), /INVALID_INPUT: A phone number or a complete address is required/);
    });

    it('rejects a malformed phone as a 10-digit US rule', () => {
        assert.throws(() => run(validInput({ phone: '12345' })), /INVALID_INPUT: Phone number must be a valid 10-digit US number/);
    });

    it('rejects a blank first name', () => {
        assert.throws(() => run(validInput({ firstName: '   ' })), /INVALID_INPUT: First name is required/);
    });

    it('rejects a blank last name', () => {
        assert.throws(() => run(validInput({ lastName: '' })), /INVALID_INPUT: Last name is required/);
    });

    it('accepts a name at the 100-character cap and rejects 101', () => {
        const { ctx } = run(validInput({ firstName: boundary(100, 'a') }));
        assert.strictEqual(ctx.stash.publicOrder.customerFirstName.length, 100);
        assert.throws(() => run(validInput({ firstName: boundary(101, 'a') })), /INVALID_INPUT: First name must be at most 100 characters/);
    });

    it('accepts notes at 500 characters and rejects 501', () => {
        const { ctx } = run(validInput({ notes: boundary(500, 'n') }));
        assert.strictEqual(ctx.stash.publicOrder.notes.length, 500);
        assert.throws(() => run(validInput({ notes: boundary(501, 'n') })), /INVALID_INPUT: Notes must be at most 500 characters/);
    });

    it('accepts an email at 254 characters and rejects 255', () => {
        const local = 'a'.repeat(242);
        const domain = 'b'.repeat(254 - local.length - 1 - '.com'.length) + '.com';
        const ok = local + '@' + domain;
        assert.strictEqual(ok.length, 254);
        const { ctx } = run(validInput({ email: ok }));
        assert.strictEqual(ctx.stash.publicOrder.customerEmail, ok);
        assert.throws(() => run(validInput({ email: ok + 'x' })), /INVALID_INPUT: Email address must be at most 254 characters/);
    });

    it('rejects a malformed email', () => {
        assert.throws(() => run(validInput({ email: 'not-an-email' })), /INVALID_INPUT: Email address is not valid/);
    });

    it('rejects zero line items', () => {
        assert.throws(() => run(validInput({ lineItems: [] })), /INVALID_INPUT: Order must have at least one line item/);
    });

    it('rejects more than 20 line items', () => {
        const items = [];
        for (let i = 0; i < 21; i += 1) {
            items.push({ productId: 'prod-' + i, quantity: 1 });
        }
        assert.throws(() => run(validInput({ lineItems: items })), /INVALID_INPUT: Order must have at most 20 line items/);
    });

    it('accepts quantity 999 and rejects 0 and 1000', () => {
        const { ctx } = run(validInput({ lineItems: [{ productId: 'prod-1', quantity: 999 }] }));
        assert.strictEqual(ctx.stash.publicOrder.lineItems[0].quantity, 999);
        assert.throws(() => run(validInput({ lineItems: [{ productId: 'prod-1', quantity: 0 }] })), /INVALID_INPUT: Quantity must be between 1 and 999/);
        assert.throws(() => run(validInput({ lineItems: [{ productId: 'prod-1', quantity: 1000 }] })), /INVALID_INPUT: Quantity must be between 1 and 999/);
    });

    it('bounds productId length so the unknown-product rejection cannot bloat the log', () => {
        run(validInput({ lineItems: [{ productId: boundary(200, 'p'), quantity: 1 }] }));
        assert.throws(
            () => run(validInput({ lineItems: [{ productId: boundary(201, 'p'), quantity: 1 }] })),
            /INVALID_INPUT: Product id must be between 1 and 200 characters/
        );
    });

    it('rejects an address field over 400 characters', () => {
        assert.throws(
            () => run(validInput({ phone: null, address: { street: boundary(401, 's'), city: 'Springfield', state: 'IL', zipCode: '62701' } })),
            /INVALID_INPUT: Address fields must be at most 400 characters/
        );
    });

    it('rejects a blank payment method', () => {
        assert.throws(() => run(validInput({ paymentMethod: '  ' })), /INVALID_INPUT: Payment method is required/);
    });
});
