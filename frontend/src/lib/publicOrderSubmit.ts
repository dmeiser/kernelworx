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
import { addressStarted, type PublicOrderFormState } from './publicOrderValidation';
import type { PublicOfferView } from '../components/public/publicOrderTypes';
import type { PublicOrderSubmittedSummary } from '../components/public/PublicOrderSuccess';

/**
 * v1 sends the acknowledgement on the buyer's behalf: placing the order IS the
 * acceptance, and the buyer page renders no terms text of its own. Adding
 * buyer-facing terms is a captain product decision, not a code change.
 */
export const BUYER_ACKNOWLEDGEMENTS_ACCEPTED = true;

/** Line items the buyer actually added (quantity > 0), in offer order. */
export function buildPublicLineItems(form: PublicOrderFormState): { productId: string; quantity: number }[] {
  return Object.entries(form.quantities)
    .filter(([, quantity]) => quantity > 0)
    .map(([productId, quantity]) => ({ productId, quantity }));
}

/** The full publicCreateOrder input for a validated form. */
export function buildPublicOrderInput(args: {
  profileId: string;
  token: string;
  campaignId: string;
  form: PublicOrderFormState;
}): GqlPublicCreateOrderInput {
  const { profileId, token, campaignId, form } = args;
  const input: GqlPublicCreateOrderInput = {
    profileId,
    token,
    campaignId,
    acknowledgementsAccepted: BUYER_ACKNOWLEDGEMENTS_ACCEPTED,
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    paymentMethod: form.paymentMethod,
    lineItems: buildPublicLineItems(form),
  };

  const phone = form.phone.trim();
  if (phone) input.phone = phone;

  if (addressStarted(form.address)) {
    input.address = {
      street: form.address.street.trim(),
      city: form.address.city.trim(),
      state: form.address.state.trim(),
      zipCode: form.address.zipCode.trim(),
    };
  }

  const email = form.email.trim();
  if (email) input.email = email;

  const notes = form.notes.trim();
  if (notes) input.notes = notes;

  return input;
}

/** What the success screen echoes back, using the offer's product names. */
export function buildSubmittedSummary(
  form: PublicOrderFormState,
  offer: PublicOfferView,
): PublicOrderSubmittedSummary {
  const nameById = new Map(offer.products.map((product) => [product.productId, product]));
  const lineItems = buildPublicLineItems(form).map((item) => {
    const product = nameById.get(item.productId);
    const pricePerUnit = product ? product.price : 0;
    return {
      productName: product ? product.productName : item.productId,
      quantity: item.quantity,
      subtotal: Number((pricePerUnit * item.quantity).toFixed(2)),
    };
  });

  return {
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    paymentMethod: form.paymentMethod,
    phone: form.phone.trim() || undefined,
    email: form.email.trim() || undefined,
    lineItems,
  };
}
