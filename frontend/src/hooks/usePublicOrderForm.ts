/**
 * Form state and submission for the public order page.
 *
 * The submit button is disabled while the mutation is in flight: v1 has no
 * idempotency key, so a double-tap would create two orders and burn two slots
 * of the campaign's cap. Beyond that the hook only owns local state — the
 * server re-validates every rule this mirrors.
 */

import { useMemo, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/apollo';
import { PUBLIC_CREATE_ORDER } from '../lib/publicOrderGraphQL';
import type { GqlPublicCreateOrderMutation, GqlPublicCreateOrderMutationVariables } from '../types/graphql-generated';
import { buildPublicOrderInput, buildSubmittedSummary } from '../lib/publicOrderSubmit';
import {
  publicOrderFormIsValid,
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
  quantities: {},
});

interface UsePublicOrderFormArgs {
  profileId: string;
  token: string;
  offer: PublicOfferView;
}

export function usePublicOrderForm({ profileId, token, offer }: UsePublicOrderFormArgs) {
  const [form, setForm] = useState<PublicOrderFormState>(emptyForm);
  const [errors, setErrors] = useState<PublicOrderFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [noEmailPrompt, setNoEmailPrompt] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PublicOrderReceiptView | null>(null);
  const [summary, setSummary] = useState<PublicOrderSubmittedSummary | null>(null);

  const [mutate] = useMutation<GqlPublicCreateOrderMutation, GqlPublicCreateOrderMutationVariables>(PUBLIC_CREATE_ORDER);

  const setField = (field: PublicOrderTextField, value: string) =>
    setForm((previous) => ({ ...previous, [field]: value }));

  const setAddressField = (field: keyof PublicOrderAddressForm, value: string) =>
    setForm((previous) => ({ ...previous, address: { ...previous.address, [field]: value } }));

  const setQuantity = (productId: string, quantity: number) =>
    setForm((previous) => ({ ...previous, quantities: { ...previous.quantities, [productId]: quantity } }));

  const submitNow = async () => {
    setNoEmailPrompt(false);
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await mutate({
        variables: { input: buildPublicOrderInput({ profileId, token, campaignId: offer.campaignId, form }) },
      });
      const created = result.data?.publicCreateOrder;
      if (created) {
        setSummary(buildSubmittedSummary(form, offer));
        setReceipt({
          orderId: created.orderId,
          receiptUrl: created.receiptUrl,
          totalAmount: created.totalAmount,
          buyerEmailProvided: created.buyerEmailProvided,
          confirmationEmailSent: created.confirmationEmailSent,
        });
      }
    } catch (mutationError) {
      setSubmitError(mapErrorCodeToMessage(getErrorCode(mutationError), getErrorMessage(mutationError)));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = async () => {
    const validationErrors = validatePublicOrderForm(form);
    setErrors(validationErrors);
    if (!publicOrderFormIsValid(validationErrors)) return;
    if (!form.email.trim()) {
      setNoEmailPrompt(true);
      return;
    }
    await submitNow();
  };

  const totalAmount = useMemo(
    () =>
      Object.entries(form.quantities).reduce((total, [productId, quantity]) => {
        const product = offer.products.find((candidate) => candidate.productId === productId);
        return total + (product ? product.price : 0) * quantity;
      }, 0),
    [form.quantities, offer.products],
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
