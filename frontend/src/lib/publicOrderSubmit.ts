/**
 * Building the publicCreateOrder input and the success-screen summary.
 *
 * The campaign id is echoed from the offer rather than taken from anywhere the
 * buyer could steer: a seller who re-picks their anchor campaign between page
 * load and submit gets a NOT_FOUND instead of an order filed against a campaign
 * the buyer never saw. Optional fields are omitted rather than sent as null, so
 * the server's "absent means absent" validation is not confused by an empty
 * string.
 */

import type { GqlPublicCreateOrderInput } from '../types/graphql-generated';
import { addressStarted, MAX_PUBLIC_QUANTITY, type PublicOrderFormState } from './publicOrderValidation';
import type { PublicOfferView } from '../components/public/publicOrderTypes';
import type { PublicOrderSubmittedSummary } from '../components/public/PublicOrderSuccess';

/**
 * v1 sends the acknowledgement on the buyer's behalf: placing the order IS the
 * acceptance, and the buyer page renders no terms text of its own. Adding
 * buyer-facing terms is a captain product decision, not a code change.
 */
export const BUYER_ACKNOWLEDGEMENTS_ACCEPTED = true;

/**
 * Build the GraphQL input for publicCreateOrder.
 *
 * @param token       The share token from the offer.
 * @param campaignId  The campaign ID from the offer.
 * @param form        The form state.
 */
export function buildPublicOrderInput(args: {
  token: string;
  campaignId: string;
  form: PublicOrderFormState;
}): GqlPublicCreateOrderInput {
  const { token, campaignId, form } = args;
  const input: GqlPublicCreateOrderInput = {
    campaignId,
    token,
    acknowledgementsAccepted: BUYER_ACKNOWLEDGEMENTS_ACCEPTED,
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    paymentMethod: form.paymentMethod,
    lineItems: submittedLineItems(form.lineItems),
  };

  const phone = form.phone.trim();
  if (phone) input.phone = phone;

  const address = form.address;
  if (addressStarted(address)) {
    input.address = {
      street: address.street.trim(),
      city: address.city.trim(),
      state: address.state.trim(),
      zipCode: address.zipCode.trim(),
    };
  }

  const email = form.email.trim();
  if (email) input.email = email;

  const notes = form.notes.trim();
  if (notes) input.notes = notes;

  return input;
}

/**
 * The line items the buyer actually submitted: a quantity counts only when it
 * is a whole number inside the picker's range, so an out-of-range value can
 * never reach the server, and the on-screen estimate and the success summary
 * are computed from exactly this set.
 */
export function submittedLineItems(lineItems: Record<string, number>): { productId: string; quantity: number }[] {
  return Object.entries(lineItems)
    .filter(([productId, quantity]) => productId.length > 0 && quantityIsValid(quantity))
    .map(([productId, quantity]) => ({ productId, quantity }));
}

function quantityIsValid(quantity: number): boolean {
  return Number.isInteger(quantity) && quantity > 0 && quantity <= MAX_PUBLIC_QUANTITY;
}

/**
 * Build the success-screen summary from the form and the offer.
 *
 * The item rows are the submitted quantities joined against the offer's
 * products — the same products the buyer picked from, at the prices the offer
 * showed them. A product id the offer no longer carries is dropped rather than
 * shown with a made-up name. The payment method is the one the buyer selected;
 * `storedPaymentMethod` (the value the create mutation echoed back) wins when
 * the response carries one, because that is what the order actually stored.
 */
export function buildSubmittedSummary(
  form: PublicOrderFormState,
  offer: PublicOfferView,
  storedPaymentMethod?: string | null,
): PublicOrderSubmittedSummary {
  const productsById = new Map(offer.products.map((product) => [product.productId, product]));
  const lineItems = submittedLineItems(form.lineItems).flatMap((item) => {
    const product = productsById.get(item.productId);
    if (!product) {
      return [];
    }
    return [
      {
        productId: item.productId,
        productName: product.productName,
        quantity: item.quantity,
        pricePerUnit: product.price,
        subtotal: product.price * item.quantity,
      },
    ];
  });

  return {
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    paymentMethod: storedPaymentMethod?.trim() || form.paymentMethod,
    phone: form.phone.trim() || undefined,
    email: form.email.trim() || undefined,
    lineItems,
  };
}
