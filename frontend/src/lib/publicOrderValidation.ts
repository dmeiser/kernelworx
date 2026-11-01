/**
 * Validation rules and types for public order forms.
 *
 * The contact rules mirror the write pipeline's own validator
 * (`tofu/application/appsync/js-resolvers/lib/validation.js` and
 * `lib/public_order.js`) field for field, including its exact message wording:
 * a phone must reduce to a 10-digit US number, and an address that is started
 * at all must carry all four fields with a 5- or 9-digit ZIP. A client that is
 * looser than the server lets a buyer submit and take a generic `INVALID_INPUT`
 * rejection instead of a field-level error, so any drift here is a bug on both
 * sides — keep the two in step.
 */

// Maximum quantity allowed for any product in a public order
export const MAX_PUBLIC_QUANTITY = 99;

// Maximum length for buyer notes
export const MAX_BUYER_NOTES_LENGTH = 500;

// Caps mirrored from the write pipeline's own constants in lib/public_order.js.
// The name and notes inputs already carry matching `maxLength` attributes, so
// only the email and address caps need a validator: without them a buyer types
// an address the server will refuse and gets a bare `INVALID_INPUT` back.
export const MAX_EMAIL_LENGTH = 254;
export const MAX_ADDRESS_FIELD_LENGTH = 400;

/**
 * Check if an address has been started (at least one field filled).
 */
export function addressStarted(
  address:
    | {
        street?: string;
        city?: string;
        state?: string;
        zipCode?: string;
      }
    | null
    | undefined,
): boolean {
  if (!address) {
    return false;
  }
  return [address.street, address.city, address.state, address.zipCode].some((field) => Boolean(field?.trim()));
}

/**
 * Form address shape for public orders.
 */
export interface PublicOrderAddressForm {
  street: string;
  city: string;
  state: string;
  zipCode: string;
}

/** Per-address-field errors, so the form can mark the exact box at fault. */
export type PublicOrderAddressFieldErrors = Partial<Record<keyof PublicOrderAddressForm, string>>;

/**
 * Field-level errors for public order forms.
 */
export interface PublicOrderFieldErrors {
  firstName?: string;
  lastName?: string;
  phone?: string;
  email?: string;
  address?: string;
  addressFields?: PublicOrderAddressFieldErrors;
  lineItems?: string;
  paymentMethod?: string;
  notes?: string;
}

/**
 * Complete form state for public orders.
 */
export interface PublicOrderFormState {
  firstName: string;
  lastName: string;
  phone: string;
  email: string;
  address: {
    street: string;
    city: string;
    state: string;
    zipCode: string;
  };
  lineItems: Record<string, number>; // productId -> quantity
  paymentMethod: string;
  notes: string;
}

/**
 * Reduce a typed phone to its 10-digit US national number, or null when it is
 * not one. Mirrors the server: every non-digit is dropped, an 11-digit number
 * starting with the `1` country code loses that digit, and anything that is
 * left over is not a US number.
 */
export function normalizeUsPhone(raw: string): string | null {
  const digits = raw.replace(/\D/g, '');
  const national = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits;
  return national.length === 10 ? national : null;
}

/** Whether the typed ZIP reduces to the 5 or 9 digits the server accepts. */
export function zipCodeIsValid(raw: string): boolean {
  const digits = raw.replace(/\D/g, '');
  return digits.length === 5 || digits.length === 9;
}

/** The four address fields in the order the server names them in its error. */
const ADDRESS_FIELDS: (keyof PublicOrderAddressForm)[] = ['street', 'city', 'state', 'zipCode'];

/**
 * Whether a typed email has the shape the server accepts: exactly one `@`, a
 * non-empty local part, and a dot-separated domain of at least two non-empty
 * labels. Mirrors `validateEmail` in `lib/public_order.js`.
 */
export function emailShapeIsValid(raw: string): boolean {
  const parts = raw.trim().split('@');
  if (parts.length !== 2 || parts[0] === '') {
    return false;
  }
  const domainLabels = parts[1].split('.');
  return domainLabels.length >= 2 && domainLabels.every((label) => label !== '');
}

/**
 * An address that has been started at all must be complete: all four fields,
 * and a US ZIP. Recorded both as the aggregate `address` error (the server's
 * wording) and per field, so the form can mark the box actually at fault.
 */
function validateAddressCompleteness(form: PublicOrderFormState, errors: PublicOrderFieldErrors): void {
  const missing = ADDRESS_FIELDS.filter((field) => !form.address[field].trim());
  if (missing.length > 0) {
    errors.address = `Address is missing required fields: ${missing.join(', ')}`;
    const fieldErrors: PublicOrderAddressFieldErrors = {};
    missing.forEach((field) => {
      fieldErrors[field] = 'Required once an address is started.';
    });
    errors.addressFields = fieldErrors;
    return;
  }
  if (!zipCodeIsValid(form.address.zipCode)) {
    errors.address = 'ZIP code must be 5 or 9 digits';
    errors.addressFields = { zipCode: 'ZIP code must be 5 or 9 digits' };
    return;
  }

  // The server checks the per-field cap only once the address is complete, so
  // the same ordering here keeps the two error surfaces agreeing.
  const overlong = ADDRESS_FIELDS.filter((field) => form.address[field].trim().length > MAX_ADDRESS_FIELD_LENGTH);
  if (overlong.length > 0) {
    const message = `Address fields must be at most ${MAX_ADDRESS_FIELD_LENGTH} characters`;
    errors.address = message;
    errors.addressFields = overlong.reduce((acc, field) => {
      acc[field] = message;
      return acc;
    }, {} as PublicOrderAddressFieldErrors);
  }
}

/**
 * The email is optional, but when present it must satisfy the server's own
 * length cap and shape. A malformed address otherwise reaches the AWSEmail
 * scalar and comes back as an unexplained `INVALID_INPUT`.
 */
function validateOptionalEmail(form: PublicOrderFormState, errors: PublicOrderFieldErrors): void {
  const email = form.email.trim();
  if (!email) {
    return;
  }
  if (email.length > MAX_EMAIL_LENGTH) {
    errors.email = `Email address must be at most ${MAX_EMAIL_LENGTH} characters`;
    return;
  }
  if (!emailShapeIsValid(email)) {
    errors.email = 'Email address is not valid';
  }
}

/** A phone the buyer actually typed must reduce to a 10-digit US number. */
function validateProvidedPhone(form: PublicOrderFormState, errors: PublicOrderFieldErrors): void {
  if (normalizeUsPhone(form.phone) === null) {
    errors.phone = 'Phone number must be a valid 10-digit US number';
  }
}

/**
 * Require a phone number or a started address, and validate whichever the
 * buyer supplied against the server's rules.
 */
function validateContactRequirement(form: PublicOrderFormState, errors: PublicOrderFieldErrors): void {
  const hasPhone = Boolean(form.phone.trim());
  const hasAddress = addressStarted(form.address);
  if (!hasPhone && !hasAddress) {
    errors.phone = 'Phone number or a complete address is required';
    errors.address = 'Phone or a complete address is required';
    return;
  }
  if (hasPhone) {
    validateProvidedPhone(form, errors);
  }
  if (hasAddress) {
    validateAddressCompleteness(form, errors);
  }
}

/** Whether at least one line item has a positive quantity. */
function hasPositiveLineItems(lineItems: Record<string, number>): boolean {
  return Object.values(lineItems).some((quantity) => quantity > 0);
}

/**
 * True when no field carries an error. The scalar fields are listed by hand
 * rather than swept with `Object.values`, because `addressFields` is a nested
 * record and a swept check would read the record object itself as an error.
 */
function fieldErrorsAreEmpty(errors: PublicOrderFieldErrors): boolean {
  const scalarErrors = [
    errors.firstName,
    errors.lastName,
    errors.phone,
    errors.email,
    errors.address,
    errors.lineItems,
    errors.paymentMethod,
    errors.notes,
  ];
  return scalarErrors.every((error) => error === undefined) && Object.keys(errors.addressFields ?? {}).length === 0;
}

/**
 * Validate the entire public order form.
 * @param form - The form state to validate
 * @returns An object with isValid boolean and field-specific errors
 */
export function validatePublicOrderForm(form: PublicOrderFormState): {
  isValid: boolean;
  errors: PublicOrderFieldErrors;
} {
  const errors: PublicOrderFieldErrors = {};

  if (!form.firstName.trim()) {
    errors.firstName = 'First name is required';
  }
  if (!form.lastName.trim()) {
    errors.lastName = 'Last name is required';
  }
  validateContactRequirement(form, errors);
  validateOptionalEmail(form, errors);
  if (!hasPositiveLineItems(form.lineItems)) {
    errors.lineItems = 'At least one product with quantity greater than zero is required';
  }
  if (!form.paymentMethod.trim()) {
    errors.paymentMethod = 'Payment method is required';
  }

  return {
    isValid: fieldErrorsAreEmpty(errors),
    errors,
  };
}
