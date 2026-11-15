/**
 * The Unit form fields, shared by create and edit (Show & Sell §1.6.1).
 *
 * One component for both screens because the field set is the same and the rules
 * must not drift between them: geography (type, number, city, state) is what makes
 * a Unit addressable and is required; the display name is optional and previews the
 * name the server would generate; timezone plus the split and needs-report defaults
 * are the Unit's settings.
 *
 * The validation itself is not here — `lib/unitForm` owns it, so the create dialog
 * and the settings screen cannot end up accepting different input.
 */

import React from 'react';
import { Box, MenuItem, TextField } from '@mui/material';
import { StateAutocomplete } from './StateAutocomplete';
import { UNIT_TIMEZONES } from '../lib/units';
import { previewUnitDisplayName, type UnitFormValues } from '../lib/unitForm';
import type { GqlCouncilNeedBasis, GqlSplitMethod } from '../types/graphql-generated';

interface UnitFormFieldsProps {
  values: UnitFormValues;
  onChange: (values: UnitFormValues) => void;
  errors?: Partial<Record<keyof UnitFormValues, string>>;
  disabled?: boolean;
  /** The create screen explains the generated name; the edit screen does not need to. */
  isCreate?: boolean;
}

type FieldSetter = <K extends keyof UnitFormValues>(field: K, value: UnitFormValues[K]) => void;

export const UnitFormFields: React.FC<UnitFormFieldsProps> = ({ values, onChange, errors = {}, disabled, isCreate }) => {
  const set: FieldSetter = (field, value) => onChange({ ...values, [field]: value });

  return (
    <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      <TextField
        select
        label="Unit type"
        value={values.unitType}
        onChange={(event) => set('unitType', event.target.value)}
        error={Boolean(errors.unitType)}
        helperText={errors.unitType}
        disabled={disabled}
        required
        data-testid="unit-type"
      >
        {['Pack', 'Troop', 'Crew', 'Ships', 'District', 'Other'].map((type) => (
          <MenuItem key={type} value={type}>
            {type}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Unit number"
        value={values.unitNumber}
        onChange={(event) => set('unitNumber', event.target.value)}
        error={Boolean(errors.unitNumber)}
        helperText={errors.unitNumber}
        disabled={disabled}
        inputMode="numeric"
        required
        data-testid="unit-number"
      />
      <TextField
        label="City"
        value={values.city}
        onChange={(event) => set('city', event.target.value)}
        error={Boolean(errors.city)}
        helperText={errors.city}
        disabled={disabled}
        required
        data-testid="unit-city"
      />
      <Box data-testid="unit-state">
        <StateAutocomplete value={values.state} onChange={(state) => set('state', state)} disabled={disabled} required />
      </Box>
      <TextField
        select
        label="Timezone"
        value={values.timezone}
        onChange={(event) => set('timezone', event.target.value)}
        error={Boolean(errors.timezone)}
        helperText={errors.timezone}
        disabled={disabled}
        data-testid="unit-timezone"
      >
        {UNIT_TIMEZONES.map((zone) => (
          <MenuItem key={zone} value={zone}>
            {zone}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Display name (optional)"
        value={values.displayName}
        onChange={(event) => set('displayName', event.target.value)}
        disabled={disabled}
        helperText={displayNameHint(values, isCreate)}
        data-testid="unit-display-name"
      />
      <TextField
        select
        label="Default split"
        value={values.splitDefault}
        onChange={(event) => set('splitDefault', event.target.value as GqlSplitMethod)}
        disabled={disabled}
        helperText="Default for new events"
        data-testid="unit-split-default"
      >
        <MenuItem value="EQUAL">Split equally</MenuItem>
        <MenuItem value="TIME_WORKED">Split by work time</MenuItem>
      </TextField>
      <TextField
        select
        label="Council needs report basis"
        value={values.councilNeedBasis}
        onChange={(event) => set('councilNeedBasis', event.target.value as GqlCouncilNeedBasis)}
        disabled={disabled}
        helperText="How the needs report is presented"
        data-testid="unit-council-basis"
      >
        <MenuItem value="PHYSICAL_STOCK">On physical stock</MenuItem>
        <MenuItem value="AFTER_ASSIGNMENTS">After assignments</MenuItem>
      </TextField>
    </Box>
  );
};

/** The create screen shows the generated name before it is committed to. */
function displayNameHint(values: UnitFormValues, isCreate: boolean | undefined): string {
  if (!isCreate) return 'Shown to Scouts joining this Unit';
  return `Leave empty to use "${previewUnitDisplayName(values)}"`;
}
