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

/**
 * Build the GraphQL input for publicCreateOrder.
 *
 * @param profileId   The profile ID is *not* used in the input; it is kept in the
 *                    argument list only to maintain compatibility with the
 *                    hook signature. The server expects the campaignId and token
 *                    from the offer, not the profileId.
 * @param token       The share token from the offer.
 * @param campaignId  The campaign ID from the offer.
 * @param form        The form state.
 */
export function buildPublicOrderInput(args: {
  profileId: string; // unused, kept for hook compatibility
  token: string;
  campaignId: string;
  form: PublicOrderFormState;
}): GqlPublicCreateOrderInput {
  const { token, campaignId, form } = args; // profileId is unused
  const input: GqlPublicCreateOrderInput = {
    campaignId,
    token,
    acknowledgementsAccepted: BUYER_ACKNOWLEDGEMENTS_ACCEPTED,
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    paymentMethod: form.paymentMethod,
    lineItems: buildPublicLineItems(form),
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
 * Build the line items array for the input.
 */
function buildPublicLineItems(form: PublicOrderFormState): {
  productId: string;
  quantity: number;
}[] {
  return Object.entries(form.lineItems)
    .filter((entry) => entry[1] > 0)
    .map(([productId, quantity]) => ({
      productId,
      quantity,
    }));
}

/**
 * Build the success-screen summary from the form and the offer.
 */
export function buildSubmittedSummary(
  form: PublicOrderFormState,
  offer: PublicOfferView,
): PublicOrderSubmittedSummary {
    const paymentMethod = offer.paymentMethods[0]?.name ?? form.paymentMethod;
    return {
      firstName: form.firstName.trim(),
      lastName: form.lastName.trim(),
      paymentMethod,
      phone: form.phone.trim() || undefined,
      email: form.email.trim() || undefined,
      lineItems: [],
    };
  }
