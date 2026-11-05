/**
 * UnitsPage - the Show & Sell "Show" landing surface (leaf 1.6.1).
 *
 * Lists the account's units (`myUnits`), offers unit creation (`createUnit`),
 * and the open-to-any-account invite redemption entry point (`redeemUnitInvite`).
 * Unit detail (settings, access, campaigns) lives at `/units/:unitId`.
 */

import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { CREATE_UNIT, MY_UNITS } from '../lib/graphql';
import { EmptyState } from '../components/EmptyState';
import { ErrorAlert } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { StateAutocomplete } from '../components/StateAutocomplete';
import { UNIT_TYPES_WITHOUT_NONE, SPLIT_DEFAULTS, COUNCIL_BASIS } from '../constants/unitTypes';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { generatedUnitDisplayName, newUnitIdempotencyKey } from '../lib/unitForm';
import RedeemUnitInviteCard from './RedeemUnitInviteCard';
import type {
  GqlCouncilNeedBasis,
  GqlSplitMethod,
  GqlUnit,
} from '../types';

const FormError: React.FC<{ text: string | null }> = ({ text }) =>
  text ? (
    <Typography color="error" sx={{ mb: 2 }} role="alert">
      {text}
    </Typography>
  ) : null;

interface CreateUnitFormState {
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  displayName: string;
  timezone: string;
  splitDefault: GqlSplitMethod;
  councilNeedBasis: GqlCouncilNeedBasis;
}

const EMPTY_FORM: CreateUnitFormState = {
  unitType: '',
  unitNumber: '',
  city: '',
  state: '',
  displayName: '',
  timezone: 'America/Denver',
  splitDefault: 'EQUAL',
  councilNeedBasis: 'PHYSICAL_STOCK',
};

const FIELD_VALIDATORS: Array<{ message: string; empty: (form: CreateUnitFormState) => boolean }> = [
  { message: 'Choose the unit type.', empty: (form) => !form.unitType },
  { message: 'Enter the unit number.', empty: (form) => !form.unitNumber.trim() },
  { message: 'Enter the city.', empty: (form) => !form.city.trim() },
  { message: 'Enter the state.', empty: (form) => !form.state.trim() },
  { message: 'Enter the timezone.', empty: (form) => !form.timezone.trim() },
];

const validateUnitForm = (form: CreateUnitFormState): string | null => {
  const missing = FIELD_VALIDATORS.find((entry) => entry.empty(form));
  return missing ? missing.message : null;
};

const getCreateUnitPreviewName = (form: CreateUnitFormState): string => {
  const explicit = form.displayName.trim();
  if (explicit) return explicit;
  return generatedUnitDisplayName(form.unitType, Number(form.unitNumber), form.city, form.state);
};

const unitDisplayName = (unit: GqlUnit): string =>
  unit.displayName || generatedUnitDisplayName(unit.unitType, unit.unitNumber, unit.city, unit.state);

const selectMyUnits = (data: { myUnits: { items: GqlUnit[] } } | undefined): GqlUnit[] =>
  data ? data.myUnits.items : [];

interface CreateUnitDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (unitId: string) => void;
}

export const CreateUnitDialog: React.FC<CreateUnitDialogProps> = ({ open, onClose, onCreated }) => {
  const [form, setForm] = useState<CreateUnitFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingInput, setPendingInput] = useState<Record<string, unknown> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const createOutcome = useRef<{ code?: string; unitId?: string; error?: string }>({});
  const [createUnit] = useMutation<{ createUnit: { unit?: { unitId: string } } }>(CREATE_UNIT, {
    refetchQueries: [{ query: MY_UNITS }],
    onCompleted: (data) => {
      createOutcome.current = { unitId: data.createUnit?.unit?.unitId };
    },
    onError: (e) => {
      const code = getErrorCode(e);
      createOutcome.current = { code, error: mapErrorCodeToMessage(code, getErrorMessage(e)) };
    },
  });

  const setField = <K extends keyof CreateUnitFormState>(key: K, value: CreateUnitFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const previewName = getCreateUnitPreviewName(form);

  const buildInput = (duplicateConfirmed: boolean, idempotencyKey: string) => ({
    unitType: form.unitType,
    unitNumber: Number(form.unitNumber),
    city: form.city.trim(),
    state: form.state.trim(),
    displayName: form.displayName.trim() || null,
    timezone: form.timezone,
    splitDefault: form.splitDefault,
    councilNeedBasis: form.councilNeedBasis,
    duplicateConfirmed,
    idempotency: { idempotencyKey },
  });

  const finishCreate = (unitId?: string) => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setPendingInput(null);
    if (unitId && onCreated) onCreated(unitId);
    else onClose();
  };

  const routeCreateOutcome = (
    outcome: { code?: string; unitId?: string; error?: string },
    input: Record<string, unknown>,
  ) => {
    if (outcome.code === 'CONFLICT') setPendingInput(input);
    else if (outcome.code) setFormError(outcome.error ?? 'Something went wrong.');
    else finishCreate(outcome.unitId);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateUnitForm(form);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    setFormError(null);
    setSubmitting(true);
    createOutcome.current = {};
    const input = buildInput(false, newUnitIdempotencyKey());
    try {
      await createUnit({ variables: { input } });
    } catch {
      // GraphQL errors are captured by the onError callback above; swallow to avoid an unhandled rejection.
    }
    setSubmitting(false);
    routeCreateOutcome(createOutcome.current, input);
  };

  const handleConfirmDuplicate = async () => {
    if (!pendingInput) return;
    createOutcome.current = {};
    try {
      await createUnit({
        variables: {
          input: {
            ...(pendingInput as object),
            duplicateConfirmed: true,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are captured by the onError callback above; swallow to avoid an unhandled rejection.
    }
    const outcome = createOutcome.current;
    if (outcome.code) {
      throw new Error(outcome.error ?? 'Something went wrong.');
    }
    finishCreate(outcome.unitId);
  };

  return (
    <>
      <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
        <DialogTitle>Create Unit</DialogTitle>
        <Box component="form" noValidate onSubmit={(e) => void handleSubmit(e)}>
          <DialogContent>
            <FormError text={formError} />
            <Stack spacing={2}>
              <TextField
                select
                fullWidth
                required
                label="Unit type"
                value={form.unitType}
                onChange={(e) => setField('unitType', e.target.value)}
              >
                {UNIT_TYPES_WITHOUT_NONE.map((t) => (
                  <MenuItem key={t.value} value={t.value}>
                    {t.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                fullWidth
                required
                label="Unit number"
                type="number"
                inputProps={{ inputMode: 'numeric', min: 1 }}
                value={form.unitNumber}
                onChange={(e) => setField('unitNumber', e.target.value)}
              />
              <TextField
                fullWidth
                required
                label="City"
                value={form.city}
                onChange={(e) => setField('city', e.target.value)}
              />
              <StateAutocomplete
                fullWidth
                required
                label="State"
                value={form.state}
                onChange={(v) => setField('state', v)}
              />
              <TextField
                fullWidth
                label="Display name (optional)"
                placeholder={previewName}
                value={form.displayName}
                onChange={(e) => setField('displayName', e.target.value)}
                helperText={`Shown as "${previewName}" when left blank`}
              />
              <TextField
                fullWidth
                required
                label="Timezone (IANA)"
                value={form.timezone}
                onChange={(e) => setField('timezone', e.target.value)}
                helperText="Used for display and calendar generation"
              />
              <TextField
                select
                fullWidth
                label="Default split"
                value={form.splitDefault}
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
                value={form.councilNeedBasis}
                onChange={(e) => setField('councilNeedBasis', e.target.value as GqlCouncilNeedBasis)}
              >
                {COUNCIL_BASIS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" variant="contained" startIcon={<AddIcon />} disabled={submitting}>
              {submitting ? 'Creating…' : 'Create Unit'}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
      <ConfirmDialog
        open={Boolean(pendingInput)}
        title="Create a distinct Unit?"
        onClose={() => setPendingInput(null)}
        onConfirm={handleConfirmDuplicate}
        confirmLabel="Create distinct Unit"
        confirmColor="warning"
      >
        <Typography>
          A Unit with this exact type, number, city, and state already exists. Confirm to create a separate,
          distinct Unit without merging them.
        </Typography>
      </ConfirmDialog>
    </>
  );
};

const UnitsLoadError: React.FC<{ message: string; onRetry: () => void }> = ({ message, onRetry }) => (
  <Box>
    <ErrorAlert message={message} />
    <Button variant="outlined" onClick={() => void onRetry()}>
      Retry
    </Button>
  </Box>
);

interface UnitCardProps {
  unit: GqlUnit;
  onOpen: (unitId: string) => void;
}

const UnitCard: React.FC<UnitCardProps> = ({ unit, onOpen }) => (
  <Card>
    <CardActionArea onClick={() => void onOpen(unit.unitId)} sx={{ height: '100%' }} data-testid={`unit-card-${unit.unitId}`}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {unitDisplayName(unit)}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {unit.unitType} {unit.unitNumber} · {unit.city}, {unit.state}
        </Typography>
        <Box sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Chip size="small" label={`${unit.adminCount} admin${unit.adminCount === 1 ? '' : 's'}`} />
          <Typography variant="body2" color="text.secondary">·</Typography>
          <Chip
            size="small"
            color="info"
            label={unit.splitDefault === 'EQUAL' ? 'Split equally' : 'Split by time worked'}
          />
        </Box>
      </CardContent>
    </CardActionArea>
  </Card>
);

const UnitsPage: React.FC = () => {
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const { data, loading, error, refetch } = useQuery<{ myUnits: { items: GqlUnit[] } }>(MY_UNITS);

  if (loading) return <LoadingState />;
  if (error) return <UnitsLoadError message={error.message || 'Unable to load your units.'} onRetry={() => void refetch()} />;

  const units = selectMyUnits(data);

  return (
    <Box>
      <PageHeader
        title="Units"
        subtitle="Scouting units you administer for Show & Sell."
        action={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            Create Unit
          </Button>
        }
      />
      <RedeemUnitInviteCard onRedeemed={() => void refetch()} />
      {units.length === 0 ? (
        <EmptyState
          title="No units yet"
          message="Create a Unit to start administering Show & Sell for it."
          actionLabel="Create Unit"
          onAction={() => setCreateOpen(true)}
        />
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' },
            gap: 2,
          }}
        >
          {units.map((unit) => (
            <Box key={unit.unitId}>
              <UnitCard unit={unit} onOpen={(id) => void navigate(`/units/${id}`)} />
            </Box>
          ))}
        </Box>
      )}
      <CreateUnitDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false);
          void navigate(`/units/${id}`);
        }}
      />
    </Box>
  );
};

export default UnitsPage;
