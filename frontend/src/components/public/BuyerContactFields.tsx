/**
 * Buyer identity fields for the public order page.
 *
 * The US-only contact rules are stated inline rather than left to a server
 * error: a ten-digit US phone number, or an address with all four fields and a
 * US ZIP. Phone OR address is required; email is optional and its absence is
 * called out separately by the submit flow.
 */

import { Grid, TextField } from '@mui/material';
import type { PublicOrderAddressForm, PublicOrderFieldErrors } from '../../lib/publicOrderValidation';

interface BuyerContactFieldsProps {
  firstName: string;
  lastName: string;
  phone: string;
  email: string;
  address: PublicOrderAddressForm;
  errors: PublicOrderFieldErrors;
  onFieldChange: (field: 'firstName' | 'lastName' | 'phone' | 'email', value: string) => void;
  onAddressChange: (field: keyof PublicOrderAddressForm, value: string) => void;
}

export const BuyerContactFields: React.FC<BuyerContactFieldsProps> = ({
  firstName,
  lastName,
  phone,
  email,
  address,
  errors,
  onFieldChange,
  onAddressChange,
}) => (
  <Grid container spacing={2}>
    <Grid size={{ xs: 12, sm: 6 }}>
      <TextField
        required
        fullWidth
        label="First name"
        value={firstName}
        onChange={(event) => onFieldChange('firstName', event.target.value)}
        error={Boolean(errors.firstName)}
        helperText={errors.firstName || 'As it should appear on the order.'}
        inputProps={{ maxLength: 100 }}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <TextField
        required
        fullWidth
        label="Last name"
        value={lastName}
        onChange={(event) => onFieldChange('lastName', event.target.value)}
        error={Boolean(errors.lastName)}
        helperText={errors.lastName || 'As it should appear on the order.'}
        inputProps={{ maxLength: 100 }}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <TextField
        fullWidth
        label="Phone"
        value={phone}
        onChange={(event) => onFieldChange('phone', event.target.value)}
        error={Boolean(errors.contact)}
        helperText={errors.contact || 'A 10-digit US phone number. Phone or a complete address is required.'}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <TextField
        fullWidth
        type="email"
        label="Email (optional)"
        value={email}
        onChange={(event) => onFieldChange('email', event.target.value)}
        error={Boolean(errors.email)}
        helperText={errors.email || 'Optional. Without it you will not receive a confirmation email.'}
      />
    </Grid>
    <Grid size={{ xs: 12 }}>
      <TextField
        fullWidth
        label="Street address"
        value={address.street}
        onChange={(event) => onAddressChange('street', event.target.value)}
        helperText="Or fill in a full US address instead of a phone number: street, city, state and ZIP."
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 5 }}>
      <TextField
        fullWidth
        label="City"
        value={address.city}
        onChange={(event) => onAddressChange('city', event.target.value)}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 3 }}>
      <TextField
        fullWidth
        label="State"
        value={address.state}
        onChange={(event) => onAddressChange('state', event.target.value)}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 4 }}>
      <TextField
        fullWidth
        label="ZIP code"
        value={address.zipCode}
        onChange={(event) => onAddressChange('zipCode', event.target.value)}
        helperText="5 or 9 digits."
      />
    </Grid>
  </Grid>
);

export default BuyerContactFields;
