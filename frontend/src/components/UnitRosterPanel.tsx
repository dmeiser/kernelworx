/**
 * Unit Campaign roster and membership removal (Show & Sell §1.6.3).
 *
 * Removed Scouts stay on this list — their orders, credit, work minutes, and
 * Scout-held stock are this campaign's history, and the row saying who removed them
 * and when is why the record was never deleted (Blake-history-preservation).
 * Removal changes eligibility and nothing else.
 *
 * The removal write carries two versions because two rows move: the roster row and
 * the Scout Campaign's join-guard row. Both come from the roster query, which is why
 * the roster answers `guardVersion` at all — a button whose write needs a number no
 * query returns is a button that cannot work.
 */

import React, { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Box,
  Button,
  Card,
  Chip,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { LIST_UNIT_CAMPAIGN_ROSTER, REMOVE_UNIT_CAMPAIGN_MEMBERSHIP } from '../lib/graphql';
import { ConfirmDialog } from './ConfirmDialog';
import { ErrorAlert, ErrorNote } from './ErrorAlert';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { UNIT_PAGE_SIZE, newIdempotencyKey, refreshQuery } from '../lib/units';
import type {
  GqlListUnitCampaignRosterQuery,
  GqlMembershipStatus,
  GqlUnitCampaignMembership,
} from '../types/graphql-generated';

type StatusFilter = 'all' | 'active' | 'removed';

function toStatusFilter(status: StatusFilter): GqlMembershipStatus | undefined {
  if (status === 'all') return undefined;
  return status === 'active' ? 'ACTIVE' : 'REMOVED';
}

function readRoster(data: GqlListUnitCampaignRosterQuery | undefined): GqlUnitCampaignMembership[] {
  return data?.unitCampaignRoster.items ?? [];
}

function rosterCount(rows: GqlUnitCampaignMembership[]): string {
  return `${rows.length} roster ${rows.length === 1 ? 'entry' : 'entries'}`;
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

interface PendingRemoval {
  membership: GqlUnitCampaignMembership;
  idempotencyKey: string;
}

interface UnitRosterPanelProps {
  unitCampaignId: string;
}

export const UnitRosterPanel: React.FC<UnitRosterPanelProps> = ({ unitCampaignId }) => {
  const [status, setStatus] = useState<StatusFilter>('all');
  const [pending, setPending] = useState<PendingRemoval | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const roster = useQuery<GqlListUnitCampaignRosterQuery>(LIST_UNIT_CAMPAIGN_ROSTER, {
    variables: { unitCampaignId, status: toStatusFilter(status), page: { limit: UNIT_PAGE_SIZE } },
  });
  const [removeMembership, { loading }] = useMutation(REMOVE_UNIT_CAMPAIGN_MEMBERSHIP);
  const rows = useMemo(() => readRoster(roster.data), [roster.data]);

  const handleRemove = async () => {
    if (!pending) return;
    const { membership, idempotencyKey } = pending;
    setPending(null);
    try {
      await removeMembership({
        variables: {
          input: {
            unitCampaignId: membership.unitCampaignId,
            campaignId: membership.campaignId,
            expectedMembershipVersion: membership.version,
            expectedGuardVersion: membership.guardVersion,
            idempotency: { idempotencyKey },
          },
        },
      });
    } catch (mutationError) {
      setActionError((mutationError as Error).message || 'That Scout could not be removed.');
    }
    await refreshQuery(roster.refetch);
  };

  return (
    <QueryGate
      query={roster}
      loading={<LoadingState minHeight="200px" />}
      failure={<ErrorAlert message="Could not load this campaign's roster." />}
    >
      <RosterBody
        rows={rows}
        status={status}
        onStatusChange={setStatus}
        actionError={actionError}
        loading={loading}
        pending={pending}
        onAskRemove={setPending}
        onCancelRemove={() => setPending(null)}
        onConfirmRemove={handleRemove}
      />
    </QueryGate>
  );
};

const RosterBody: React.FC<{
  rows: GqlUnitCampaignMembership[];
  status: StatusFilter;
  onStatusChange: (status: StatusFilter) => void;
  actionError: string | null;
  loading: boolean;
  pending: PendingRemoval | null;
  onAskRemove: (pending: PendingRemoval) => void;
  onCancelRemove: () => void;
  onConfirmRemove: () => Promise<void>;
}> = ({ rows, status, onStatusChange, actionError, loading, pending, onAskRemove, onCancelRemove, onConfirmRemove }) => (
  <Box sx={{ pt: 2 }}>
    <ErrorNote message={actionError} />
    <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
      <TextField
        select
        label="Show"
        value={status}
        onChange={(event) => onStatusChange(event.target.value as StatusFilter)}
        size="small"
        data-testid="roster-filter"
      >
        <MenuItem value="all">Everyone (including removed)</MenuItem>
        <MenuItem value="active">Active only</MenuItem>
        <MenuItem value="removed">Removed only</MenuItem>
      </TextField>
      <Typography variant="body2" color="text.secondary" data-testid="roster-count">
        {rosterCount(rows)}
      </Typography>
    </Stack>

    <Card variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Scout profile</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Joined</TableCell>
            <TableCell>Removed</TableCell>
            <TableCell align="right">Action</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((membership) => (
            <RosterRow key={membership.profileId} membership={membership} onAskRemove={onAskRemove} />
          ))}
          {rows.length === 0 && <EmptyRosterRow />}
        </TableBody>
      </Table>
    </Card>

    <ConfirmDialog
      open={pending !== null}
      title="Remove this Scout from the campaign?"
      confirmLabel="Remove from campaign"
      confirmColor="error"
      isLoading={loading}
      onClose={onCancelRemove}
      onConfirm={onConfirmRemove}
    >
      <RemovalExplanation />
    </ConfirmDialog>
  </Box>
);

const RosterRow: React.FC<{
  membership: GqlUnitCampaignMembership;
  onAskRemove: (pending: PendingRemoval) => void;
}> = ({ membership, onAskRemove }) => (
  <TableRow data-testid={`roster-row-${membership.profileId}`}>
    <TableCell>{membership.profileId}</TableCell>
    <TableCell data-testid={`roster-status-${membership.profileId}`}>
      <MembershipStatusChip status={membership.status} />
    </TableCell>
    <TableCell>{formatDate(membership.joinedAt)}</TableCell>
    <TableCell data-testid={`roster-removed-${membership.profileId}`}>
      <RemovedNote membership={membership} />
    </TableCell>
    <TableCell align="right">
      <RosterAction membership={membership} onAskRemove={onAskRemove} />
    </TableCell>
  </TableRow>
);

const MembershipStatusChip: React.FC<{ status: GqlMembershipStatus }> = ({ status }) => (
  <Chip size="small" color={status === 'ACTIVE' ? 'success' : 'default'} label={status === 'ACTIVE' ? 'Joined' : 'Removed'} />
);

/** The removal audit is shown, not hidden: a removed row is history, not debris. */
const RemovedNote: React.FC<{ membership: GqlUnitCampaignMembership }> = ({ membership }) => {
  if (!membership.removedAt) return <>—</>;
  return <>{`${formatDate(membership.removedAt)} · ${membership.removedByAccountId ?? 'unknown'}`}</>;
};

/**
 * Only an ACTIVE row with a guard version can be removed. The version is not
 * decoration: it is the row the write conditions on, so a row that cannot answer it
 * gets no button rather than a button that fails.
 */
const RosterAction: React.FC<{
  membership: GqlUnitCampaignMembership;
  onAskRemove: (pending: PendingRemoval) => void;
}> = ({ membership, onAskRemove }) => {
  const removable = membership.status === 'ACTIVE' && membership.guardVersion !== null;
  if (!removable) {
    return (
      <Typography variant="body2" color="text.secondary" data-testid={`no-action-${membership.profileId}`}>
        {membership.status === 'ACTIVE' ? 'Unavailable' : 'History kept'}
      </Typography>
    );
  }
  return (
    <Button
      size="small"
      color="error"
      onClick={() => onAskRemove({ membership, idempotencyKey: newIdempotencyKey() })}
      data-testid={`remove-member-${membership.profileId}`}
    >
      Remove
    </Button>
  );
};

const EmptyRosterRow: React.FC = () => (
  <TableRow>
    <TableCell colSpan={5}>
      <Box sx={{ p: 2 }}>
        <Typography color="text.secondary">No roster entries match this filter.</Typography>
      </Box>
    </TableCell>
  </TableRow>
);

const RemovalExplanation: React.FC = () => (
  <Typography>
    They stop being able to sign up for this campaign's events. Their existing orders, credit, work minutes, and
    Scout-held stock stay exactly as they are, and this roster keeps the entry with the removal date. They can rejoin
    later with the same join code.
  </Typography>
);
