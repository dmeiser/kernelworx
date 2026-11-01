/**
 * Tests for publicOrderValidation.
 *
 * The point of these rules is that the client must not admit anything the write
 * pipeline rejects: every case below is a form state that used to pass client
 * validation and then come back from the server as a bare `INVALID_INPUT` with
 * no field to blame. The expected wording is the server's own, copied from
 * `tofu/application/appsync/js-resolvers/lib/validation.js` and
 * `lib/public_order.js`, so a drift on either side shows up here.
 */
import { describe, it, expect } from 'vitest';
import {
  validatePublicOrderForm,
  normalizeUsPhone,
  zipCodeIsValid,
  emailShapeIsValid,
  addressStarted,
  MAX_EMAIL_LENGTH,
  MAX_ADDRESS_FIELD_LENGTH,
  type PublicOrderFormState,
} from '../../src/lib/publicOrderValidation';

const emptyAddress = { street: '', city: '', state: '', zipCode: '' };

/** A form that satisfies every rule; individual tests break one field at a time. */
const validForm = (overrides: Partial<PublicOrderFormState> = {}): PublicOrderFormState => ({
  firstName: 'Ada',
  lastName: 'Lovelace',
  phone: '555-123-4567',
  email: '',
  address: { ...emptyAddress },
  lineItems: { 'PROD#1': 2 },
  paymentMethod: 'Venmo',
  notes: '',
  ...overrides,
});

const completeAddress = { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' };

describe('normalizeUsPhone', () => {
  it('accepts a ten-digit number written with separators', () => {
    expect(normalizeUsPhone('(555) 123.4567')).toBe('5551234567');
  });

  it('drops a leading country code the way the server does', () => {
    expect(normalizeUsPhone('+1 555 123 4567')).toBe('5551234567');
  });

  it('rejects a number that is not ten digits once reduced', () => {
    expect(normalizeUsPhone('555-1234')).toBeNull();
    expect(normalizeUsPhone('555-123-45678')).toBeNull();
  });

  it('keeps an eleven-digit number that does not start with the country code', () => {
    // The server only strips an 11-digit number beginning with '1'; anything
    // else of that length is not a US number.
    expect(normalizeUsPhone('25512345678')).toBeNull();
  });
});

describe('zipCodeIsValid', () => {
  it('accepts 5 and 9 digit ZIPs once non-digits are stripped', () => {
    expect(zipCodeIsValid('62701')).toBe(true);
    expect(zipCodeIsValid('62701-1234')).toBe(true);
  });

  it('rejects every other length', () => {
    expect(zipCodeIsValid('6270')).toBe(false);
    expect(zipCodeIsValid('627011')).toBe(false);
    expect(zipCodeIsValid('abcde')).toBe(false);
  });
});

describe('emailShapeIsValid', () => {
  it('accepts a one-at address with a two-label domain', () => {
    expect(emailShapeIsValid('buyer@example.com')).toBe(true);
  });

  it('rejects the shapes the server rejects', () => {
    expect(emailShapeIsValid('no-at-sign')).toBe(false);
    expect(emailShapeIsValid('@example.com')).toBe(false);
    expect(emailShapeIsValid('a@b@c.com')).toBe(false);
    expect(emailShapeIsValid('buyer@example')).toBe(false);
    expect(emailShapeIsValid('buyer@example..com')).toBe(false);
  });
});

describe('validatePublicOrderForm contact rules', () => {
  it('accepts a phone-only form', () => {
    expect(validatePublicOrderForm(validForm()).isValid).toBe(true);
  });

  it('accepts a complete-address-only form', () => {
    const form = validForm({ phone: '', address: { ...completeAddress } });
    expect(validatePublicOrderForm(form).isValid).toBe(true);
  });

  it('requires a phone or an address', () => {
    const { errors } = validatePublicOrderForm(validForm({ phone: '' }));
    expect(errors.phone).toBe('Phone number or a complete address is required');
    expect(errors.address).toBe('Phone or a complete address is required');
  });

  it('rejects a phone that is not a 10-digit US number', () => {
    const { errors } = validatePublicOrderForm(validForm({ phone: '555-1234' }));
    expect(errors.phone).toBe('Phone number must be a valid 10-digit US number');
  });

  it('accepts a phone the server would normalize, such as a country-coded one', () => {
    expect(validatePublicOrderForm(validForm({ phone: '+1 (555) 123-4567' })).isValid).toBe(true);
  });
});

describe('validatePublicOrderForm address completeness', () => {
  it('rejects a started-but-partial address and names the missing fields', () => {
    const form = validForm({ phone: '', address: { ...emptyAddress, street: '1 Main St' } });
    const { isValid, errors } = validatePublicOrderForm(form);
    expect(isValid).toBe(false);
    expect(errors.address).toBe('Address is missing required fields: city, state, zipCode');
  });

  it('marks each missing address field individually so the form can highlight it', () => {
    const form = validForm({ phone: '', address: { ...emptyAddress, street: '1 Main St' } });
    const { errors } = validatePublicOrderForm(form);
    expect(errors.addressFields?.city).toBeTruthy();
    expect(errors.addressFields?.state).toBeTruthy();
    expect(errors.addressFields?.zipCode).toBeTruthy();
    expect(errors.addressFields?.street).toBeUndefined();
  });

  it('rejects a complete-looking address with a non-US ZIP', () => {
    const form = validForm({ phone: '', address: { ...completeAddress, zipCode: 'AB12' } });
    const { errors } = validatePublicOrderForm(form);
    expect(errors.address).toBe('ZIP code must be 5 or 9 digits');
    expect(errors.addressFields?.zipCode).toBe('ZIP code must be 5 or 9 digits');
  });

  it('accepts a ZIP+4 the way the server does', () => {
    const form = validForm({ phone: '', address: { ...completeAddress, zipCode: '62701-1234' } });
    expect(validatePublicOrderForm(form).isValid).toBe(true);
  });

  it('rejects an address field longer than the server cap', () => {
    const tooLong = 'x'.repeat(MAX_ADDRESS_FIELD_LENGTH + 1);
    const form = validForm({ phone: '', address: { ...completeAddress, street: tooLong } });
    const { errors } = validatePublicOrderForm(form);
    expect(errors.address).toBe(`Address fields must be at most ${MAX_ADDRESS_FIELD_LENGTH} characters`);
    expect(errors.addressFields?.street).toBeTruthy();
  });

  it('treats whitespace-only address fields as missing', () => {
    const form = validForm({ phone: '', address: { ...completeAddress, city: '   ' } });
    const { errors } = validatePublicOrderForm(form);
    expect(errors.address).toBe('Address is missing required fields: city');
  });
});

describe('validatePublicOrderForm email rules', () => {
  it('leaves an absent email valid', () => {
    expect(validatePublicOrderForm(validForm({ email: '' })).isValid).toBe(true);
  });

  it('rejects a malformed email instead of letting the server answer', () => {
    const { errors } = validatePublicOrderForm(validForm({ email: 'not-an-email' }));
    expect(errors.email).toBe('Email address is not valid');
  });

  it('rejects an email past the server cap', () => {
    const long = `${'a'.repeat(MAX_EMAIL_LENGTH)}@example.com`;
    const { errors } = validatePublicOrderForm(validForm({ email: long }));
    expect(errors.email).toBe(`Email address must be at most ${MAX_EMAIL_LENGTH} characters`);
  });
});

describe('validatePublicOrderForm remaining required fields', () => {
  it('requires both names', () => {
    const { errors } = validatePublicOrderForm(validForm({ firstName: '  ', lastName: '' }));
    expect(errors.firstName).toBe('First name is required');
    expect(errors.lastName).toBe('Last name is required');
  });

  it('requires at least one line item above zero', () => {
    const { errors } = validatePublicOrderForm(validForm({ lineItems: { 'PROD#1': 0 } }));
    expect(errors.lineItems).toBe('At least one product with quantity greater than zero is required');
  });

  it('requires a payment method', () => {
    const { errors } = validatePublicOrderForm(validForm({ paymentMethod: '' }));
    expect(errors.paymentMethod).toBe('Payment method is required');
  });
});

describe('validatePublicOrderForm isValid', () => {
  it('is false when only a nested address field error is present', () => {
    // The nested `addressFields` record must not read as "no error" just because
    // the aggregate scalar is undefined.
    const form = validForm({ phone: '', address: { ...completeAddress, zipCode: '12' } });
    const result = validatePublicOrderForm(form);
    expect(result.isValid).toBe(false);
  });

  it('is true for a form with no errors at all', () => {
    expect(validatePublicOrderForm(validForm()).isValid).toBe(true);
  });
});

describe('addressStarted', () => {
  it('is false for a wholly empty or absent address', () => {
    expect(addressStarted(emptyAddress)).toBe(false);
    expect(addressStarted(null)).toBe(false);
    expect(addressStarted(undefined)).toBe(false);
  });

  it('is true when any field carries non-whitespace text', () => {
    expect(addressStarted({ ...emptyAddress, state: 'IL' })).toBe(true);
    expect(addressStarted({ ...emptyAddress, city: '  ' })).toBe(false);
  });
});
