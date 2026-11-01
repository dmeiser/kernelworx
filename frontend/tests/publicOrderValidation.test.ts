import { describe, it, expect } from 'vitest';
import {
  validatePublicOrderForm,
  MAX_PUBLIC_QUANTITY,
  MAX_BUYER_NOTES_LENGTH,
  addressStarted,
} from '../src/lib/publicOrderValidation';

function validForm() {
  return {
    firstName: 'Buyer',
    lastName: 'One',
    phone: '1234567890',
    email: '',
    address: { street: '', city: '', state: '', zipCode: '' },
    lineItems: { p: 1 },
    paymentMethod: 'Cash',
    notes: '',
  };
}

describe('publicOrderValidation', () => {
  it('valid form passes', () => {
    expect(validatePublicOrderForm(validForm() as any).isValid).toBe(true);
    expect(validatePublicOrderForm(validForm() as any).errors).toEqual({});
  });

  it('requires first and last name', () => {
    const f = { ...validForm(), firstName: '', lastName: '' } as any;
    const r = validatePublicOrderForm(f);
    expect(r.errors.firstName).toBeTruthy();
    expect(r.errors.lastName).toBeTruthy();
    expect(r.isValid).toBe(false);
  });

  it('requires phone or address', () => {
    const f = { ...validForm(), phone: '', address: { street: '', city: '', state: '', zipCode: '' } } as any;
    const r = validatePublicOrderForm(f);
    expect(r.errors.phone).toBeTruthy();
    expect(r.errors.address).toBeTruthy();
  });

  it('requires positive line item', () => {
    const f = { ...validForm(), lineItems: { p: 0 } } as any;
    const r = validatePublicOrderForm(f);
    expect(r.errors.lineItems).toBeTruthy();
  });

  it('requires payment method', () => {
    const f = { ...validForm(), paymentMethod: '' } as any;
    const r = validatePublicOrderForm(f);
    expect(r.errors.paymentMethod).toBeTruthy();
  });

  it('constants match documented values', () => {
    expect(MAX_PUBLIC_QUANTITY).toBe(99);
    expect(MAX_BUYER_NOTES_LENGTH).toBe(500);
  });

  it('addressStarted detects any non-empty field', () => {
    expect(addressStarted({ street: 'x', city: '', state: '', zipCode: '' })).toBe(true);
    expect(addressStarted({ street: '', city: '', state: '', zipCode: '' })).toBe(false);
  });
});
