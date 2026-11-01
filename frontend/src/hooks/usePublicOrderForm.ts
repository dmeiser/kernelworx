/**
 * Form state and submission for the public order page.
 *
 * Submission is guarded three ways, because v1 has no idempotency key and a
 * double-tap is two orders burning two slots of the campaign's cap: the submit
 * button and the confirmation dialog's buttons are disabled in flight, and
 * `submitNow` itself refuses to re-enter. Beyond that the hook only owns local
 * state — the server re-validates every rule this mirrors.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { mapPublicSubmissionErrorMessage } from '../lib/api-utils';
import { PUBLIC_CREATE_ORDER } from '../lib/publicOrderGraphQL';
import type { GqlPublicCreateOrderMutation, GqlPublicCreateOrderMutationVariables } from '../types/graphql-generated';
import { buildPublicOrderInput, buildSubmittedSummary, submittedLineItems } from '../lib/publicOrderSubmit';
import {
  MAX_PUBLIC_QUANTITY,
  validatePublicOrderForm,
  type PublicOrderAddressForm,
  type PublicOrderFieldErrors,
  type PublicOrderFormState,
} from '../lib/publicOrderValidation';
import type { PublicOfferView } from '../components/public/publicOrderTypes';
import type { PublicOrderReceiptView, PublicOrderSubmittedSummary } from '../components/public/PublicOrderSuccess';

const EMPTY_ADDRESS: PublicOrderAddressForm = { street: '', city: '', state: '', zipCode: '' };

/** Free-text form fields the buyer types into. */
export type PublicOrderTextField = 'firstName' | 'lastName' | 'phone' | 'email' | 'paymentMethod' | 'notes';

const emptyForm = (): PublicOrderFormState => ({
  firstName: '',
  lastName: '',
  phone: '',
  email: '',
  address: { ...EMPTY_ADDRESS },
  paymentMethod: '',
  notes: '',
  lineItems: {},
});

/**
 * A typed quantity is clamped to the picker's range the moment it arrives.
 * A free-typed number field can carry a negative, a fraction, or NaN, and an
 * unclamped negative subtracts from the on-screen total while the submit path
 * drops the line — the buyer then sees a total that is not the order they
 * place.
 */
function clampQuantity(quantity: number): number {
  if (!Number.isFinite(quantity)) {
    return 0;
  }
  return Math.min(MAX_PUBLIC_QUANTITY, Math.max(0, Math.trunc(quantity)));
}

/**
 * The success-screen state a create response implies, kept as a pure function so
 * the submit path stays a single linear flow.
 *
 * The create response carries no payment-method field today; it is read
 * defensively so the stored value wins as soon as the schema echoes it.
 */
function outcomeOfSubmission(
  form: PublicOrderFormState,
  offer: PublicOfferView,
  created: GqlPublicCreateOrderMutation['publicCreateOrder'],
): { summary: PublicOrderSubmittedSummary; receipt: PublicOrderReceiptView } {
  const storedPaymentMethod = (created as { paymentMethodName?: string | null }).paymentMethodName;
  return {
    summary: buildSubmittedSummary(form, offer, storedPaymentMethod),
    receipt: {
      orderId: created.orderId,
      receiptUrl: created.receiptUrl,
      totalAmount: created.totalAmount,
      buyerEmailProvided: created.buyerEmailProvided,
      confirmationEmailSent: created.confirmationEmailSent,
    },
  };
}

interface UsePublicOrderFormArgs {
  offer: PublicOfferView;
  token: string;
}

export function usePublicOrderForm({ offer, token }: UsePublicOrderFormArgs) {
  const [form, setForm] = useState<PublicOrderFormState>(emptyForm);
  const [errors, setErrors] = useState<PublicOrderFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [noEmailPrompt, setNoEmailPrompt] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PublicOrderReceiptView | null>(null);
  const [summary, setSummary] = useState<PublicOrderSubmittedSummary | null>(null);

  const [mutate] = useMutation<GqlPublicCreateOrderMutation, GqlPublicCreateOrderMutationVariables>(
    PUBLIC_CREATE_ORDER,
  );

  // Stable identities: the product rows are memoized, and a setter recreated on
  // every render would defeat that and re-render the whole catalog per
  // keystroke.
  const setField = useCallback(
    (field: PublicOrderTextField, value: string) => setForm((previous) => ({ ...previous, [field]: value })),
    [],
  );

  const setAddressField = useCallback(
    (field: keyof PublicOrderAddressForm, value: string) =>
      setForm((previous) => ({ ...previous, address: { ...previous.address, [field]: value } })),
    [],
  );

  const setQuantity = useCallback((productId: string, quantity: number) => {
    const clamped = clampQuantity(quantity);
    setForm((previous) => ({ ...previous, lineItems: { ...previous.lineItems, [productId]: clamped } }));
  }, []);

  // A ref, not the `submitting` state: two taps inside one React batch both
  // read the pre-update state, so the state flag alone cannot close the
  // re-entry window. The ref covers a strictly wider span than the state
  // (it is set before `setSubmitting` and cleared after it), so it is the
  // single authoritative guard.
  const inFlight = useRef(false);

  const submitNow = async () => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setNoEmailPrompt(false);
    setSubmitting(true);
    // Cleared up front: a stale error from a failed attempt must not sit above
    // a form the buyer has since corrected, and must not be mistaken for the
    // outcome of this attempt.
    setSubmitError(null);
    try {
      const result = await mutate({
        variables: { input: buildPublicOrderInput({ token, campaignId: offer.campaignId, form }) },
      });
      const created = result.data?.publicCreateOrder;
      if (created) {
        const outcome = outcomeOfSubmission(form, offer, created);
        setSummary(outcome.summary);
        setReceipt(outcome.receipt);
      }
    } catch (mutationError) {
      // Anonymous page: never echo the server's raw wording for a code we do
      // not understand (see mapPublicSubmissionErrorMessage).
      setSubmitError(mapPublicSubmissionErrorMessage(mutationError));
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  const submit = async () => {
    const validation = validatePublicOrderForm(form);
    setErrors(validation.errors);
    if (!validation.isValid) return;
    if (!form.email.trim()) {
      setNoEmailPrompt(true);
      return;
    }
    await submitNow();
  };

  // Unit prices are looked up by id once per offer, not per line item per
  // keystroke; the estimate is built from exactly the items the submit path
  // will send, so the two can never disagree.
  const priceById = useMemo(
    () => new Map(offer.products.map((product) => [product.productId, product.price])),
    [offer.products],
  );

  const totalAmount = useMemo(
    () =>
      submittedLineItems(form.lineItems).reduce(
        (total, item) => total + (priceById.get(item.productId) ?? 0) * item.quantity,
        0,
      ),
    [form.lineItems, priceById],
  );

  return {
    form,
    errors,
    submitting,
    noEmailPrompt,
    submitError,
    receipt,
    summary,
    totalAmount,
    setField,
    setAddressField,
    setQuantity,
    setNoEmailPrompt,
    submit,
    submitNow,
  };
}
