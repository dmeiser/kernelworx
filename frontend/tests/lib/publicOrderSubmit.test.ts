/**
 * Tests for building the publicCreateOrder input and the success summary.
 *
 * The campaign id must come from the offer (the server rejects a mismatch), and
 * optional fields must be omitted rather than sent as empty strings or nulls.
 */

import { describe, it, expect } from 'vitest';
import { buildPublicLineItems, buildPublicOrderInput, buildSubmittedSummary } from '../../src/lib/publicOrderSubmit';
import type { PublicOrderFormState } from '../../src/lib/publicOrderValidation';
import type { PublicOfferView } from '../../src/components/public/publicOrderTypes';

const offer: PublicOfferView = {
  sellerName: 'Troop 42',
  campaignId: 'campaign-bare-id',
  campaignName: 'Fall popcorn',
  products: [
    { productId: 'p-1', productName: 'Large bag', price: 12.5 },
    { productId: 'p-2', productName: 'Small bag', price: 7.25 },
  ],
  paymentMethods: [{ name: 'Venmo', qrCodeUrl: 'https://example/qr' }],
};

function form(overrides: Partial<PublicOrderFormState> = {}): PublicOrderFormState {
  return {
    firstName: '  Ada ',
    lastName: 'Lovelace ',
    phone: ' 5558675309 ',
    email: ' ADA@EXAMPLE.COM ',
    address: { street: '', city: '', state: '', zipCode: '' },
    paymentMethod: 'Venmo',
    notes: '  call after 5  ',
    quantities: { 'p-1': 2, 'p-2': 0, 'p-3': 1 },
    ...overrides,
  };
}

describe('buildPublicLineItems', () => {
  it('keeps only products with a quantity above zero', () => {
    expect(buildPublicLineItems(form())).toEqual([
      { productId: 'p-1', quantity: 2 },
      { productId: 'p-3', quantity: 1 },
    ]);
  });
});

describe('buildPublicOrderInput', () => {
  it('echoes the offer campaign id and the share token', () => {
    const input = buildPublicOrderInput({ profileId: 'profile-bare', token: 'share-token', campaignId: offer.campaignId, form: form() });
    expect(input.profileId).toBe('profile-bare');
    expect(input.token).toBe('share-token');
    expect(input.campaignId).toBe('campaign-bare-id');
    expect(input.acknowledgementsAccepted).toBe(true);
  });

  it('trims the names and the free-text fields', () => {
    const input = buildPublicOrderInput({ profileId: 'p', token: 't', campaignId: 'c', form: form() });
    expect(input.firstName).toBe('Ada');
    expect(input.lastName).toBe('Lovelace');
    expect(input.phone).toBe('5558675309');
    expect(input.email).toBe('ADA@EXAMPLE.COM');
    expect(input.notes).toBe('call after 5');
  });

  it('omits an address the buyer never started', () => {
    const input = buildPublicOrderInput({ profileId: 'p', token: 't', campaignId: 'c', form: form() });
    expect('address' in input).toBe(false);
  });

  it('sends a trimmed address when one was started', () => {
    const input = buildPublicOrderInput({
      profileId: 'p',
      token: 't',
      campaignId: 'c',
      form: form({ address: { street: ' 1 Main St ', city: ' Anytown ', state: ' TX ', zipCode: ' 75001 ' } }),
    });
    expect(input.address).toEqual({ street: '1 Main St', city: 'Anytown', state: 'TX', zipCode: '75001' });
  });

  it('omits blank optional fields entirely', () => {
    const input = buildPublicOrderInput({
      profileId: 'p',
      token: 't',
      campaignId: 'c',
      form: form({ phone: '', email: '', notes: '' }),
    });
    expect('phone' in input).toBe(false);
    expect('email' in input).toBe(false);
    expect('notes' in input).toBe(false);
  });
});

describe('buildSubmittedSummary', () => {
  it('labels line items with the offer product names and prices', () => {
    const summary = buildSubmittedSummary(form(), offer);
    expect(summary.lineItems).toEqual([
      { productName: 'Large bag', quantity: 2, subtotal: 25 },
      { productName: 'p-3', quantity: 1, subtotal: 0 },
    ]);
  });

  it('reports the trimmed buyer identity and contact details', () => {
    const summary = buildSubmittedSummary(form(), offer);
    expect(summary.firstName).toBe('Ada');
    expect(summary.lastName).toBe('Lovelace');
    expect(summary.paymentMethod).toBe('Venmo');
    expect(summary.phone).toBe('5558675309');
    expect(summary.email).toBe('ADA@EXAMPLE.COM');
  });

  it('leaves blank contact fields undefined rather than empty strings', () => {
    const summary = buildSubmittedSummary(form({ phone: '', email: '' }), offer);
    expect(summary.phone).toBeUndefined();
    expect(summary.email).toBeUndefined();
  });
});
