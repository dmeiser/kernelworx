/**
 * Tests for the public order form validation.
 *
 * These pin the US-only semantics the form states inline: a ten-digit US phone
 * number, or an address with all four fields plus a 5- or 9-digit ZIP, and the
 * schema's length/quantity bounds at their boundaries.
 */

import { describe, it, expect } from 'vitest';
import {
  MAX_ADDRESS_FIELD_LENGTH,
  MAX_BUYER_EMAIL_LENGTH,
  MAX_BUYER_NAME_LENGTH,
  MAX_BUYER_NOTES_LENGTH,
  MAX_PUBLIC_LINE_ITEMS,
  MAX_PUBLIC_QUANTITY,
  MIN_PUBLIC_QUANTITY,
  addressStarted,
  publicOrderFormIsValid,
  validateBuyerAddress,
  validateBuyerContact,
  validateBuyerEmail,
  validateBuyerName,
  validateBuyerNotes,
  validateBuyerPhone,
  validateLineItems,
  validatePublicOrderForm,
  type PublicOrderFormState,
} from '../../src/lib/publicOrderValidation';

const emptyAddress = { street: '', city: '', state: '', zipCode: '' };
const fullAddress = { street: '1 Main St', city: 'Anytown', state: 'TX', zipCode: '75001' };

function formState(overrides: Partial<PublicOrderFormState> = {}): PublicOrderFormState {
  return {
    firstName: 'Ada',
    lastName: 'Lovelace',
    phone: '555-867-5309',
    email: '',
    address: { ...emptyAddress },
    paymentMethod: 'Venmo',
    notes: '',
    quantities: { 'p-1': 2 },
    ...overrides,
  };
}

describe('validateBuyerName', () => {
  it('requires a trimmed non-empty name', () => {
    expect(validateBuyerName('', 'First name')).toBe('First name is required.');
    expect(validateBuyerName('   ', 'First name')).toBe('First name is required.');
    expect(validateBuyerName('Ada', 'First name')).toBeNull();
  });

  it('accepts the max length and rejects one over', () => {
    expect(validateBuyerName('a'.repeat(MAX_BUYER_NAME_LENGTH), 'First name')).toBeNull();
    expect(validateBuyerName('a'.repeat(MAX_BUYER_NAME_LENGTH + 1), 'First name')).toBe(
      `First name must be at most ${MAX_BUYER_NAME_LENGTH} characters.`,
    );
  });
});

describe('validateBuyerPhone', () => {
  it('accepts a ten-digit US number with separators', () => {
    expect(validateBuyerPhone('(555) 867-5309')).toBeNull();
  });

  it('accepts a leading country code', () => {
    expect(validateBuyerPhone('+1 555 867 5309')).toBeNull();
  });

  it('rejects anything that is not ten digits', () => {
    expect(validateBuyerPhone('555-5309')).toBe('Phone number must be a valid 10-digit US number.');
    expect(validateBuyerPhone('555 867 5309 0')).toBe('Phone number must be a valid 10-digit US number.');
    expect(validateBuyerPhone('+44 20 7946 0958')).toBe('Phone number must be a valid 10-digit US number.');
  });

  it('requires a value when the field is the chosen contact method', () => {
    expect(validateBuyerPhone('')).toBe('Enter a phone number or a complete address.');
  });
});

describe('validateBuyerAddress', () => {
  it('accepts all four fields with a 5-digit ZIP', () => {
    expect(validateBuyerAddress(fullAddress)).toBeNull();
  });

  it('accepts a ZIP+4', () => {
    expect(validateBuyerAddress({ ...fullAddress, zipCode: '75001-1234' })).toBeNull();
  });

  it('names every missing field when an address is started', () => {
    expect(validateBuyerAddress({ ...fullAddress, city: '', state: '' })).toBe(
      'An address needs all four fields (missing: city, state).',
    );
  });

  it('rejects a ZIP that is neither 5 nor 9 digits', () => {
    expect(validateBuyerAddress({ ...fullAddress, zipCode: '7501' })).toBe('ZIP code must be 5 or 9 digits.');
    expect(validateBuyerAddress({ ...fullAddress, zipCode: 'SW1A 1AA' })).toBe('ZIP code must be 5 or 9 digits.');
  });

  it('accepts fields at the per-field length cap and rejects one over', () => {
    const atCap = 'a'.repeat(MAX_ADDRESS_FIELD_LENGTH);
    expect(validateBuyerAddress({ ...fullAddress, street: atCap })).toBeNull();
    expect(validateBuyerAddress({ ...fullAddress, city: 'a'.repeat(MAX_ADDRESS_FIELD_LENGTH + 1) })).toBe(
      `Address fields must be at most ${MAX_ADDRESS_FIELD_LENGTH} characters (too long: city).`,
    );
  });

  it('names every over-long field at once', () => {
    const long = 'a'.repeat(MAX_ADDRESS_FIELD_LENGTH + 1);
    expect(validateBuyerAddress({ ...fullAddress, state: long, zipCode: long })).toBe(
      `Address fields must be at most ${MAX_ADDRESS_FIELD_LENGTH} characters (too long: state, zipCode).`,
    );
  });
});

describe('addressStarted', () => {
  it('is false for an untouched address block', () => {
    expect(addressStarted(emptyAddress)).toBe(false);
  });

  it('is true when any field has content', () => {
    expect(addressStarted({ ...emptyAddress, city: 'Anytown' })).toBe(true);
  });
});

describe('validateBuyerContact', () => {
  it('requires phone or a complete address', () => {
    expect(validateBuyerContact('', emptyAddress)).toBe(
      'Enter a phone number or a complete address so the seller can reach you.',
    );
  });

  it('accepts a phone alone', () => {
    expect(validateBuyerContact('5558675309', emptyAddress)).toBeNull();
  });

  it('accepts a complete address alone', () => {
    expect(validateBuyerContact('', fullAddress)).toBeNull();
  });

  it('reports a malformed phone when one was typed', () => {
    expect(validateBuyerContact('12345', emptyAddress)).toBe('Phone number must be a valid 10-digit US number.');
  });

  it('reports an incomplete address when only an address was started', () => {
    expect(validateBuyerContact('', { ...fullAddress, zipCode: '' })).toBe(
      'An address needs all four fields (missing: zipCode).',
    );
  });

  it('requires a complete address when one was started alongside a valid phone', () => {
    expect(validateBuyerContact('555-867-5309', { ...emptyAddress, city: 'Anytown' })).toBe(
      'An address needs all four fields (missing: street, state, zipCode).',
    );
  });

  it('reports a malformed phone first when it is paired with a started address', () => {
    expect(validateBuyerContact('12345', { ...fullAddress, zipCode: '' })).toBe(
      'Phone number must be a valid 10-digit US number.',
    );
  });

  it('accepts a phone plus a complete address', () => {
    expect(validateBuyerContact('555-867-5309', fullAddress)).toBeNull();
  });
});

describe('validateBuyerEmail', () => {
  it('is optional', () => {
    expect(validateBuyerEmail('')).toBeNull();
  });

  it('checks the shape when present', () => {
    expect(validateBuyerEmail('ada@example.com')).toBeNull();
    expect(validateBuyerEmail('ada@')).toBe('Enter a valid email address.');
    expect(validateBuyerEmail('ada example.com')).toBe('Enter a valid email address.');
  });

  it('rejects an email over the bound', () => {
    const long = `${'a'.repeat(MAX_BUYER_EMAIL_LENGTH)}@example.com`;
    expect(validateBuyerEmail(long)).toBe(`Email must be at most ${MAX_BUYER_EMAIL_LENGTH} characters.`);
  });
});

describe('validateLineItems', () => {
  it('requires at least one product', () => {
    expect(validateLineItems({})).toBe('Add at least one product to your order.');
    expect(validateLineItems({ 'p-1': 0 })).toBe('Add at least one product to your order.');
  });

  it('caps the number of line items', () => {
    const quantities = Object.fromEntries(
      Array.from({ length: MAX_PUBLIC_LINE_ITEMS + 1 }, (_, index) => [`p-${index}`, 1]),
    );
    expect(validateLineItems(quantities)).toBe(`An order can have at most ${MAX_PUBLIC_LINE_ITEMS} products.`);
  });

  it('accepts the quantity bounds and rejects outside them', () => {
    expect(validateLineItems({ 'p-1': MIN_PUBLIC_QUANTITY })).toBeNull();
    expect(validateLineItems({ 'p-1': MAX_PUBLIC_QUANTITY })).toBeNull();
    expect(validateLineItems({ 'p-1': MAX_PUBLIC_QUANTITY + 1 })).toBe(
      `Quantities must be between ${MIN_PUBLIC_QUANTITY} and ${MAX_PUBLIC_QUANTITY}.`,
    );
  });
});

describe('validateBuyerNotes', () => {
  it('accepts notes at the bound and rejects one over', () => {
    expect(validateBuyerNotes('x'.repeat(MAX_BUYER_NOTES_LENGTH))).toBeNull();
    expect(validateBuyerNotes('x'.repeat(MAX_BUYER_NOTES_LENGTH + 1))).toBe(
      `Notes must be at most ${MAX_BUYER_NOTES_LENGTH} characters.`,
    );
  });
});

describe('validatePublicOrderForm', () => {
  it('passes a complete form', () => {
    expect(publicOrderFormIsValid(validatePublicOrderForm(formState()))).toBe(true);
  });

  it('reports every invalid field at once', () => {
    const errors = validatePublicOrderForm(
      formState({ firstName: '', lastName: '', phone: '12', email: 'nope', paymentMethod: '', quantities: {}, notes: 'n'.repeat(600) }),
    );
    expect(Object.keys(errors).sort()).toEqual(['contact', 'email', 'firstName', 'lastName', 'lineItems', 'notes', 'paymentMethod']);
  });

  it('passes when a complete address stands in for a phone number', () => {
    const errors = validatePublicOrderForm(formState({ phone: '', address: { ...fullAddress } }));
    expect(errors.contact).toBeUndefined();
  });

  it('rejects a partial address even when a valid phone is present', () => {
    const errors = validatePublicOrderForm(formState({ address: { ...emptyAddress, street: '1 Main St' } }));
    expect(errors.contact).toBe('An address needs all four fields (missing: city, state, zipCode).');
  });
});
