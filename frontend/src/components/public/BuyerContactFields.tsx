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

interface ContactFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** The error for this exact box. */
  error?: string;
  /** An error covering the block this box belongs to, shown when the box itself is clean. */
  groupError?: string;
  /** The neutral hint shown when nothing is wrong. */
  hint?: string;
  required?: boolean;
  type?: string;
  maxLength?: number;
}

/**
 * One buyer contact input with its error resolution.
 *
 * The precedence — this box's own error, then the block's, then the neutral
 * hint — is the whole point of the public contact form, so it lives in one
 * place rather than in eight `||` chains that can drift apart. Only the box's
 * own error marks it invalid: a block error is shown as text under the first
 * box of the block, but a box the server would accept is not flagged as wrong.
 */
const ContactField: React.FC<ContactFieldProps> = ({
  label,
  value,
  onChange,
  error,
  groupError,
  hint,
  required,
  type,
  maxLength,
}) => (
  <TextField
    required={required}
    fullWidth
    type={type}
    label={label}
    value={value}
    onChange={(event) => onChange(event.target.value)}
    error={Boolean(error)}
    helperText={error ?? groupError ?? hint}
    inputProps={{ maxLength }}
  />
);

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
      <ContactField
        required
        label="First name"
        value={firstName}
        onChange={(value) => onFieldChange('firstName', value)}
        error={errors.firstName}
        hint="As it should appear on the order."
        maxLength={100}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <ContactField
        required
        label="Last name"
        value={lastName}
        onChange={(value) => onFieldChange('lastName', value)}
        error={errors.lastName}
        hint="As it should appear on the order."
        maxLength={100}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <ContactField
        label="Phone"
        value={phone}
        onChange={(value) => onFieldChange('phone', value)}
        error={errors.phone}
        hint="A 10-digit US phone number. Phone or a complete address is required."
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 6 }}>
      <ContactField
        label="Email (optional)"
        type="email"
        value={email}
        onChange={(value) => onFieldChange('email', value)}
        error={errors.email}
        hint="Optional. Without it you will not receive a confirmation email."
      />
    </Grid>
    <Grid size={{ xs: 12 }}>
      <ContactField
        label="Street address"
        value={address.street}
        onChange={(value) => onAddressChange('street', value)}
        error={errors.addressFields?.street}
        groupError={errors.address}
        hint="Or fill in a full US address instead of a phone number: street, city, state and ZIP."
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 5 }}>
      <ContactField
        label="City"
        value={address.city}
        onChange={(value) => onAddressChange('city', value)}
        error={errors.addressFields?.city}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 3 }}>
      <ContactField
        label="State"
        value={address.state}
        onChange={(value) => onAddressChange('state', value)}
        error={errors.addressFields?.state}
      />
    </Grid>
    <Grid size={{ xs: 12, sm: 4 }}>
      <ContactField
        label="ZIP code"
        value={address.zipCode}
        onChange={(value) => onAddressChange('zipCode', value)}
        error={errors.addressFields?.zipCode}
        hint="5 or 9 digits."
      />
    </Grid>
  </Grid>
);

export default BuyerContactFields;
