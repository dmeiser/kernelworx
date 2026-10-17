/**
 * Validation rules and types for public order forms.
 */

// Maximum quantity allowed for any product in a public order
export const MAX_PUBLIC_QUANTITY = 99;

// Maximum length for buyer notes
export const MAX_BUYER_NOTES_LENGTH = 500;

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

/**
 * Field-level errors for public order forms.
 */
export interface PublicOrderFieldErrors {
  firstName?: string;
  lastName?: string;
  phone?: string;
  email?: string;
  address?: string;
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
 * Require a phone number or a started address, recording both error fields
 * when neither is present.
 */
function validateContactRequirement(form: PublicOrderFormState, errors: PublicOrderFieldErrors): void {
  const hasPhone = Boolean(form.phone.trim());
  const hasAddress = addressStarted(form.address);
  if (hasPhone || hasAddress) {
    return;
  }
  errors.phone = 'Phone number or a complete address is required';
  errors.address = 'Phone or a complete address is required';
}

/** Whether at least one line item has a positive quantity. */
function hasPositiveLineItems(lineItems: Record<string, number>): boolean {
  return Object.values(lineItems).some((quantity) => quantity > 0);
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
  if (!hasPositiveLineItems(form.lineItems)) {
    errors.lineItems = 'At least one product with quantity greater than zero is required';
  }
  if (!form.paymentMethod.trim()) {
    errors.paymentMethod = 'Payment method is required';
  }

  return {
    isValid: Object.values(errors).every((error) => error === undefined),
    errors,
  };
}

/**
 * Check if the public order form is valid.
 * @param form - The form state to check
 * @returns True if valid, false otherwise
 */
export function publicOrderFormIsValid(form: PublicOrderFormState): boolean {
  return validatePublicOrderForm(form).isValid;
}
