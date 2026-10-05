/**
 * Allowed-method checklist for the public order settings.
 *
 * Payment methods live at ACCOUNT level (`preferences.paymentMethods`), so every
 * profile of one account offers the same list while this toggle governs one
 * profile. `Cash` and `Check` are always offered as choices; the offer filters
 * staleness later, so a method the seller deletes simply drops out of the buyer
 * page rather than breaking the settings blob.
 */

import { Alert, Box, Checkbox, FormControlLabel, Typography } from '@mui/material';
import { methodIsAllowed } from '../../lib/publicOrderSettings';

interface PublicSettingsMethodChecklistProps {
  options: string[];
  selected: string[];
  onToggle: (name: string, checked: boolean) => void;
}

export const PublicSettingsMethodChecklist: React.FC<PublicSettingsMethodChecklistProps> = ({
  options,
  selected,
  onToggle,
}) => (
  <Box data-testid="method-checklist">
    <Typography variant="subtitle1" fontWeight="medium" gutterBottom>
      Methods buyers may choose
    </Typography>
    {options.length === 0 ? (
      <Alert severity="info" sx={{ mb: 1 }}>
        Add a payment method under Payment Methods first, or enable Cash or Check.
      </Alert>
    ) : null}
    {options.map((name) => (
      <FormControlLabel
        key={name}
        control={
          <Checkbox
            checked={methodIsAllowed(selected, name)}
            onChange={(event) => onToggle(name, event.target.checked)}
          />
        }
        label={name}
      />
    ))}
  </Box>
);

export default PublicSettingsMethodChecklist;
