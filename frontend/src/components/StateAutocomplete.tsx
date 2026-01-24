/**
 * StateAutocomplete - Reusable autocomplete component for US state selection
 * Provides type-ahead functionality with all 50 US states plus DC
 */

import React from 'react';
import { Autocomplete, TextField } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { US_STATES } from '../constants/campaign';

interface StateAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  label?: string;
  fullWidth?: boolean;
  required?: boolean;
  sx?: SxProps<Theme>;
}

export const StateAutocomplete: React.FC<StateAutocompleteProps> = ({
  value,
  onChange,
  disabled = false,
  label = 'State',
  fullWidth = false,
  required = false,
  sx,
}) => (
  <Autocomplete
    value={value}
    onChange={(_, newValue) => onChange(newValue || '')}
    inputValue={value}
    onInputChange={(_, newInputValue) => onChange(newInputValue)}
    options={US_STATES}
    disabled={disabled}
    fullWidth={fullWidth}
    sx={sx}
    renderInput={(params) => <TextField {...params} label={label} required={required} />}
    noOptionsText="No states found"
    clearOnBlur={false}
    freeSolo
  />
);
