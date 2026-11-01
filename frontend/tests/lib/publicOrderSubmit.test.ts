/**
 * Tests for publicOrderSubmit.
 *
 * The success screen is the buyer's only record of an offline order, so the
 * summary must be the order they actually placed: the items they picked at the
 * prices the offer showed them, and the payment method they chose. These cases
 * pin the join against the offer's products, the drop of an id the offer no
 * longer carries, and the fact that the input builder takes no profile id at
 * all (the server derives everything from campaignId + token).
 */
import { describe, it, expect } from 'vitest';
import {
  buildPublicOrderInput,
  buildSubmittedSummary,
  submittedLineItems,
  BUYER_ACKNOWLEDGEMENTS_ACCEPTED,
} from '../../src/lib/publicOrderSubmit';
import { MAX_PUBLIC_QUANTITY, type PublicOrderFormState } from '../../src/lib/publicOrderValidation';
import type { PublicOfferView } from '../../src/components/public/publicOrderTypes';

const emptyAddress = { street: '', city: '', state: '', zipCode: '' };

const formState = (overrides: Partial<PublicOrderFormState> = {}): PublicOrderFormState => ({
  firstName: ' Ada ',
  lastName: 'Lovelace',
  phone: '555-123-4567',
  email: 'ada@example.com',
  address: { ...emptyAddress },
  lineItems: { 'PROD#1': 2, 'PROD#2': 1 },
  paymentMethod: 'Cash',
  notes: '',
  ...overrides,
});

const offer: PublicOfferView = {
  sellerName: 'Acme Troop',
  campaignId: 'CAMPAIGN#c1',
  campaignName: 'Spring Sale',
  products: [
    { productId: 'PROD#1', productName: 'Cookie Box', price: 12.5, description: 'Twelve cookies' },
    { productId: 'PROD#2', productName: 'Magazine', price: 4, description: null },
  ],
  paymentMethods: [{ name: 'Venmo', qrCodeUrl: null }, { name: 'Cash', qrCodeUrl: null }],
};

describe('buildPublicOrderInput', () => {
  it('carries the campaign, token, acknowledgements, trimmed identity, and method', () => {
    const input = buildPublicOrderInput({ token: 'tok-1', campaignId: 'CAMPAIGN#c1', form: formState() });
    expect(input.campaignId).toBe('CAMPAIGN#c1');
    expect(input.token).toBe('tok-1');
    expect(input.acknowledgementsAccepted).toBe(BUYER_ACKNOWLEDGEMENTS_ACCEPTED);
    expect(input.firstName).toBe('Ada');
    expect(input.lastName).toBe('Lovelace');
    expect(input.paymentMethod).toBe('Cash');
  });

  it('sends only the line items with a valid positive quantity', () => {
    const form = formState({ lineItems: { 'PROD#1': 3, 'PROD#2': 0, 'PROD#3': -5 } });
    const input = buildPublicOrderInput({ token: 'tok-1', campaignId: 'CAMPAIGN#c1', form });
    expect(input.lineItems).toEqual([{ productId: 'PROD#1', quantity: 3 }]);
  });

  it('omits optional fields the buyer left blank', () => {
    const form = formState({ phone: '', email: '', notes: '', address: { ...emptyAddress } });
    const input = buildPublicOrderInput({ token: 'tok-1', campaignId: 'CAMPAIGN#c1', form });
    expect(input.phone).toBeUndefined();
    expect(input.email).toBeUndefined();
    expect(input.notes).toBeUndefined();
    expect(input.address).toBeUndefined();
  });

  it('includes a started address, trimmed', () => {
    const form = formState({
      address: { street: ' 1 Main St ', city: 'Springfield', state: 'IL', zipCode: '62701' },
    });
    const input = buildPublicOrderInput({ token: 'tok-1', campaignId: 'CAMPAIGN#c1', form });
    expect(input.address).toEqual({ street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' });
  });

  it('accepts no profile id: the input is keyed only by campaign and token', () => {
    // The vestigial profileId argument used to be threaded through the call
    // site and silently dropped. Its arity is part of the contract now.
    expect(buildPublicOrderInput.length).toBe(1);
    const input = buildPublicOrderInput({ token: 'tok-1', campaignId: 'CAMPAIGN#c1', form: formState() });
    expect(input).not.toHaveProperty('profileId');
  });
});

describe('submittedLineItems', () => {
  it('keeps whole positive quantities inside the picker range', () => {
    expect(submittedLineItems(formState({ lineItems: { 'PROD#1': 1, 'PROD#2': MAX_PUBLIC_QUANTITY } }).lineItems)).toEqual(
      expect.arrayContaining([
        { productId: 'PROD#1', quantity: 1 },
        { productId: 'PROD#2', quantity: MAX_PUBLIC_QUANTITY },
      ]),
    );
  });

  it('drops negatives, zeros, fractions, and non-finite values', () => {
    const form = formState({
      lineItems: { a: -1, b: 0, c: 1.5, d: Number.NaN, e: Number.POSITIVE_INFINITY, f: 2 },
    });
    expect(submittedLineItems(form.lineItems)).toEqual([{ productId: 'f', quantity: 2 }]);
  });

  it('drops quantities above the picker maximum so the estimate cannot disagree with the order', () => {
    const form = formState({ lineItems: { a: MAX_PUBLIC_QUANTITY + 1 } });
    expect(submittedLineItems(form.lineItems)).toEqual([]);
  });

  it('drops an empty product id', () => {
    expect(submittedLineItems(formState({ lineItems: { '': 3 } }).lineItems)).toEqual([]);
  });
});

describe('buildSubmittedSummary', () => {
  it('lists the submitted items joined against the offer, with unit price and line total', () => {
    const summary = buildSubmittedSummary(formState(), offer);
    expect(summary.lineItems).toEqual([
      { productId: 'PROD#1', productName: 'Cookie Box', quantity: 2, pricePerUnit: 12.5, subtotal: 25 },
      { productId: 'PROD#2', productName: 'Magazine', quantity: 1, pricePerUnit: 4, subtotal: 4 },
    ]);
  });

  it('is never empty for a form that has items', () => {
    // The regression this guards: lineItems was hardcoded to [], so every buyer
    // saw an empty "What you submitted" table.
    expect(buildSubmittedSummary(formState(), offer).lineItems.length).toBeGreaterThan(0);
  });

  it('drops a product id the offer no longer carries rather than inventing a name', () => {
    const form = formState({ lineItems: { 'PROD#1': 1, 'PROD#GONE': 4 } });
    const summary = buildSubmittedSummary(form, offer);
    expect(summary.lineItems.map((item) => item.productId)).toEqual(['PROD#1']);
  });

  it('uses the payment method the buyer selected, not the seller first method', () => {
    // offer.paymentMethods[0] is Venmo; the buyer chose Cash.
    expect(buildSubmittedSummary(formState(), offer).paymentMethod).toBe('Cash');
  });

  it('prefers the payment method the create mutation echoed back', () => {
    const summary = buildSubmittedSummary(formState(), offer, 'Check');
    expect(summary.paymentMethod).toBe('Check');
  });

  it('falls back to the selected method when the echoed value is blank or absent', () => {
    expect(buildSubmittedSummary(formState(), offer, '   ').paymentMethod).toBe('Cash');
    expect(buildSubmittedSummary(formState(), offer, null).paymentMethod).toBe('Cash');
    expect(buildSubmittedSummary(formState(), offer, undefined).paymentMethod).toBe('Cash');
  });

  it('reports trimmed buyer identity and omits blank contact channels', () => {
    const form = formState({ firstName: '  Ada  ', lastName: ' Lovelace ', phone: '', email: '  ' });
    const summary = buildSubmittedSummary(form, offer);
    expect(summary.firstName).toBe('Ada');
    expect(summary.lastName).toBe('Lovelace');
    expect(summary.phone).toBeUndefined();
    expect(summary.email).toBeUndefined();
  });

  it('produces no rows when the offer carries no products', () => {
    const bareOffer: PublicOfferView = { ...offer, products: [] };
    expect(buildSubmittedSummary(formState(), bareOffer).lineItems).toEqual([]);
  });
});
