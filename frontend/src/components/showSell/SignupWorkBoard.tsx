/**
 * The signup board and work confirmation of one event (§3.5.4, built on
 * §3.4.1-§3.4.5).
 *
 * Two facts that look alike are deliberately kept apart here:
 *
 * - **A signup is not worked time.** A Scout holding a place says nothing about the
 *   minutes a Kernel actually saw (`SLOT-05`), so the minutes column starts empty
 *   and stays empty until a Kernel enters it.
 * - **Entering zero is un-confirming, not deleting.** §3.4.3 makes 0 the way a
 *   mistake is taken back: the signup stays, its confirmed minutes go away, and the
 *   finalization write set the confirmation staged is freed. The row never
 *   *disappears*, which is why the board shows cancelled signups too — they are the
 *   history an audit question is asked about.
 *
 * The minutes a row accepts is bounded by that slot's own length: a 90-minute slot
 * cannot contain 115 worked minutes, and the field says so before the write rather
 * than letting the server refuse the whole batch, which would also discard the
 * other rows the admin typed.
 *
 * The preview under the board is the server's, from the batch that just saved:
 * confirmed minutes, the rows and participants behind them, and the minimum
 * finalization write set that picture implies. It is computed, never approved —
 * approving credit is finalization's act, not this read's.
 *
 * A saved row and that preview are the same write's answer, so the row shows it as
 * soon as the save lands: the board re-reads its own signup query after a write, and
 * while that read is in flight the row holds the after-image the write itself
 * answered. A table left at the pre-save number beside a preview that already moved
 * is the screen disagreeing with itself about one save.
 *
 * The calendar action on each row is data-only: it reads the authorized invite
 * fields and hands the browser a file it assembled itself. Nothing on the server is
 * generated, stored, or mailed (CAL-01, CAL-02).
 */

import React, { useMemo, useState } from 'react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import {
  CONFIRM_SHOW_AND_SELL_WORK,
  GET_SIGNUP_CALENDAR_DATA,
  LIST_SHOW_AND_SELL_SIGNUPS,
  LIST_UNIT_CAMPAIGN_ROSTER,
} from '../../lib/graphql';
import {
  SHOW_AND_SELL_PAGE_SIZE,
  acceptsWorkConfirmation,
  buildInvite,
  changedWorkLines,
  describeShowAndSellFailure,
  downloadInvite,
  durationBySlot,
  inviteFileName,
  reportWriteFailure,
  slotNameOf,
  sortBy,
  withIdempotency,
  workDraftsOf,
  workRowKey,
} from '../../lib/showSell';
import { UNIT_PAGE_SIZE, createWriteIntent, refreshQuery } from '../../lib/units';
import { scoutLabel } from '../../lib/inventory';
import { ConnectionRestNotice } from '../ConnectionRestNotice';
import { ErrorAlert, ErrorNote } from '../ErrorAlert';
import { LoadingState } from '../LoadingState';
import { QueryGate } from '../QueryGate';
import { useCompleteConnection } from '../../hooks/useCompleteConnection';
import type {
  GqlConfirmShowAndSellWorkMutation,
  GqlGetSignupCalendarDataQuery,
  GqlListShowAndSellSignupsQuery,
  GqlListUnitCampaignRosterQuery,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSignupFieldsFragment,
  GqlShowAndSellWorkPreviewFieldsFragment,
  GqlUnitCampaignMembershipFieldsFragment,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Signup = GqlShowAndSellSignupFieldsFragment;
type WorkPreview = GqlShowAndSellWorkPreviewFieldsFragment;

const SIGNUP_VARIABLES = (showAndSellId: string) => ({
  showAndSellId,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
});

const ROSTER_VARIABLES = (unitCampaignId: string) => ({
  unitCampaignId,
  status: undefined,
  page: { limit: UNIT_PAGE_SIZE },
});

export const SignupWorkBoard: React.FC<{
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, timezone, onChanged }) => {
  const client = useApolloClient();
  const signups = useQuery<GqlListShowAndSellSignupsQuery>(LIST_SHOW_AND_SELL_SIGNUPS, {
    variables: SIGNUP_VARIABLES(event.showAndSellId),
  });
  const roster = useQuery<GqlListUnitCampaignRosterQuery>(LIST_UNIT_CAMPAIGN_ROSTER, {
    variables: ROSTER_VARIABLES(event.unitCampaignId),
  });
  const allSignups = useCompleteConnection<Signup>(signups.data?.showAndSellSignups, {
    query: LIST_SHOW_AND_SELL_SIGNUPS,
    field: 'showAndSellSignups',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: SIGNUP_VARIABLES(event.showAndSellId),
  });
  const allRoster = useCompleteConnection<GqlUnitCampaignMembershipFieldsFragment>(roster.data?.unitCampaignRoster, {
    query: LIST_UNIT_CAMPAIGN_ROSTER,
    field: 'unitCampaignRoster',
    limit: UNIT_PAGE_SIZE,
    variables: ROSTER_VARIABLES(event.unitCampaignId),
  });

  const names = useMemo(
    () => new Map(allRoster.items.map((member) => [member.profileId, member.scoutName])),
    [allRoster.items],
  );
  const durationOf = useMemo(() => durationBySlot(event), [event]);

  // What the last accepted save answered for each row it touched, kept until a read
  // of this board's own query is at least as new. The preview under the board is that
  // same save's answer, so a row that goes on showing its pre-save read while the
  // preview has moved is the screen disagreeing with itself about one write.
  const [answered, setAnswered] = useState<Map<string, Signup>>(new Map());
  const rows = useMemo(
    () => sortBy(shownRows(allSignups.items, answered), (signup) => `${signup.slotId} ${signup.profileId}`),
    [allSignups.items, answered],
  );

  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [preview, setPreview] = useState<WorkPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const intent = React.useRef(createWriteIntent());
  const [confirmWork, { loading }] = useMutation<GqlConfirmShowAndSellWorkMutation>(CONFIRM_SHOW_AND_SELL_WORK);

  const writable = acceptsWorkConfirmation(event.status);

  const save = async () => {
    const collected = changedWorkLines(workDraftsOf(rows, drafts), rows, durationOf);
    if (collected.error !== null) {
      setError(collected.error);
      return;
    }
    if (collected.lines.length === 0) return;
    const body = {
      showAndSellId: event.showAndSellId,
      work: collected.lines,
      version: { expectedVersion: event.version },
    };
    try {
      const result = await confirmWork({ variables: { input: withIdempotency(body, intent.current) } });
      setPreview(previewOf(result));
      setAnswered((current) => answeredRows(current, writtenRows(result)));
      setSavedCount(collected.lines.length);
      setDrafts(new Map());
    } catch (mutationError) {
      setError(await reportWriteFailure(mutationError, 'Could not save the worked time.', onChanged));
      return;
    }
    // The event is re-read for its version, and this board's own signup read is
    // re-read for the rows: they are different queries, and refreshing only the
    // event leaves the table showing what it held before the save until the whole
    // page is reloaded, next to a preview that already moved.
    await refreshQuery(async () => {
      await Promise.all([signups.refetch(), onChanged()]);
    });
  };

  const download = async (signup: Signup) => {
    setError(null);
    try {
      const invite = await readCalendarData(client, signup);
      downloadInvite(inviteFileName(invite), buildInvite(invite));
    } catch (calendarError) {
      setError(describeShowAndSellFailure(calendarError, 'Could not read the calendar data for this signup.'));
    }
  };

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="signup-note">
        Confirmed work is what a Kernel saw, entered per Scout and per slot. Entering 0 takes a confirmation back. Worked
        minutes decide a split by worked time; they are not approved credit until the event is finalized.
      </Alert>
      {writable ? null : (
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="work-locked-note">
          Worked time is entered while the event is running, after it ends, or while it is reopened for correction. This
          event’s state does not allow it.
        </Alert>
      )}
      <QueryGate
        query={signups}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="Could not load this event’s signups." />}
      >
        <SignupTable
          rows={rows}
          event={event}
          names={names}
          drafts={drafts}
          writable={writable}
          loading={loading}
          onDraft={(key, value) => setDrafts((current) => new Map(current).set(key, value))}
          onDownload={(signup) => void download(signup)}
        />
        <ConnectionRestNotice loading={allSignups.loadingRest} failed={allSignups.failedRest} />
      </QueryGate>
      {rows.length === 0 ? (
        <Typography color="text.secondary" data-testid="no-signups">
          No Scout has a place in this event yet.
        </Typography>
      ) : null}
      <ErrorNote message={error} />
      <Stack direction="row" spacing={2} sx={{ pt: 2 }} alignItems="center" flexWrap="wrap">
        <WorkSaveButton writable={writable} loading={loading} onSave={() => void save()} />
        <SavedCount count={savedCount} />
      </Stack>
      <WorkPreviewCard preview={preview} timezone={timezone} />
    </Box>
  );
};

/** What the save answered for the event: its pending picture, or null when the batch carried none. */
function previewOf(result: { data?: GqlConfirmShowAndSellWorkMutation }): WorkPreview | null {
  const preview = result.data?.confirmShowAndSellWork?.preview;
  return (preview as WorkPreview | undefined) ?? null;
}

/**
 * What the same save answered for the rows it wrote.
 *
 * This is the server's own after-image, not a number this screen summed up, which is
 * why it is kept: the preview under the board is computed from these very rows.
 */
function writtenRows(result: { data?: GqlConfirmShowAndSellWorkMutation }): readonly Signup[] {
  return result.data?.confirmShowAndSellWork?.work ?? [];
}

/** The newest answer the server has given for every row this board has saved. */
function answeredRows(current: ReadonlyMap<string, Signup>, written: readonly Signup[]): Map<string, Signup> {
  const next = new Map(current);
  for (const signup of written) next.set(workRowKey(signup.slotId, signup.profileId), signup);
  return next;
}

/**
 * The read, with each saved row replaced by what the save answered for it — while the
 * read has not moved past that answer.
 *
 * Which of the two is newer is a fact the rows state rather than a guess the browser
 * makes: a signup carries its own version. The save's answer wins over a read at an
 * older version, and a read at a newer version wins over it — that read is either
 * this board's own re-read catching up, or another Kernel's change arriving. So the
 * row and the preview under it agree the moment a save lands, and keep agreeing when
 * the re-read arrives with the same number.
 */
function shownRows(rows: readonly Signup[], answered: ReadonlyMap<string, Signup>): Signup[] {
  return rows.map((signup) => {
    const written = answered.get(workRowKey(signup.slotId, signup.profileId));
    return written !== undefined && written.version >= signup.version ? written : signup;
  });
}

/**
 * The authorized invite fields for one signup, read fresh.
 *
 * `network-only` because the fields are the ones a calendar file is built from: a
 * cached read of an event whose slot moved would write an invite for a time that no
 * longer exists.
 */
async function readCalendarData(
  client: ReturnType<typeof useApolloClient>,
  signup: Signup,
): Promise<NonNullable<GqlGetSignupCalendarDataQuery['showAndSellSignupCalendarData']>> {
  const { data } = await client.query<GqlGetSignupCalendarDataQuery>({
    query: GET_SIGNUP_CALENDAR_DATA,
    variables: { showAndSellId: signup.showAndSellId, slotId: signup.slotId, profileId: signup.profileId },
    fetchPolicy: 'network-only',
  });
  const invite = data?.showAndSellSignupCalendarData;
  if (!invite) throw new Error('The server answered no calendar data for this signup.');
  return invite;
}

/** The save, named for what it does to the event's records rather than for a button. */
const WorkSaveButton: React.FC<{ writable: boolean; loading: boolean; onSave: () => void }> = ({
  writable,
  loading,
  onSave,
}) => (
  <Button
    variant="contained"
    onClick={onSave}
    disabled={!writable || loading}
    data-testid="save-work"
  >
    {loading ? 'Saving…' : 'Save worked time'}
  </Button>
);

const SavedCount: React.FC<{ count: number | null }> = ({ count }) => {
  if (count === null) return null;
  return (
    <Typography variant="body2" color="text.secondary" data-testid="work-saved-count">
      {count} work {count === 1 ? 'row' : 'rows'} saved.
    </Typography>
  );
};

const SignupTable: React.FC<{
  rows: Signup[];
  event: Event;
  names: Map<string, string>;
  drafts: Map<string, string>;
  writable: boolean;
  loading: boolean;
  onDraft: (key: string, value: string) => void;
  onDownload: (signup: Signup) => void;
}> = ({ rows, event, names, drafts, writable, loading, onDraft, onDownload }) => (
  <>
    <Table size="small" aria-label="Scout signups and confirmed work">
      <TableHead>
        <TableRow>
          <TableCell>Scout</TableCell>
          <TableCell>Slot</TableCell>
          <TableCell>Place</TableCell>
          <TableCell>Minutes worked</TableCell>
          <TableCell>Confirmed by</TableCell>
          <TableCell aria-label="Actions" />
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((signup) => {
          const key = workRowKey(signup.slotId, signup.profileId);
          return (
            <SignupRow
              key={key}
              rowKey={key}
              signup={signup}
              slotName={slotNameOf(event.slots, signup.slotId)}
              scoutName={names.get(signup.profileId)}
              draft={drafts.get(key)}
              writable={writable}
              loading={loading}
              onDraft={onDraft}
              onDownload={onDownload}
            />
          );
        })}
      </TableBody>
    </Table>
  </>
);

/**
 * One Scout's place in one slot.
 *
 * The minutes box starts at the stored value, not at zero: an admin correcting a
 * wrong number has to see the wrong number to know it is the one they are fixing.
 */
const SignupRow: React.FC<{
  rowKey: string;
  signup: Signup;
  slotName: string;
  scoutName?: string;
  draft?: string;
  writable: boolean;
  loading: boolean;
  onDraft: (key: string, value: string) => void;
  onDownload: (signup: Signup) => void;
}> = ({ rowKey, signup, slotName, scoutName, draft, writable, loading, onDraft, onDownload }) => (
  <TableRow data-testid={`signup-row-${rowKey}`}>
    <TableCell data-testid={`signup-scout-${rowKey}`}>{scoutLabel({ profileId: signup.profileId, scoutName })}</TableCell>
    <TableCell data-testid={`signup-slot-${rowKey}`}>{slotName}</TableCell>
    <TableCell data-testid={`signup-status-${rowKey}`}>
      {signup.status === 'ACTIVE' ? 'Holding a place' : 'Cancelled'}
    </TableCell>
    <TableCell>
      <TextField
        size="small"
        inputMode="numeric"
        value={draft ?? String(signup.actualMinutes)}
        onChange={(input) => onDraft(rowKey, input.target.value)}
        disabled={!writable || loading}
        inputProps={{
          'data-testid': `work-minutes-${rowKey}`,
          'aria-label': `Minutes worked in slot ${slotName}`,
        }}
        sx={{ width: 96 }}
      />
    </TableCell>
    <TableCell data-testid={`signup-confirmed-by-${rowKey}`}>
      {signup.confirmedByAccountId ? 'Kernel' : 'Not confirmed'}
    </TableCell>
    <TableCell>
      <Button
        size="small"
        startIcon={<FileDownloadIcon />}
        onClick={() => onDownload(signup)}
        data-testid={`invite-${rowKey}`}
      >
        Calendar
      </Button>
    </TableCell>
  </TableRow>
);

/**
 * The pending picture the last save answered.
 *
 * It appears only once a batch has been saved, because there is no read that
 * computes it: the number an admin sees here is the number the write staged, and
 * showing a locally summed figure instead would be the browser inventing the
 * server's answer.
 */
const WorkPreviewCard: React.FC<{ preview: WorkPreview | null; timezone: string }> = ({ preview, timezone }) => {
  if (preview === null) return <WorkPreviewAbsent />;
  return (
    <Card variant="outlined" sx={{ mt: 3 }} data-testid="work-preview">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom>
          Pending work picture (event version {preview.eventVersion})
        </Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3} flexWrap="wrap">
          <Typography data-testid="preview-minutes">{preview.totalConfirmedMinutes} confirmed minutes</Typography>
          <Typography data-testid="preview-rows">{preview.confirmedWorkRows} confirmed rows</Typography>
          <Typography data-testid="preview-people">{preview.confirmedParticipants} Scouts</Typography>
          <Typography data-testid="preview-actions">
            {preview.minimumFinalizationActions} finalization actions needed
          </Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ pt: 1 }}>
          Computed against the event as it stands in {timezone}; a later change moves these numbers.
        </Typography>
      </CardContent>
    </Card>
  );
};

const WorkPreviewAbsent: React.FC = () => (
  <Card variant="outlined" sx={{ mt: 3 }} data-testid="work-preview-empty">
    <CardContent>
      <Typography color="text.secondary">
        The pending work picture appears after worked time is saved. It is computed, never approved — approving credit is
        what finalization does.
      </Typography>
    </CardContent>
  </Card>
);
