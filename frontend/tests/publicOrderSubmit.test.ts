import { describe, it, expect } from 'vitest';
import { buildPublicOrderInput, buildSubmittedSummary, BUYER_ACKNOWLEDGEMENTS_ACCEPTED } from '../src/lib/publicOrderSubmit';

describe('publicOrderSubmit', () => {
  it('builds line items only for positive quantities', () => {
    const form = {
      firstName: 'A', lastName: 'B', phone: '1234567890', email: '', address: { street: '', city: '', state: '', zipCode: '' },
      paymentMethod: 'Cash', notes: '', lineItems: { a: 2, b: 0, c: 3 },
    } as any;
    const input = buildPublicOrderInput({ token: 'tok', campaignId: 'camp', form }) as any;
    expect(input.lineItems).toEqual([
      { productId: 'a', quantity: 2 },
      { productId: 'c', quantity: 3 },
    ]);
  });

  it('carries payment method and ack flag', () => {
    const form = {
      firstName: 'A', lastName: 'B', phone: '1234567890', email: '', address: { street: '', city: '', state: '', zipCode: '' },
      paymentMethod: 'Venmo', notes: '', lineItems: { a: 1 },
    } as any;
    const input = buildPublicOrderInput({ token: 'tok', campaignId: 'camp', form }) as any;
    expect(input.paymentMethod).toBe('Venmo');
    expect(input.acknowledgementsAccepted).toBe(BUYER_ACKNOWLEDGEMENTS_ACCEPTED);
    expect(input.token).toBe('tok');
    expect(input.campaignId).toBe('camp');
  });

  it('carries trimmed buyer notes when present', () => {
    const form = {
      firstName: 'A', lastName: 'B', phone: '1234567890', email: '', address: { street: '', city: '', state: '', zipCode: '' },
      paymentMethod: 'Venmo', notes: '  Leave the box at the side door  ', lineItems: { a: 1 },
    } as any;
    const input = buildPublicOrderInput({ token: 'tok', campaignId: 'camp', form }) as any;
    expect(input.notes).toBe('Leave the box at the side door');
  });

  it('submitted summary derives payment method from the buyer selection', () => {
    const form = { firstName: 'A', lastName: 'B', phone: 'x', email: 'e@x.com', address: { street: '', city: '', state: '', zipCode: '' }, paymentMethod: 'Cash', notes: '', lineItems: {} } as any;
    const offer = { products: [], paymentMethods: [{ name: 'Card' }] } as any;
    const summary = buildSubmittedSummary(form, offer) as any;
    expect(summary.paymentMethod).toBe('Cash');
    expect(summary.email).toBe('e@x.com');
  });
});
