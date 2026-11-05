/**
 * UnitAccessSection - the access administration surface for a Unit (leaf 1.6.2).
 *
 * Wires `unitAdmins`, `createUnitInvite`, `revokeUnitInvite`, and
 * `revokeUnitAccessGrant`. There is a single role (UNIT_ADMIN) and a single
 * version gate: the Unit's own `version`, carried by the optimistic-concurrency
 * `expectedVersion`. Every mutation carries a fresh idempotency key, so a
 * network retry replays to the same logical operation.
 */

import React, { useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import {
  CREATE_UNIT_INVITE,
  GET_UNIT,
  REVOKE_UNIT_ACCESS_GRANT,
  REVOKE_UNIT_INVITE,
  UNIT_ADMINS,
  UNIT_INVITES,
} from '../lib/graphql';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { LoadingState } from '../components/LoadingState';
import { newUnitIdempotencyKey } from '../lib/unitForm';
import { useAuth } from '../contexts/AuthContext';
import type { GqlUnit, GqlUnitAccessGrant, GqlUnitInvite } from '../types';

type Outcome = { state: 'pending' | 'success' | 'error'; error: string | null };

const throwIfError = (outcome: Outcome): void => {
  if (outcome.state === 'error') throw new Error(outcome.error ?? 'Something went wrong.');
};

const anyLoading = (...flags: boolean[]): boolean => flags.some(Boolean);

const computeIsLastAdmin = (unit: GqlUnit | undefined, accountId: string | null): boolean =>
  Boolean(unit && unit.adminCount <= 1 && accountId);

interface UnitAccessData {
  unit: GqlUnit | undefined;
  admins: GqlUnitAccessGrant[];
  invites: GqlUnitInvite[];
  isLastAdmin: boolean;
}

const selectUnitAccess = (
  unitData: { unit: GqlUnit } | undefined,
  adminsData: { unitAdmins: { items: GqlUnitAccessGrant[] } } | undefined,
  invitesData: { unitInvites: { items: GqlUnitInvite[] } } | undefined,
  currentAccountId: string | null,
): UnitAccessData => {
  const unit = unitData ? unitData.unit : undefined;
  const admins = adminsData ? adminsData.unitAdmins.items : [];
  const invites = invitesData ? invitesData.unitInvites.items : [];
  return { unit, admins, invites, isLastAdmin: computeIsLastAdmin(unit, currentAccountId) };
};

interface AdminRowProps {
  admin: GqlUnitAccessGrant;
  isSelf: boolean;
  removeDisabled: boolean;
  onRevoke: (admin: GqlUnitAccessGrant) => void;
}

const AdminRow: React.FC<AdminRowProps> = ({ admin, isSelf, removeDisabled, onRevoke }) => (
  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
    <div>
      <Typography variant="body2">{admin.email}</Typography>
      <Typography variant="caption" color="text.secondary">
        {isSelf ? 'You' : admin.name || 'Admin'}
      </Typography>
    </div>
    <Stack direction="row" spacing={1} alignItems="center">
      <Chip size="small" label="UNIT_ADMIN" />
      <Button size="small" color="error" disabled={removeDisabled} onClick={() => onRevoke(admin)}>
        Remove
      </Button>
    </Stack>
  </Box>
);

interface AdminsCardProps {
  admins: GqlUnitAccessGrant[];
  currentAccountId: string | null;
  isLastAdmin: boolean;
  onRevokeAdmin: (admin: GqlUnitAccessGrant) => void;
}

const AdminsCard: React.FC<AdminsCardProps> = ({ admins, currentAccountId, isLastAdmin, onRevokeAdmin }) => (
  <Card variant="outlined">
    <CardHeader title="Admins" subheader="Unit admins manage settings, access, and campaigns." />
    <CardContent>
      {admins.length === 0 ? (
        <Typography>Awaiting admin resolution.</Typography>
      ) : (
        <Stack spacing={1}>
          {admins.map((admin) => (
            <AdminRow
              key={admin.accountId}
              admin={admin}
              isSelf={admin.accountId === currentAccountId}
              removeDisabled={isLastAdmin && admin.accountId === currentAccountId}
              onRevoke={onRevokeAdmin}
            />
          ))}
        </Stack>
      )}
      {isLastAdmin && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          A unit must keep at least one admin.
        </Typography>
      )}
    </CardContent>
  </Card>
);

interface InviteRowProps {
  invite: GqlUnitInvite;
  onRevoke: (invite: GqlUnitInvite) => void;
}

const InviteRow: React.FC<InviteRowProps> = ({ invite, onRevoke }) => (
  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.5 }}>
    <Box>
      <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
        {invite.inviteCode}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        Created {new Date(invite.createdAt).toLocaleDateString()}
        {invite.expiresAt ? ` · expires ${new Date(invite.expiresAt).toLocaleDateString()}` : ''}
      </Typography>
    </Box>
    <Button size="small" color="error" onClick={() => onRevoke(invite)}>
      Revoke
    </Button>
  </Box>
);

interface InvitesCardProps {
  invites: GqlUnitInvite[];
  inviteError: string | null;
  onCreateInvite: () => void;
  onRevokeInvite: (invite: GqlUnitInvite) => void;
}

const InvitesCard: React.FC<InvitesCardProps> = ({ invites, inviteError, onCreateInvite, onRevokeInvite }) => (
  <Card variant="outlined">
    <CardHeader
      title="Invites"
      subheader="Invite another account as a Unit Admin."
      action={
        <Button variant="outlined" startIcon={<AddIcon />} onClick={onCreateInvite}>
          Create invite
        </Button>
      }
    />
    <CardContent>
      {inviteError && <Alert severity="error" sx={{ mb: 1 }}>{inviteError}</Alert>}
      {invites.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No active invites.
        </Typography>
      ) : (
        <Stack spacing={1} data-testid="unit-invite-list">
          {invites.map((invite) => (
            <InviteRow key={invite.inviteCode} invite={invite} onRevoke={onRevokeInvite} />
          ))}
        </Stack>
      )}
    </CardContent>
  </Card>
);

interface RevokeAdminDialogProps {
  target: GqlUnitAccessGrant | null;
  onConfirm: () => Promise<void>;
  onDismiss: () => void;
}

const RevokeAdminDialog: React.FC<RevokeAdminDialogProps> = ({ target, onConfirm, onDismiss }) => (
  <ConfirmDialog
    open={Boolean(target)}
    title="Remove this admin?"
    onClose={onDismiss}
    onConfirm={onConfirm}
    confirmLabel="Remove"
    confirmColor="error"
    loadingLabel="Removing…"
  >
    {target && (
      <Typography variant="body2">
        {target.email} will lose access to this unit. They can be re-invited later.
      </Typography>
    )}
  </ConfirmDialog>
);

interface RevokeInviteDialogProps {
  target: GqlUnitInvite | null;
  onConfirm: () => Promise<void>;
  onDismiss: () => void;
}

const RevokeInviteDialog: React.FC<RevokeInviteDialogProps> = ({ target, onConfirm, onDismiss }) => (
  <ConfirmDialog
    open={Boolean(target)}
    title="Revoke this invite?"
    onClose={onDismiss}
    onConfirm={onConfirm}
    confirmLabel="Revoke"
    confirmColor="error"
    loadingLabel="Revoking…"
  >
    {target && (
      <Typography variant="body2">
        The code <code>{target.inviteCode}</code> will stop working.
      </Typography>
    )}
  </ConfirmDialog>
);

const UnitAccessSection: React.FC<{ unitId: string }> = ({ unitId }) => {
  const { account } = useAuth();
  const currentAccountId = account ? account.accountId : null;

  const { data: unitData, loading: unitLoading } = useQuery<{ unit: GqlUnit }>(GET_UNIT, {
    variables: { unitId },
  });
  const { data: adminsData, loading: adminsLoading } = useQuery<{
    unitAdmins: { items: GqlUnitAccessGrant[] };
  }>(UNIT_ADMINS, { variables: { unitId } });
  const { data: invitesData, loading: invitesLoading } = useQuery<{
    unitInvites: { items: GqlUnitInvite[] };
  }>(UNIT_INVITES, { variables: { unitId } });

  const { unit, admins, invites, isLastAdmin } = selectUnitAccess(
    unitData,
    adminsData,
    invitesData,
    currentAccountId,
  );
  const loading = anyLoading(unitLoading, adminsLoading, invitesLoading);

  const [revokeAdmin, setRevokeAdmin] = useState<GqlUnitAccessGrant | null>(null);
  const [revokeInvite, setRevokeInvite] = useState<GqlUnitInvite | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const adminOutcome = useRef<Outcome>({ state: 'pending', error: null });
  const inviteOutcome = useRef<Outcome>({ state: 'pending', error: null });

  const [revokeGrant] = useMutation(REVOKE_UNIT_ACCESS_GRANT, {
    refetchQueries: [{ query: UNIT_ADMINS, variables: { unitId } }, { query: GET_UNIT, variables: { unitId } }],
    onCompleted: () => {
      adminOutcome.current = { state: 'success', error: null };
      setRevokeAdmin(null);
    },
    onError: (e) => {
      adminOutcome.current = { state: 'error', error: mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e)) };
    },
  });

  const [createInvite] = useMutation(CREATE_UNIT_INVITE, {
    refetchQueries: [{ query: UNIT_INVITES, variables: { unitId } }],
    onError: (e) => setInviteError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e))),
  });

  const [revokeInviteMutation] = useMutation(REVOKE_UNIT_INVITE, {
    refetchQueries: [{ query: UNIT_INVITES, variables: { unitId } }],
    onCompleted: () => {
      inviteOutcome.current = { state: 'success', error: null };
      setRevokeInvite(null);
    },
    onError: (e) => {
      inviteOutcome.current = { state: 'error', error: mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e)) };
    },
  });

  const handleCreateInvite = async () => {
    setInviteError(null);
    try {
      await createInvite({
        variables: {
          input: { unitId, idempotency: { idempotencyKey: newUnitIdempotencyKey() } },
        },
      });
    } catch {
      // GraphQL errors are surfaced by the onError callback; swallow to avoid an unhandled rejection.
    }
  };

  const handleConfirmRevokeAdmin = async () => {
    if (!revokeAdmin || !unit) return;
    adminOutcome.current = { state: 'pending', error: null };
    try {
      await revokeGrant({
        variables: {
          input: {
            unitId,
            accountId: revokeAdmin.accountId,
            version: { expectedVersion: unit.version },
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are captured by the onError callback; swallow to avoid an unhandled rejection.
    }
    throwIfError(adminOutcome.current);
  };

  const handleConfirmRevokeInvite = async () => {
    if (!revokeInvite) return;
    inviteOutcome.current = { state: 'pending', error: null };
    try {
      await revokeInviteMutation({
        variables: {
          input: {
            unitId,
            inviteCode: revokeInvite.inviteCode,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are captured by the onError callback; swallow to avoid an unhandled rejection.
    }
    throwIfError(inviteOutcome.current);
  };

  if (loading) return <LoadingState minHeight="200px" />;

  return (
    <Stack spacing={2}>
      <AdminsCard admins={admins} currentAccountId={currentAccountId} isLastAdmin={isLastAdmin} onRevokeAdmin={setRevokeAdmin} />
      <InvitesCard
        invites={invites}
        inviteError={inviteError}
        onCreateInvite={() => void handleCreateInvite()}
        onRevokeInvite={setRevokeInvite}
      />
      <RevokeAdminDialog target={revokeAdmin} onConfirm={handleConfirmRevokeAdmin} onDismiss={() => setRevokeAdmin(null)} />
      <RevokeInviteDialog target={revokeInvite} onConfirm={handleConfirmRevokeInvite} onDismiss={() => setRevokeInvite(null)} />
    </Stack>
  );
};

export default UnitAccessSection;
