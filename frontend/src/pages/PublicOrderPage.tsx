/**
 * The buyer's public order page: /o/:profileId/:token
 *
 * Reached by scanning the seller's QR at an event. The token in the path is the
 * whole authorization, so this route is wrapped in the API-key-only Apollo
 * client (see App.tsx) and never attaches a session.
 *
 * Field order follows the spec: first/last name, phone OR address (US-only rules
 * stated inline), optional email, the catalog product picker, the payment method
 * radio list, notes, then submit.
 */

import { useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { Alert, Box, Button, Divider, Paper, Stack, TextField, Typography } from '@mui/material';
import { LoadingState } from '../components/LoadingState';
import { NoIndexMeta } from '../components/NoIndexMeta';
import { PublicPageUnavailable } from '../components/public/PublicPageUnavailable';
import { BuyerContactFields } from '../components/public/BuyerContactFields';
import { ProductPicker } from '../components/public/ProductPicker';
import { PaymentMethodChoice } from '../components/public/PaymentMethodChoice';
import { NoEmailConfirmDialog } from '../components/public/NoEmailConfirmDialog';
import { PublicOrderSuccess } from '../components/public/PublicOrderSuccess';
import { formatCurrency } from '../lib/api-utils';
import { MAX_BUYER_NOTES_LENGTH } from '../lib/publicOrderValidation';
import { usePublicOrderForm } from '../hooks/usePublicOrderForm';
import { usePublicOrderOffer } from '../hooks/usePublicOrderOffer';
import type { PublicOfferView } from '../components/public/publicOrderTypes';

export const NO_METHODS_MESSAGE = 'This seller has no payment methods available right now. Please check back later.';

/**
 * An offer with an empty product or method list is a valid response (the server
 * returns NOT_FOUND for a dead link instead), so the form renders disabled with
 * this message rather than pretending the link is broken.
 */
function offerIsOrderable(offer: PublicOfferView): boolean {
  return offer.paymentMethods.length > 0 && offer.products.length > 0;
}

const NoMethodsAlert: React.FC<{ offer: PublicOfferView }> = ({ offer }) =>
  offerIsOrderable(offer) ? null : (
    <Alert severity="info" sx={{ mb: 2 }} data-testid="no-methods-alert">
      {NO_METHODS_MESSAGE}
    </Alert>
  );

const SubmitErrorAlert: React.FC<{ message: string | null }> = ({ message }) =>
  message ? (
    <Alert severity="error" sx={{ mb: 2 }} data-testid="submit-error">
      {message}
    </Alert>
  ) : null;

const FieldError: React.FC<{ message: string | undefined }> = ({ message }) =>
  message ? (
    <Typography variant="body2" color="error" sx={{ mb: 2 }}>
      {message}
    </Typography>
  ) : null;

interface NotesFieldProps {
  value: string;
  errorText: string | undefined;
  onChange: (value: string) => void;
}

const NotesField: React.FC<NotesFieldProps> = ({ value, errorText, onChange }) => (
  <TextField
    fullWidth
    multiline
    minRows={2}
    label="Notes (optional)"
    value={value}
    onChange={(event) => onChange(event.target.value)}
    error={Boolean(errorText)}
    helperText={errorText || `Anything the seller should know. Up to ${MAX_BUYER_NOTES_LENGTH} characters.`}
    inputProps={{ maxLength: MAX_BUYER_NOTES_LENGTH }}
    sx={{ mb: 3 }}
  />
);

interface SubmitButtonProps {
  submitting: boolean;
  disabled: boolean;
  onSubmit: () => void;
}

/** Disabled in flight: v1 has no idempotency key, so a double-tap is two orders. */
const SubmitButton: React.FC<SubmitButtonProps> = ({ submitting, disabled, onSubmit }) => (
  <Button
    variant="contained"
    size="large"
    onClick={onSubmit}
    disabled={submitting || disabled}
    data-testid="submit-order"
  >
    {submitting ? 'Placing your order…' : 'Place order'}
  </Button>
);

interface FormViewProps {
  offer: PublicOfferView;
  profileId: string;
  token: string;
  onQrExpired: () => void;
}

const FormView: React.FC<FormViewProps> = ({ offer, profileId, token, onQrExpired }) => {
  const order = usePublicOrderForm({ profileId, token, offer });

  if (order.receipt && order.summary) {
    return <PublicOrderSuccess receipt={order.receipt} summary={order.summary} />;
  }

  return (
    <Box component="form" onSubmit={(event) => event.preventDefault()} sx={{ maxWidth: 640, mx: 'auto' }}>
      <Typography variant="h4" gutterBottom>
        {offer.sellerName}
      </Typography>
      <Typography variant="body1" color="text.secondary" gutterBottom>
        {offer.campaignName}
      </Typography>

      <NoMethodsAlert offer={offer} />
      <SubmitErrorAlert message={order.submitError} />

      <BuyerContactFields
        firstName={order.form.firstName}
        lastName={order.form.lastName}
        phone={order.form.phone}
        email={order.form.email}
        address={order.form.address}
        errors={order.errors}
        onFieldChange={order.setField}
        onAddressChange={order.setAddressField}
      />

      <Divider sx={{ my: 3 }} />

      <ProductPicker
        products={offer.products}
        quantities={order.form.quantities}
        onQuantityChange={order.setQuantity}
        errorText={order.errors.lineItems}
      />

      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="order-total">
        Estimated total: {formatCurrency(order.totalAmount)}
      </Typography>

      <Divider sx={{ my: 3 }} />

      <Typography variant="subtitle1" fontWeight="medium" gutterBottom>
        Payment method
      </Typography>
      <Stack spacing={1.5} sx={{ mb: 1 }}>
        {offer.paymentMethods.map((method) => (
          <PaymentMethodChoice
            key={method.name}
            method={method}
            selected={order.form.paymentMethod === method.name}
            onSelect={(name) => order.setField('paymentMethod', name)}
            onQrExpired={onQrExpired}
          />
        ))}
      </Stack>
      <FieldError message={order.errors.paymentMethod} />

      <NotesField
        value={order.form.notes}
        errorText={order.errors.notes}
        onChange={(value) => order.setField('notes', value)}
      />

      <SubmitButton
        submitting={order.submitting}
        disabled={!offerIsOrderable(offer)}
        onSubmit={() => void order.submit()}
      />

      <NoEmailConfirmDialog
        open={order.noEmailPrompt}
        onGoBack={() => order.setNoEmailPrompt(false)}
        onContinue={() => void order.submitNow()}
      />
    </Box>
  );
};

interface BodyProps {
  complete: boolean;
  loading: boolean;
  offer: PublicOfferView | null;
  profileId: string;
  token: string;
  onQrExpired: () => void;
}

const PublicOrderBody: React.FC<BodyProps> = ({ complete, loading, offer, profileId, token, onQrExpired }) => {
  if (!complete) return <PublicPageUnavailable />;
  if (loading && !offer) return <LoadingState />;
  if (!offer) return <PublicPageUnavailable />;
  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <FormView offer={offer} profileId={profileId} token={token} onQrExpired={onQrExpired} />
    </Paper>
  );
};

const OfferRefreshWarning: React.FC<{ hasError: boolean; hasOffer: boolean }> = ({ hasError, hasOffer }) =>
  hasError && hasOffer ? (
    <Alert severity="warning" sx={{ mt: 2 }}>
      Some of this page could not be refreshed.
    </Alert>
  ) : null;

export const PublicOrderPage: React.FC = () => {
  const params = useParams<{ profileId: string; token: string }>();
  const profileId = params.profileId ?? '';
  const token = params.token ?? '';
  const { offer, loading, error, refetch } = usePublicOrderOffer(profileId, token);

  // A pre-signed QR URL expires after 15 idle minutes; a failed image reloads
  // the offer once rather than looping if the bucket keeps refusing.
  const qrRefetches = useRef(0);
  const handleQrExpired = useCallback(() => {
    if (qrRefetches.current >= 1) return;
    qrRefetches.current += 1;
    void refetch();
  }, [refetch]);

  return (
    <Box sx={{ p: { xs: 2, sm: 3 } }}>
      <NoIndexMeta />
      <PublicOrderBody
        complete={Boolean(profileId && token)}
        loading={loading}
        offer={offer}
        profileId={profileId}
        token={token}
        onQrExpired={handleQrExpired}
      />
      <OfferRefreshWarning hasError={Boolean(error)} hasOffer={Boolean(offer)} />
    </Box>
  );
};

export default PublicOrderPage;
