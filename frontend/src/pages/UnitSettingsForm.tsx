/**
 * UnitSettingsForm - edit a Unit's display metadata and settings.
 *
 * Part of the Show & Sell Unit surface (batch C, leaf 1.6.1). Wires `unit` and
 * `updateUnit`. The unit type and number (the identity fingerprint) are not
 * editable here — only display name, city, state, timezone, the default split,
 * and the Council-need basis are. Each save carries the version the form last
 * read, so a concurrent edit surfaces a CONFLICT instead of silently overwriting.
 */

import React, { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { Alert, Box, Button, Divider, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { GET_UNIT, UPDATE_UNIT } from '../lib/graphql';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { StateAutocomplete } from '../components/StateAutocomplete';
import { LoadingState } from '../components/LoadingState';
import { generatedUnitDisplayName, newUnitIdempotencyKey } from '../lib/unitForm';
import { COUNCIL_BASIS, SPLIT_DEFAULTS } from '../constants/unitTypes';
import type { GqlCouncilNeedBasis, GqlSplitMethod, GqlUnit } from '../types';

interface EditableSettings {
  displayName: string;
  city: string;
  state: string;
  timezone: string;
  splitDefault: GqlSplitMethod;
  councilNeedBasis: GqlCouncilNeedBasis;
}

const settingsFromUnit = (unit: GqlUnit): EditableSettings => ({
  displayName: unit.displayName ?? '',
  city: unit.city,
  state: unit.state,
  timezone: unit.timezone,
  splitDefault: unit.splitDefault,
  councilNeedBasis: unit.councilNeedBasis,
});

const previewDisplayName = (unit: GqlUnit, settings: EditableSettings): string =>
  settings.displayName.trim() || generatedUnitDisplayName(unit.unitType, unit.unitNumber, settings.city.trim(), settings.state.trim());

const SettingsLoadError: React.FC<{ error: Error }> = ({ error }) => (
  <Alert severity="error" sx={{ my: 2 }}>
    {error.message || 'Unable to load this unit.'}
  </Alert>
);

const freshestUnit = (savedUnit: GqlUnit | null, unit: GqlUnit): GqlUnit => savedUnit ?? unit;

const UnitSettingsFields: React.FC<{ unit: GqlUnit; onSaved?: (unit: GqlUnit) => void }> = ({ unit, onSaved }) => {
  const [settings, setSettings] = useState<EditableSettings>(() => settingsFromUnit(unit));
  const [savedUnit, setSavedUnit] = useState<GqlUnit | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [updateUnit, { loading: saving }] = useMutation<{ updateUnit: GqlUnit }>(UPDATE_UNIT, {
    refetchQueries: [{ query: GET_UNIT, variables: { unitId: unit.unitId } }],
    onCompleted: (result) => {
      setSavedUnit(result.updateUnit);
      onSaved?.(result.updateUnit);
    },
    onError: (e) => setSaveError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e))),
  });

  const setField = <K extends keyof EditableSettings>(key: K, value: EditableSettings[K]) =>
    setSettings((prev) => ({ ...prev, [key]: value }));

  const viewUnit = freshestUnit(savedUnit, unit);
  const previewName = previewDisplayName(viewUnit, settings);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    try {
      await updateUnit({
        variables: {
          input: {
            unitId: unit.unitId,
            version: { expectedVersion: viewUnit.version },
            displayName:
              settings.displayName.trim() ||
              generatedUnitDisplayName(unit.unitType, unit.unitNumber, settings.city.trim(), settings.state.trim()),
            city: settings.city.trim(),
            state: settings.state.trim(),
            timezone: settings.timezone,
            splitDefault: settings.splitDefault,
            councilNeedBasis: settings.councilNeedBasis,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are surfaced by the onError callback; swallow to avoid an unhandled rejection.
    }
  };

  return (
    <Box component="form" noValidate onSubmit={(e) => void handleSave(e)}>
      <Typography variant="h6" gutterBottom>
        {viewUnit.displayName || previewName}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {viewUnit.unitType} {viewUnit.unitNumber} · {viewUnit.city}, {viewUnit.state} · {viewUnit.adminCount} admin
        {viewUnit.adminCount === 1 ? '' : 's'}
      </Typography>
      <Stack spacing={2}>
        {saveError && <Alert severity="error">{saveError}</Alert>}
        <TextField
          fullWidth
          label="Display name (optional)"
          value={settings.displayName}
          onChange={(e) => setField('displayName', e.target.value)}
          placeholder={previewName}
          helperText={`Shown as "${previewName}" when left blank`}
        />
        <TextField
          fullWidth
          label="City"
          value={settings.city}
          onChange={(e) => setField('city', e.target.value)}
        />
        <StateAutocomplete
          fullWidth
          label="State"
          value={settings.state}
          onChange={(v) => setField('state', v)}
        />
        <TextField
          fullWidth
          label="Timezone (IANA)"
          value={settings.timezone}
          onChange={(e) => setField('timezone', e.target.value)}
          helperText="Used for display and calendar generation"
        />
        <TextField
          select
          fullWidth
          label="Default split"
          value={settings.splitDefault}
          onChange={(e) => setField('splitDefault', e.target.value as GqlSplitMethod)}
        >
          {SPLIT_DEFAULTS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          fullWidth
          label="Council-need basis"
          value={settings.councilNeedBasis}
          onChange={(e) => setField('councilNeedBasis', e.target.value as GqlCouncilNeedBasis)}
        >
          {COUNCIL_BASIS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <Divider />
        <Button type="submit" variant="contained" disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </Button>
      </Stack>
    </Box>
  );
};

export const UnitSettingsForm: React.FC<{
  unitId: string;
  /** Called after a successful save with the updated Unit. */
  onSave?: (unit: GqlUnit) => void;
}> = ({ unitId, onSave }) => {
  const { data, loading, error } = useQuery<{ unit: GqlUnit }>(GET_UNIT, { variables: { unitId } });

  if (loading) return <LoadingState minHeight="200px" />;
  if (error) return <SettingsLoadError error={error} />;
  const unit = data ? data.unit : null;
  if (!unit) return null;

  return <UnitSettingsFields key={unit.version} unit={unit} onSaved={onSave} />;
};

export default UnitSettingsForm;
