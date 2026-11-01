/**
 * Acknowledgement checkboxes for public order settings.
 *
 * Both texts are mandated by the public-orders spec (decisions D4 and D5) and
 * are persisted server-side (`acknowledgedAt`, `ackVersion`) as evidence of
 * the liability warning. The settings mutation requires both to be accepted
 * (`acknowledgementsAccepted: true`) whenever public orders are enabled.
 */
import { Box, Checkbox, FormControlLabel, FormGroup, Typography } from '@mui/material';

/** D4 — payment responsibility. */
export const PAYMENT_ACK_TEXT =
  'KernelWorx does not collect payment. You are responsible for verifying that the buyer has actually paid before fulfilling the order.';

/** D5 — QR and buyer-PII disclosure. */
export const DISCLOSURE_ACK_TEXT =
  "Buyers will see the QR image you uploaded for any enabled payment method. Public buyers' name, contact details, and email become visible to people you share this profile with and appear in unit reports/exports.";

interface PublicSettingsAckCheckboxesProps {
  paymentAckAccepted: boolean;
  disclosureAckAccepted: boolean;
  onPaymentAckChange: (value: boolean) => void;
  onDisclosureAckChange: (value: boolean) => void;
  disabled?: boolean;
}

export const PublicSettingsAckCheckboxes: React.FC<PublicSettingsAckCheckboxesProps> = ({
  paymentAckAccepted,
  disclosureAckAccepted,
  onPaymentAckChange,
  onDisclosureAckChange,
  disabled = false,
}) => {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Acknowledgements
      </Typography>
      <FormGroup>
        <FormControlLabel
          control={
            <Checkbox
              checked={paymentAckAccepted}
              onChange={(e) => onPaymentAckChange(e.target.checked)}
              disabled={disabled}
            />
          }
          label={PAYMENT_ACK_TEXT}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={disclosureAckAccepted}
              onChange={(e) => onDisclosureAckChange(e.target.checked)}
              disabled={disabled}
            />
          }
          label={DISCLOSURE_ACK_TEXT}
        />
      </FormGroup>
    </Box>
  );
};
