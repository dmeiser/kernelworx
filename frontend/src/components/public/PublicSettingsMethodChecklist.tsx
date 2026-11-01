/**
 * Payment method checklist for public order settings.
 *
 * The checklist lists the owner account's real payment methods (plus the
 * always-available Cash and Check), not a hardcoded brand list — custom
 * methods like Venmo must be allowlistable. Matching against the stored
 * allowlist is case-insensitive (pinned server-side); toggling preserves the
 * method's canonical name as shown here.
 */
import { Box, Checkbox, FormControlLabel, FormGroup, Typography } from '@mui/material';

interface PublicSettingsMethodChecklistProps {
  /** The seller's available payment methods (account methods + Cash + Check). */
  availablePaymentMethods: string[];
  /** The currently allowed methods (stored or draft). */
  allowedPaymentMethods: string[];
  onChange: (methods: string[]) => void;
  disabled?: boolean;
}

const sameMethod = (a: string, b: string): boolean => a.toLowerCase() === b.toLowerCase();

export const PublicSettingsMethodChecklist: React.FC<PublicSettingsMethodChecklistProps> = ({
  availablePaymentMethods,
  allowedPaymentMethods,
  onChange,
  disabled = false,
}) => {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Allowed Payment Methods
      </Typography>
      <FormGroup>
        {availablePaymentMethods.map((method) => (
          <FormControlLabel
            key={method}
            control={
              <Checkbox
                checked={allowedPaymentMethods.some((allowed) => sameMethod(allowed, method))}
                onChange={() => {
                  const isAllowed = allowedPaymentMethods.some((allowed) => sameMethod(allowed, method));
                  const updated = isAllowed
                    ? allowedPaymentMethods.filter((allowed) => !sameMethod(allowed, method))
                    : [...allowedPaymentMethods, method];
                  onChange(updated);
                }}
                disabled={disabled}
              />
            }
            label={method}
          />
        ))}
      </FormGroup>
    </Box>
  );
};
