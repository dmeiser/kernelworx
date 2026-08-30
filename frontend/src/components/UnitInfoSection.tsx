/**
 * UnitInfoSection - Reusable unit information form section
 *
 * Used in campaign creation and campaign settings for optional scout unit info.
 */

import React from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { ExpandMore as ExpandMoreIcon } from '@mui/icons-material';
import { StateAutocomplete } from './StateAutocomplete';
import { UNIT_TYPES } from '../constants/unitTypes';

interface UnitInfoSectionProps {
  unitType: string;
  onUnitTypeChange: (value: string) => void;
  unitNumber: string;
  onUnitNumberChange: (value: string) => void;
  city: string;
  onCityChange: (value: string) => void;
  state: string;
  onStateChange: (value: string) => void;
  submitting: boolean;
  expanded: boolean;
  onExpandChange: (expanded: boolean) => void;
  readOnly?: boolean;
}

const UnitInfoAlert: React.FC<{ readOnly: boolean }> = ({ readOnly }) =>
  readOnly ? (
    <Alert severity="info">Unit information cannot be changed for campaigns created from a shared campaign link.</Alert>
  ) : (
    <Alert severity="info">
      Adding unit information enables participation in unit reports and allows coordination with other unit members.
    </Alert>
  );

const UnitInfoHeader: React.FC<{ unitType: string; unitNumber: string }> = ({ unitType, unitNumber }) => (
  <Typography>
    Unit Information (Optional)
    {unitType && (
      <span>
        {' '}
        - {unitType} {unitNumber}
      </span>
    )}
  </Typography>
);

const getUnitNumberHelper = (unitType: string): string => (unitType ? 'Required' : 'Select unit type first');

const getCityHelper = (unitType: string): string => (unitType ? 'Required for unit identification' : '');

const UnitInfoFields: React.FC<
  Pick<
    UnitInfoSectionProps,
    | 'unitType'
    | 'onUnitTypeChange'
    | 'unitNumber'
    | 'onUnitNumberChange'
    | 'city'
    | 'onCityChange'
    | 'state'
    | 'onStateChange'
    | 'submitting'
    | 'readOnly'
  >
> = ({
  unitType,
  onUnitTypeChange,
  unitNumber,
  onUnitNumberChange,
  city,
  onCityChange,
  state,
  onStateChange,
  submitting,
  readOnly,
}) => {
  const fieldDisabled = submitting || readOnly || !unitType;

  return (
    <>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <FormControl fullWidth disabled={submitting || readOnly}>
          <InputLabel>Unit Type</InputLabel>
          <Select value={unitType} onChange={(e) => onUnitTypeChange(e.target.value)} label="Unit Type">
            {UNIT_TYPES.map((option) => (
              <MenuItem key={`unit-${option.value}`} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          fullWidth
          label="Unit Number"
          type="number"
          value={unitNumber}
          onChange={(e) => onUnitNumberChange(e.target.value)}
          disabled={fieldDisabled}
          inputProps={{ min: 1, step: 1 }}
          helperText={getUnitNumberHelper(unitType)}
        />
      </Stack>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField
          fullWidth
          label="City"
          value={city}
          onChange={(e) => onCityChange(e.target.value)}
          disabled={fieldDisabled}
          helperText={getCityHelper(unitType)}
        />
        <StateAutocomplete value={state} onChange={onStateChange} disabled={fieldDisabled} fullWidth />
      </Stack>
    </>
  );
};

export const UnitInfoSection: React.FC<UnitInfoSectionProps> = ({
  unitType,
  onUnitTypeChange,
  unitNumber,
  onUnitNumberChange,
  city,
  onCityChange,
  state,
  onStateChange,
  submitting,
  expanded,
  onExpandChange,
  readOnly = false,
}) => (
  <Accordion expanded={expanded} onChange={(_, isExpanded) => onExpandChange(isExpanded)}>
    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
      <UnitInfoHeader unitType={unitType} unitNumber={unitNumber} />
    </AccordionSummary>
    <AccordionDetails>
      <Stack spacing={2} sx={{ width: '100%' }}>
        <UnitInfoAlert readOnly={readOnly} />
        <UnitInfoFields
          unitType={unitType}
          onUnitTypeChange={onUnitTypeChange}
          unitNumber={unitNumber}
          onUnitNumberChange={onUnitNumberChange}
          city={city}
          onCityChange={onCityChange}
          state={state}
          onStateChange={onStateChange}
          submitting={submitting}
          readOnly={readOnly}
        />
      </Stack>
    </AccordionDetails>
  </Accordion>
);
