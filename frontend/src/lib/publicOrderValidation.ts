/**
 * Client-side validation for the public order form.
 *
 * These rules mirror the server-side validators the same request hits
 * (`tofu/application/appsync/js-resolvers/lib/validation.js` runs
 * `validatePhone`/`validateAddress` inside the create pipeline) so the buyer
 * sees the US-only semantics stated inline instead of bouncing off a GraphQL
 * error. The server stays authoritative: this is a UX layer, not a trust
 * boundary.
 */

/** Max length of a buyer name, matching the schema's maxLength bound. */
export const MAX_BUYER_NAME_LENGTH = 100;

/** Max length of the buyer's notes (400KB item guard on the server). */
export const MAX_BUYER_NOTES_LENGTH = 500;

/** Max length of the buyer's email address. */
export const MAX_BUYER_EMAIL_LENGTH = 254;

/** Max length of one address field, matching the server cap. */
export const MAX_ADDRESS_FIELD_LENGTH = 400;

/** Max line items in one public order. */
export const MAX_PUBLIC_LINE_ITEMS = 20;

/** Smallest quantity accepted for one line item. */
export const MIN_PUBLIC_QUANTITY = 1;

/** Largest quantity accepted for one line item. */
export const MAX_PUBLIC_QUANTITY = 999;

/** Loose email shape check; the server applies the AWSEmail scalar. */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The four address fields; all are required once an address is started. */
export const REQUIRED_ADDRESS_FIELDS: readonly string[] = ['street', 'city', 'state', 'zipCode'];

export interface PublicOrderAddressForm {
  street: string;
  city: string;
  state: string;
  zipCode: string;
}

export interface PublicOrderFormState {
  firstName: string;
  lastName: string;
  phone: string;
  email: string;
  address: PublicOrderAddressForm;
  paymentMethod: string;
  notes: string;
  /** productId -> quantity, for products the buyer added to the order. */
  quantities: Record<string, number>;
}

export type PublicOrderField = 'firstName' | 'lastName' | 'contact' | 'email' | 'paymentMethod' | 'lineItems' | 'notes';

export type PublicOrderFieldErrors = Partial<Record<PublicOrderField, string>>;

/** True when the buyer typed anything into the address block. */
export function addressStarted(address: PublicOrderAddressForm): boolean {
  return REQUIRED_ADDRESS_FIELDS.some(
    (field) => String(address[field as keyof PublicOrderAddressForm] || '').trim() !== '',
  );
}

/** US phone semantics: ten digits, tolerating separators and a leading 1. */
export function validateBuyerPhone(phone: string): string | null {
  const trimmed = phone.trim();
  if (!trimmed) return 'Enter a phone number or a complete address.';
  const digits = trimmed.replace(/\D/g, '');
  const normalized = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits;
  if (normalized.length !== 10) return 'Phone number must be a valid 10-digit US number.';
  return null;
}

/** Address semantics: all four fields plus a 5- or 9-digit US ZIP. */
export function validateBuyerAddress(address: PublicOrderAddressForm): string | null {
  const missing = REQUIRED_ADDRESS_FIELDS.filter(
    (field) => address[field as keyof PublicOrderAddressForm].trim() === '',
  );
  if (missing.length > 0) {
    return `An address needs all four fields (missing: ${missing.join(', ')}).`;
  }
  const tooLong = REQUIRED_ADDRESS_FIELDS.filter(
    (field) => address[field as keyof PublicOrderAddressForm].trim().length > MAX_ADDRESS_FIELD_LENGTH,
  );
  if (tooLong.length > 0) {
    return `Address fields must be at most ${MAX_ADDRESS_FIELD_LENGTH} characters (too long: ${tooLong.join(', ')}).`;
  }
  const zipDigits = address.zipCode.trim().replace(/\D/g, '');
  if (zipDigits.length !== 5 && zipDigits.length !== 9) {
    return 'ZIP code must be 5 or 9 digits.';
  }
  return null;
}

/** Phone OR a complete address is required; the error is reported once. */
export function validateBuyerContact(phone: string, address: PublicOrderAddressForm): string | null {
  const trimmedPhone = phone.trim();
  if (!trimmedPhone && !addressStarted(address)) {
    return 'Enter a phone number or a complete address so the seller can reach you.';
  }
  if (trimmedPhone && addressStarted(address)) {
    const phoneFailure = validateBuyerPhone(trimmedPhone);
    if (phoneFailure) return phoneFailure;
    return validateBuyerAddress(address);
  }
  if (trimmedPhone) return validateBuyerPhone(trimmedPhone);
  return validateBuyerAddress(address);
}

/** Email is optional but must look like an address when present. */
export function validateBuyerEmail(email: string): string | null {
  const trimmed = email.trim();
  if (!trimmed) return null;
  if (trimmed.length > MAX_BUYER_EMAIL_LENGTH) return `Email must be at most ${MAX_BUYER_EMAIL_LENGTH} characters.`;
  if (!EMAIL_PATTERN.test(trimmed)) return 'Enter a valid email address.';
  return null;
}

/** A trimmed, non-empty name within the schema's length bound. */
export function validateBuyerName(value: string, label: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return `${label} is required.`;
  if (trimmed.length > MAX_BUYER_NAME_LENGTH) return `${label} must be at most ${MAX_BUYER_NAME_LENGTH} characters.`;
  return null;
}

/** At least one line item, at most twenty, each quantity within bounds. */
export function validateLineItems(quantities: Record<string, number>): string | null {
  const entries = Object.entries(quantities).filter(([, quantity]) => quantity > 0);
  if (entries.length === 0) return 'Add at least one product to your order.';
  if (entries.length > MAX_PUBLIC_LINE_ITEMS) return `An order can have at most ${MAX_PUBLIC_LINE_ITEMS} products.`;
  const outOfRange = entries.some(([, quantity]) => quantity < MIN_PUBLIC_QUANTITY || quantity > MAX_PUBLIC_QUANTITY);
  if (outOfRange) {
    return `Quantities must be between ${MIN_PUBLIC_QUANTITY} and ${MAX_PUBLIC_QUANTITY}.`;
  }
  return null;
}

/** Notes are optional but bounded. */
export function validateBuyerNotes(notes: string): string | null {
  return notes.length > MAX_BUYER_NOTES_LENGTH ? `Notes must be at most ${MAX_BUYER_NOTES_LENGTH} characters.` : null;
}

/** Each field's message, computed only when the field is invalid. */
const FIELD_VALIDATORS: { field: PublicOrderField; message: (state: PublicOrderFormState) => string | null }[] = [
  { field: 'firstName', message: (state) => validateBuyerName(state.firstName, 'First name') },
  { field: 'lastName', message: (state) => validateBuyerName(state.lastName, 'Last name') },
  { field: 'contact', message: (state) => validateBuyerContact(state.phone, state.address) },
  { field: 'email', message: (state) => validateBuyerEmail(state.email) },
  { field: 'paymentMethod', message: (state) => (state.paymentMethod ? null : 'Choose how you will pay.') },
  { field: 'lineItems', message: (state) => validateLineItems(state.quantities) },
  { field: 'notes', message: (state) => validateBuyerNotes(state.notes) },
];

/** Validate the whole form and return per-field messages. */
export function validatePublicOrderForm(state: PublicOrderFormState): PublicOrderFieldErrors {
  const errors: PublicOrderFieldErrors = {};
  FIELD_VALIDATORS.forEach(({ field, message }) => {
    const failure = message(state);
    if (failure) errors[field] = failure;
  });
  return errors;
}

/** True when the form has no validation errors. */
export function publicOrderFormIsValid(errors: PublicOrderFieldErrors): boolean {
  return Object.keys(errors).length === 0;
}
