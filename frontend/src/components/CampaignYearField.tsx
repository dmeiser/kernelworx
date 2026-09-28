/**
 * CampaignYearField - canonical campaign-year number input.
 *
 * Single source of truth for the campaign-year bound (2020..currentYear + 5),
 * shared by the Create Campaign and Create Shared Campaign forms (issue #539),
 * which previously diverged (`max: currentYear + 5` vs a hard-coded `max: 2100`).
 * Callers keep their own label, width, disabled state, and onChange parsing
 * semantics; the component hands each change back as the raw `parseInt` result
 * so a caller can still coerce empty input to 0.
 */

import React from 'react';
import { TextField } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { CAMPAIGN_YEAR_MIN, getCampaignYearMax } from '../constants/campaign';

interface CampaignYearFieldProps {
  label: string;
  value: number;
  /** Receives the raw `parseInt(value, 10)` of the input (NaN when cleared). */
  onChange: (value: number) => void;
  disabled?: boolean;
  sx?: SxProps<Theme>;
}

export const CampaignYearField: React.FC<CampaignYearFieldProps> = ({
  label,
  value,
  onChange,
  disabled = false,
  sx,
}) => (
  <TextField
    label={label}
    type="number"
    value={value}
    onChange={(e) => onChange(parseInt(e.target.value, 10))}
    required
    disabled={disabled}
    sx={sx}
    inputProps={{
      min: CAMPAIGN_YEAR_MIN,
      max: getCampaignYearMax(),
      step: 1,
    }}
  />
);
