/**
 * Unit settings editing (Show & Sell §1.6.1).
 *
 * Every save carries the `version` this screen read plus an idempotency key that a
 * retry of the same edit reuses. A `CONFLICT` means another admin wrote in between:
 * the answer is to re-read and decide again, never to resend blind, because a blind
 * resend would overwrite whatever they changed.
 *
 * Geography is editable here, which is why the server re-runs its duplicate check
 * on a geography change; the confirmation dialog is the same one the create screen
 * uses, so a duplicate is always a choice and never a surprise.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import { ConfirmDialog } from './ConfirmDialog';
import { ErrorNote } from './ErrorAlert';
import { UPDATE_UNIT } from '../lib/graphql';
import { UnitFormFields } from './UnitFormFields';
import { changedUnitFields, unitFormErrors, unitFormFromUnit, type UnitFormValues } from '../lib/unitForm';
import { isDuplicateUnitError, isStaleVersionError, newIdempotencyKey } from '../lib/units';
import type { GqlUnit } from '../types/graphql-generated';

interface UnitSettingsPanelProps {
  unit: GqlUnit;
  onSaved: () => Promise<unknown> | void;
}

interface SaveIntent {
  idempotencyKey: string;
  duplicateConfirmed: boolean;
}

export const UnitSettingsPanel: React.FC<UnitSettingsPanelProps> = ({ unit, onSaved }) => {
  const [values, setValues] = useState<UnitFormValues>(() => unitFormFromUnit(unit));
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof UnitFormValues, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [pendingSave, setPendingSave] = useState<SaveIntent | null>(null);
  // One key per edit intent: a retry of the same body replays the original write,
  // and a saved edit's key is retired so the next edit is genuinely a new intent.
  const [intentKey, setIntentKey] = useState(newIdempotencyKey);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  // Another admin's save (or a reload) replaces `unit`, and the form follows it
  // rather than keeping an edit whose version no longer exists.
  useEffect(() => {
    setValues(unitFormFromUnit(unit));
    setStale(false);
  }, [unit]);

  const [updateUnit, { loading }] = useMutation(UPDATE_UNIT);
  const changes = useMemo(() => changedUnitFields(values, unit), [values, unit]);

  const submit = async (intent: SaveIntent) => {
    setError(null);
    setSavedMessage(null);
    try {
      await updateUnit({
        variables: {
          input: {
            unitId: unit.unitId,
            ...changes,
            duplicateConfirmed: intent.duplicateConfirmed,
            version: { expectedVersion: unit.version },
            idempotency: { idempotencyKey: intent.idempotencyKey },
          },
        },
      });
      setPendingSave(null);
      setSavedMessage('Settings saved.');
      setIntentKey(newIdempotencyKey());
      await onSaved();
    } catch (mutationError) {
      const failure = classifySaveFailure(mutationError);
      if (failure.kind === 'duplicate') setPendingSave({ idempotencyKey: newIdempotencyKey(), duplicateConfirmed: true });
      if (failure.kind === 'stale') {
        setStale(true);
        await onSaved();
      }
      if (failure.message) setError(failure.message);
    }
  };

  const handleSave = async () => {
    const errors = unitFormErrors(values);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;
    if (Object.keys(changes).length === 0) {
      setError('Nothing to save — no field has changed.');
      return;
    }
    await submit({ idempotencyKey: intentKey, duplicateConfirmed: false });
  };

  return (
    <Box sx={{ pt: 2 }}>
      <UnitFormFields values={values} onChange={setValues} errors={formErrors} disabled={loading} />

      <StaleUnitNotice onReload={() => void onSaved()} disabled={loading} visible={stale} />
      <ErrorNote message={error} sx={{ mt: 2 }} />
      <SuccessNote message={savedMessage} />

      <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 3 }}>
        <Button variant="contained" onClick={() => void handleSave()} disabled={loading} data-testid="save-unit">
          {loading ? 'Saving…' : 'Save settings'}
        </Button>
        <VersionNote version={unit.version} adminCount={unit.adminCount} />
      </Stack>

      <ConfirmDialog
        open={pendingSave !== null}
        title="A Unit with these details already exists"
        confirmLabel="Save it as a separate Unit"
        confirmColor="warning"
        isLoading={loading}
        onClose={() => setPendingSave(null)}
        onConfirm={async () => {
          if (pendingSave) await submit(pendingSave);
        }}
      >
        <Typography>
          Another Unit already uses exactly this type, number, city, and state. Saving keeps them separate — no shared
          admins and no merged history.
        </Typography>
      </ConfirmDialog>
    </Box>
  );
};

/**
 * Which next step a failed save implies.
 *
 * A duplicate is a question the admin can answer; a stale version is a re-read;
 * anything else is the server's own reason. Collapsing the three into one red box
 * loses the difference between "decide again" and "you are looking at old data".
 */
type SaveFailure = { kind: 'duplicate' | 'stale' | 'error'; message?: string };

function classifySaveFailure(mutationError: unknown): SaveFailure {
  if (isDuplicateUnitError(mutationError)) return { kind: 'duplicate' };
  if (isStaleVersionError(mutationError)) {
    return { kind: 'stale', message: 'This Unit changed while you were editing. Reload it and apply your change again.' };
  }
  return { kind: 'error', message: (mutationError as Error).message || 'Could not save the Unit settings.' };
}

const StaleUnitNotice: React.FC<{ visible: boolean; onReload: () => void; disabled: boolean }> = ({
  visible,
  onReload,
  disabled,
}) => {
  if (!visible) return null;
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
      <Alert severity="warning" sx={{ flexGrow: 1 }}>
        Another admin changed this Unit.
      </Alert>
      <Button variant="outlined" onClick={onReload} disabled={disabled} data-testid="reload-unit">
        Reload this Unit
      </Button>
    </Stack>
  );
};

const SuccessNote: React.FC<{ message: string | null }> = ({ message }) => {
  if (!message) return null;
  return (
    <Typography color="success.main" sx={{ mt: 2 }} data-testid="save-confirmation">
      {message}
    </Typography>
  );
};

const VersionNote: React.FC<{ version: number; adminCount: number }> = ({ version, adminCount }) => (
  <Typography variant="body2" color="text.secondary" data-testid="unit-version">
    Version {version} · {adminCount} admin{adminCount === 1 ? '' : 's'}
  </Typography>
);
