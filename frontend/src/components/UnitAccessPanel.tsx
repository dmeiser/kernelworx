/**
 * Unit access administration (Show & Sell §1.6.2).
 *
 * One role is offered, because one role exists: `UnitRole` has a single value and
 * every admin is equal. There is deliberately no READ/WRITE selector here — that
 * gradient belongs to Scout profile sharing, and borrowing it for Units would promise
 * a capability the backend does not have.
 *
 * An invite is a bearer credential: shown once at creation, listed only while it is
 * still redeemable, and revoking one deletes it rather than labelling it. Revoking a
 * *grant* is the destructive action of this screen, and the last remaining admin
 * cannot be revoked from here at all — a Unit with no admin is unreachable, so the
 * server refuses that write too (`adminCount > 1` rides in the write condition, not
 * merely in this button's visibility).
 */

import React, {useCallback, useState} from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Box,
  Button,
  Card,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import {
  CREATE_UNIT_INVITE,
  LIST_UNIT_ADMINS,
  LIST_UNIT_INVITES,
  REVOKE_UNIT_ACCESS_GRANT,
  REVOKE_UNIT_INVITE,
} from '../lib/graphql';
import { ConfirmDialog } from './ConfirmDialog';
import { ErrorAlert } from './ErrorAlert';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { ConnectionRestNotice } from './ConnectionRestNotice';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import { UNIT_PAGE_SIZE, bareAccountId, isStaleVersionError, newIdempotencyKey, refreshQuery } from '../lib/units';
import type {
  GqlListUnitAdminsQuery,
  GqlListUnitInvitesQuery,
  GqlUnit,
  GqlUnitAccessGrant,
  GqlUnitInvite,
} from '../types/graphql-generated';

interface UnitAccessPanelProps {
  unit: GqlUnit;
  callerAccountId: string;
  onUnitChanged: () => Promise<unknown> | void;
}

interface PendingGrantRevocation {
  grant: GqlUnitAccessGrant;
  idempotencyKey: string;
}

export const UnitAccessPanel: React.FC<UnitAccessPanelProps> = ({ unit, callerAccountId, onUnitChanged }) => {
  const unitPage = { unitId: unit.unitId };
  const admins = useQuery<GqlListUnitAdminsQuery>(LIST_UNIT_ADMINS, {
    variables: { ...unitPage, page: { limit: UNIT_PAGE_SIZE } },
  });
  const invites = useQuery<GqlListUnitInvitesQuery>(LIST_UNIT_INVITES, {
    variables: { ...unitPage, page: { limit: UNIT_PAGE_SIZE } },
  });
  // Both lists decide what an admin can do next — who is still an admin, which codes
  // are still live — so a truncated page would be a wrong answer, not a short one.
  const completeAdmins = useCompleteConnection<GqlUnitAccessGrant>(admins.data?.unitAdmins, {
    query: LIST_UNIT_ADMINS,
    field: 'unitAdmins',
    limit: UNIT_PAGE_SIZE,
    variables: unitPage,
  });
  const completeInvites = useCompleteConnection<GqlUnitInvite>(invites.data?.unitInvites, {
    query: LIST_UNIT_INVITES,
    field: 'unitInvites',
    limit: UNIT_PAGE_SIZE,
    variables: unitPage,
  });
  const [createdCode, setCreatedCode] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [revokeInviteCode, setRevokeInviteCode] = useState<string | null>(null);
  const [pendingGrant, setPendingGrant] = useState<PendingGrantRevocation | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const grantList = completeAdmins.items;
  const inviteList = completeInvites.items;
  const caller = bareAccountId(callerAccountId);
  const pendingAccountId = bareAccountId(readPendingAccount(pendingGrant));

  const { handleCreateInvite, handleRevokeInvite, handleRevokeGrant, creatingInvite } = useAccessMutations({
    unitId: unit.unitId,
    unitVersion: unit.version,
    revokeInviteCode,
    pendingGrant,
    invites,
    admins,
    onUnitChanged,
    setActionError,
    setCreatedCode,
    setInviteError,
    setRevokeInviteCode,
    setPendingGrant,
  });

  return (
    <QueryGate
      query={admins}
      loading={<LoadingState minHeight="200px" />}
      failure={<ErrorAlert message="Could not load this Unit's admins." />}
    >
      <Box sx={{ pt: 2 }}>
        <ErrorNote message={actionError} />

        <AdminSection
          grants={grantList}
          callerAccountId={caller}
          lastAdmin={unit.adminCount <= 1}
          onRequestRevoke={(grant) => setPendingGrant({ grant, idempotencyKey: newIdempotencyKey() })}
        />

        <ConnectionRestNotice
          loading={completeAdmins.loadingRest || completeInvites.loadingRest}
          failed={completeAdmins.failedRest || completeInvites.failedRest}
        />

        <InviteSection
          invites={inviteList}
          createdCode={createdCode}
          inviteError={inviteError}
          creatingInvite={creatingInvite}
          onCreateInvite={() => void handleCreateInvite()}
          onRequestRevoke={setRevokeInviteCode}
        />

        <ConfirmDialog
          open={revokeInviteCode !== null}
          title="Revoke this invite?"
          confirmLabel="Revoke invite"
          confirmColor="error"
          onClose={() => setRevokeInviteCode(null)}
          onConfirm={handleRevokeInvite}
        >
          <Typography>
            The code stops working immediately and cannot be recovered. Anyone who has already used it keeps their
            access.
          </Typography>
        </ConfirmDialog>

        <ConfirmDialog
          open={pendingGrant !== null}
          title="Remove this admin?"
          confirmLabel="Remove admin"
          confirmColor="error"
          onClose={() => setPendingGrant(null)}
          onConfirm={handleRevokeGrant}
        >
          <GrantRemovalWarning grantAccountId={pendingAccountId} callerAccountId={caller} />
        </ConfirmDialog>
      </Box>
    </QueryGate>
  );
};

/**
 * The three access writes and what each failure means.
 *
 * A revoked invite that is already redeemed or already expired is simply gone — the
 * list is the authority on what is still redeemable, so it is re-read rather than
 * left showing a row that no longer means anything. A stale Unit version is a
 * re-read of the Unit before any further grant change.
 */
interface AccessMutationArgs {
  unitId: string;
  unitVersion: number;
  revokeInviteCode: string | null;
  pendingGrant: PendingGrantRevocation | null;
  invites: { refetch: () => Promise<unknown> };
  admins: { refetch: () => Promise<unknown> };
  onUnitChanged: () => Promise<unknown> | void;
  setActionError: (message: string | null) => void;
  setCreatedCode: (code: string | null) => void;
  setInviteError: (message: string | null) => void;
  setRevokeInviteCode: (code: string | null) => void;
  setPendingGrant: (pending: PendingGrantRevocation | null) => void;
}

function useAccessMutations(args: AccessMutationArgs) {
  const [createInvite, { loading: creatingInvite }] = useMutation(CREATE_UNIT_INVITE);
  const [revokeInvite] = useMutation(REVOKE_UNIT_INVITE);
  const [revokeGrant] = useMutation(REVOKE_UNIT_ACCESS_GRANT);

  const handleCreateInvite = useCallback(async () => {
    args.setInviteError(null);
    try {
      const result = await createInvite({
        variables: { input: { unitId: args.unitId, idempotency: { idempotencyKey: newIdempotencyKey() } } },
      });
      args.setCreatedCode(readInviteCode(result));
    } catch (mutationError) {
      args.setInviteError((mutationError as Error).message || 'Could not create an invite.');
    }
    await refreshQuery(args.invites.refetch);
  }, [args, createInvite]);

  const handleRevokeInvite = useCallback(async () => {
    const inviteCode = args.revokeInviteCode;
    args.setRevokeInviteCode(null);
    if (!inviteCode) return;
    try {
      await revokeInvite({
        variables: { input: { unitId: args.unitId, inviteCode, idempotency: { idempotencyKey: newIdempotencyKey() } } },
      });
    } catch (mutationError) {
      args.setActionError((mutationError as Error).message || 'That invite could not be revoked.');
    }
    await refreshQuery(args.invites.refetch);
  }, [args, revokeInvite]);

  const handleRevokeGrant = useCallback(async () => {
    const pending = args.pendingGrant;
    args.setPendingGrant(null);
    if (!pending) return;
    try {
      await revokeGrant({
        variables: {
          input: {
            unitId: args.unitId,
            accountId: pending.grant.accountId,
            version: { expectedVersion: args.unitVersion },
            idempotency: { idempotencyKey: pending.idempotencyKey },
          },
        },
      });
    } catch (mutationError) {
      args.setActionError(describeGrantFailure(mutationError));
    }
    await Promise.all([refreshQuery(args.admins.refetch), refreshQuery(args.invites.refetch), refreshQuery(args.onUnitChanged)]);
  }, [args, revokeGrant]);

  return { handleCreateInvite, handleRevokeInvite, handleRevokeGrant, creatingInvite };
}



function readInviteCode(result: unknown): string | null {
  const code = (result as { data?: { createUnitInvite?: { inviteCode?: string } } } | undefined)?.data?.createUnitInvite
    ?.inviteCode;
  return code ?? null;
}

function readPendingAccount(pending: PendingGrantRevocation | null): string {
  return pending?.grant.accountId ?? '';
}

function describeGrantFailure(mutationError: unknown): string {
  if (isStaleVersionError(mutationError)) return 'This Unit changed while you were working. Reload it and try again.';
  return (mutationError as Error).message || 'That admin could not be removed.';
}

const ErrorNote: React.FC<{ message: string | null }> = ({ message }) => {
  if (!message) return null;
  return <ErrorAlert message={message} />;
};

const AdminSection: React.FC<{
  grants: GqlUnitAccessGrant[];
  callerAccountId: string;
  lastAdmin: boolean;
  onRequestRevoke: (grant: GqlUnitAccessGrant) => void;
}> = ({ grants, callerAccountId, lastAdmin, onRequestRevoke }) => (
  <Box sx={{ mb: 3 }}>
    <Typography variant="h6" gutterBottom>
      Unit admins
    </Typography>
    <Typography color="text.secondary" sx={{ mb: 2 }}>
      Every Unit admin is equal: the same settings, invites, roster, and campaigns. No per-admin permission levels are
      offered because none exist.
    </Typography>
    <Card variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Admin</TableCell>
            <TableCell>Role</TableCell>
            <TableCell align="right">Remove</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {grants.map((grant) => (
            <AdminRow
              key={grant.accountId}
              grant={grant}
              isSelf={bareAccountId(grant.accountId) === callerAccountId}
              removeBlocked={lastAdmin}
              onRequestRevoke={onRequestRevoke}
            />
          ))}
        </TableBody>
      </Table>
    </Card>
  </Box>
);

const AdminRow: React.FC<{
  grant: GqlUnitAccessGrant;
  isSelf: boolean;
  removeBlocked: boolean;
  onRequestRevoke: (grant: GqlUnitAccessGrant) => void;
}> = ({ grant, isSelf, removeBlocked, onRequestRevoke }) => (
  <TableRow data-testid={`admin-row-${grant.accountId}`}>
    <TableCell>
      <AdminLabel grant={grant} isSelf={isSelf} />
    </TableCell>
    <TableCell data-testid={`role-${grant.accountId}`}>Admin</TableCell>
    <TableCell align="right">
      <GrantRemovalControl grant={grant} removeBlocked={removeBlocked} onRequestRevoke={onRequestRevoke} />
    </TableCell>
  </TableRow>
);

const AdminLabel: React.FC<{ grant: GqlUnitAccessGrant; isSelf: boolean }> = ({ grant, isSelf }) => (
  <>
    {grant.name || grant.email || grant.accountId}
    {isSelf ? ' (you)' : ''}
  </>
);

/**
 * A Unit keeps at least one admin. Hiding the control from the last one is the
 * friendly half of a rule the server enforces in the write condition, so a
 * direct-API attempt is refused as well (final-grant denial).
 */
const GrantRemovalControl: React.FC<{
  grant: GqlUnitAccessGrant;
  removeBlocked: boolean;
  onRequestRevoke: (grant: GqlUnitAccessGrant) => void;
}> = ({ grant, removeBlocked, onRequestRevoke }) => {
  if (removeBlocked) {
    return (
      <Tooltip title="A Unit keeps at least one admin. Invite another admin first.">
        <span>
          <Button size="small" disabled data-testid={`revoke-blocked-${grant.accountId}`}>
            Remove
          </Button>
        </span>
      </Tooltip>
    );
  }
  return (
    <Button size="small" color="error" onClick={() => onRequestRevoke(grant)} data-testid={`revoke-${grant.accountId}`}>
      Remove
    </Button>
  );
};

const GrantRemovalWarning: React.FC<{ grantAccountId: string; callerAccountId: string }> = ({
  grantAccountId,
  callerAccountId,
}) => (
  <Typography>
    {grantAccountId === callerAccountId
      ? 'You are removing your own access. This Unit leaves your list immediately.'
      : 'They lose access to this Unit immediately. Their past actions stay in the Unit history.'}
  </Typography>
);

const InviteSection: React.FC<{
  invites: GqlUnitInvite[];
  createdCode: string | null;
  inviteError: string | null;
  creatingInvite: boolean;
  onCreateInvite: () => void;
  onRequestRevoke: (code: string) => void;
}> = ({ invites, createdCode, inviteError, creatingInvite, onCreateInvite, onRequestRevoke }) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Invites
    </Typography>
    <Typography color="text.secondary" sx={{ mb: 2 }}>
      An invite is a 16-character code, valid for 14 days and usable once. Only codes that can still be redeemed are
      listed.
    </Typography>
    <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
      <Button
        variant="contained"
        startIcon={<PersonAddIcon />}
        onClick={onCreateInvite}
        disabled={creatingInvite}
        data-testid="create-invite"
      >
        {creatingInvite ? 'Creating…' : 'Create invite'}
      </Button>
      <Typography variant="body2" color="text.secondary" data-testid="active-invite-count">
        {invites.length} active invite{invites.length === 1 ? '' : 's'}
      </Typography>
    </Stack>
    <ErrorNote message={inviteError} />
    <NewInviteCode code={createdCode} />
    <Card variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Code</TableCell>
            <TableCell>Created by</TableCell>
            <TableCell>Expires</TableCell>
            <TableCell align="right">Revoke</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {invites.map((invite) => (
            <InviteRow key={invite.inviteCode} invite={invite} onRequestRevoke={onRequestRevoke} />
          ))}
          {invites.length === 0 && (
            <TableRow>
              <TableCell colSpan={4}>
                <Box sx={{ p: 2 }}>
                  <Typography color="text.secondary">No invites are waiting.</Typography>
                </Box>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Card>
  </Box>
);

const InviteRow: React.FC<{ invite: GqlUnitInvite; onRequestRevoke: (code: string) => void }> = ({
  invite,
  onRequestRevoke,
}) => (
  <TableRow data-testid={`invite-row-${invite.inviteCode}`}>
    <TableCell>{invite.inviteCode}</TableCell>
    <TableCell>{invite.createdByAccountId}</TableCell>
    <TableCell>{formatDate(invite.expiresAt)}</TableCell>
    <TableCell align="right">
      <Button size="small" onClick={() => onRequestRevoke(invite.inviteCode)} data-testid={`revoke-invite-${invite.inviteCode}`}>
        Revoke
      </Button>
    </TableCell>
  </TableRow>
);

const NewInviteCode: React.FC<{ code: string | null }> = ({ code }) => {
  if (!code) return null;
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
      <Typography data-testid="invite-code-value">Share this code with the admin you are inviting: {code}</Typography>
      <IconButton
        size="small"
        aria-label="Copy invite code"
        data-testid="copy-invite"
        onClick={() => void copyText(code)}
      >
        <ContentCopyIcon fontSize="small" />
      </IconButton>
    </Stack>
  );
};

function copyText(value: string): Promise<void> | undefined {
  return navigator.clipboard?.writeText(value);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString();
}
