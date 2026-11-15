/**
 * Units list, Unit creation, and invite redemption (Show & Sell §1.6.1).
 *
 * `myUnits` returns only the Units this account holds a grant on, so the list is
 * also the answer to "am I an admin anywhere" — there is no browse-every-Units path
 * to hide. Creating a Unit makes the caller its first admin, and the exact
 * type/number/city/state duplicate warning is surfaced as a choice rather than a
 * dead end: two unrelated Units legitimately share a number in one city, and
 * confirming is how the second one gets created.
 *
 * Redeeming an invite lives here for the same reason the list does — before the
 * redemption there is no Unit to open, so the invited account needs an entry point
 * that does not depend on already being an admin.
 */

import React, { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import GroupWorkIcon from '@mui/icons-material/GroupWork';
import { CREATE_UNIT, MY_UNITS, REDEEM_UNIT_INVITE } from '../lib/graphql';
import type { GateQuery } from '../components/QueryGate';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { FormDialog } from '../components/FormDialog';
import { QueryGate } from '../components/QueryGate';
import { ConnectionRestNotice } from '../components/ConnectionRestNotice';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import { EmptyState } from '../components/EmptyState';
import { ErrorAlert } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { UnitFormFields } from '../components/UnitFormFields';
import { createUnitInput, emptyUnitForm, unitFormErrors, type UnitFormValues } from '../lib/unitForm';
import { SHOW_SELL_BASE, UNIT_PAGE_SIZE, isDuplicateUnitError, newIdempotencyKey, refreshQuery, unitDisplayName } from '../lib/units';
import type { GqlMyUnitsQuery, GqlUnit } from '../types/graphql-generated';

export const UnitsPage: React.FC = () => {
  const [createOpen, setCreateOpen] = useState(false);
  const unitList = useQuery<GqlMyUnitsQuery>(MY_UNITS, { variables: { page: { limit: UNIT_PAGE_SIZE } } });
  // The list of the caller's own Units is only correct when every page of it is here.
  const completeUnits = useCompleteConnection<GqlUnit>(unitList.data?.myUnits, {
    query: MY_UNITS,
    field: 'myUnits',
    limit: UNIT_PAGE_SIZE,
  });
  const openCreate = () => setCreateOpen(true);

  return (
    <>
      <PageHeader
        title="Units"
        subtitle="The Units you administer. A Unit holds its own campaigns, roster, and inventory."
        icon={GroupWorkIcon}
        action={
          <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate} data-testid="create-unit">
            Create Unit
          </Button>
        }
      />

      <RedeemInviteCard onRedeemed={unitList.refetch} />

      <UnitListSection result={unitList} units={completeUnits.items} rest={completeUnits} onCreate={openCreate} />

      {createOpen && <CreateUnitDialog onClose={() => setCreateOpen(false)} onCreated={unitList.refetch} />}
    </>
  );
};

/**
 * The list owns only the read's presentation: an empty account still has to be
 * told how to get a first Unit, and a failed read must not look like an empty one.
 */
const UnitListSection: React.FC<{
  result: GateQuery;
  units: GqlUnit[];
  rest: { loadingRest: boolean; failedRest: boolean };
  onCreate: () => void;
}> = ({ result, units, rest, onCreate }) => (
  <QueryGate
    query={result}
    loading={<LoadingState />}
    failure={<ErrorAlert message="Could not load your Units." />}
  >
    <UnitListBody units={units} onCreate={onCreate} />
    <ConnectionRestNotice loading={rest.loadingRest} failed={rest.failedRest} />
  </QueryGate>
);

/** No Units at all is an invitation, not an empty table. */
const UnitListBody: React.FC<{ units: GqlUnit[]; onCreate: () => void }> = ({ units, onCreate }) =>
  units.length === 0 ? (
    <EmptyState
      title="No Units yet"
      message="Create a Unit to run its campaigns, roster, and inventory."
      actionLabel="Create Unit"
      actionIcon={AddIcon}
      onAction={onCreate}
    />
  ) : (
    <Stack spacing={2} data-testid="unit-list">
      {units.map((unit) => (
        <UnitCard key={unit.unitId} unit={unit} />
      ))}
    </Stack>
  );

const UnitCard: React.FC<{ unit: GqlUnit }> = ({ unit }) => {
  const navigate = useNavigate();
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="h6" data-testid={`unit-name-${unit.unitId}`}>
              {unitDisplayName(unit)}
            </Typography>
            <Typography color="text.secondary" data-testid={`unit-summary-${unit.unitId}`}>
              {unit.unitType} {unit.unitNumber} · {unit.city}, {unit.state} · {unit.adminCount} admin
              {unit.adminCount === 1 ? '' : 's'}
            </Typography>
          </Box>
          <Button
            variant="outlined"
            onClick={() => void navigate(`${SHOW_SELL_BASE}/units/${unit.unitId}`)}
            data-testid={`open-unit-${unit.unitId}`}
          >
            Manage
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
};

const RedeemInviteCard: React.FC<{ onRedeemed: () => Promise<unknown> }> = ({ onRedeemed }) => {
  const [code, setCode] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [redeemInvite, { loading }] = useMutation(REDEEM_UNIT_INVITE);

  const redeem = async () => {
    const inviteCode = code.trim();
    if (!inviteCode) {
      setError('Enter the invite code you were given.');
      return;
    }
    setError(null);
    setMessage(null);
    try {
      await redeemInvite({
        variables: { input: { inviteCode, idempotency: { idempotencyKey: newIdempotencyKey() } } },
      });
      setCode('');
      setMessage('Invite redeemed. The Unit now appears in your list.');
      await refreshQuery(onRedeemed);
    } catch (redeemFailure) {
      setError((redeemFailure as Error).message || 'That invite code could not be redeemed.');
    }
  };

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="subtitle1" gutterBottom>
          Redeem an invite code
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          A Unit admin can invite you. Paste the 16-character code to become an admin of that Unit.
        </Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
          <TextField
            label="Invite code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            disabled={loading}
            sx={{ flexGrow: 1 }}
            inputProps={{ 'data-testid': 'invite-code' }}
          />
          <Button variant="outlined" onClick={() => void redeem()} disabled={loading} data-testid="redeem-invite">
            {loading ? 'Redeeming…' : 'Redeem'}
          </Button>
        </Stack>
        {message && (
          <Alert severity="success" sx={{ mt: 2 }} data-testid="redeem-success">
            {message}
          </Alert>
        )}
        {error && <ErrorAlert sx={{ mt: 2 }} message={error} />}
      </CardContent>
    </Card>
  );
};

/**
 * The create form, including the duplicate confirmation.
 *
 * The confirmation is a second intent, not a retry: the body changes
 * (`duplicateConfirmed`), so it carries a fresh idempotency key. Reusing the first
 * key would be refused as a changed fingerprint instead of answered by the attempt
 * that key already made.
 */
const CreateUnitDialog: React.FC<{ onClose: () => void; onCreated: () => Promise<unknown> }> = ({
  onClose,
  onCreated,
}) => {
  const [values, setValues] = useState<UnitFormValues>(emptyUnitForm);
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof UnitFormValues, string>>>({});
  const [pendingConfirm, setPendingConfirm] = useState<PendingDuplicate | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One key for this dialog's intent, so a retry after a dropped connection replays
  // the write that already happened instead of asking for a second Unit.
  const [intentKey] = useState(newIdempotencyKey);
  const [createUnit, { loading }] = useMutation(CREATE_UNIT);

  const submit = async (formValues: UnitFormValues, idempotencyKey: string, duplicateConfirmed: boolean) => {
    setError(null);
    try {
      await createUnit({ variables: { input: createUnitInput(formValues, idempotencyKey, duplicateConfirmed) } });
      setPendingConfirm(null);
      await refreshQuery(onCreated);
      onClose();
    } catch (mutationError) {
      if (isDuplicateUnitError(mutationError)) {
        setPendingConfirm({ values: formValues, idempotencyKey: newIdempotencyKey() });
        return;
      }
      setError((mutationError as Error).message || 'Could not create the Unit.');
    }
  };

  // Awaited, not fired: ConfirmDialog closes the form the moment `onConfirm`
  // resolves, and closing this dialog mid-mutation would cancel the request.
  const handleCreate = async () => {
    const errors = unitFormErrors(values);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) {
      // Refused, not dismissed: the form keeps what was typed and says which
      // fields are missing, because a Unit without geography has no tenant key.
      throw new Error('Fill in the Unit type, number, city, and state.');
    }
    await submit(values, intentKey, false);
  };

  return (
    <>
      <FormDialog
        title="Create a Unit"
        confirmLabel="Create Unit"
        onCancel={onClose}
        onConfirm={handleCreate}
        error={error}
        onDismissError={() => setError(null)}
      >
        <UnitFormFields values={values} onChange={setValues} errors={formErrors} disabled={loading} isCreate />
      </FormDialog>

      <ConfirmDialog
        open={pendingConfirm !== null}
        title="A Unit with these details already exists"
        confirmLabel="Create it as a separate Unit"
        confirmColor="warning"
        isLoading={loading}
        onClose={() => setPendingConfirm(null)}
        onConfirm={async () => {
          if (pendingConfirm) await submit(pendingConfirm.values, pendingConfirm.idempotencyKey, true);
        }}
      >
        <Typography>
          Another Unit already uses exactly this type, number, city, and state. Creating this one keeps them separate: no
          shared admins, no merged history.
        </Typography>
      </ConfirmDialog>
    </>
  );
};

interface PendingDuplicate {
  values: UnitFormValues;
  /** A confirmed duplicate is a different body, so it carries a different key. */
  idempotencyKey: string;
}
