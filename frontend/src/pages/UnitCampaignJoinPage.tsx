/**
 * The Scout-side join screen (Show & Sell §1.6.3).
 *
 * A join code is the only credential a participant needs, and it buys exactly the
 * preview the server projects: Unit name, campaign name and year, catalog name, and
 * whether the campaign is open. Nothing about the roster, the inventory, or another
 * Scout appears here because nothing about them is answerable to a code.
 *
 * Joining is an act of the Scout, not an appointment by a Unit Admin: the profile is
 * chosen from the caller's own Scout profiles and the server re-checks Owner or WRITE
 * on it. A code that is unknown, expired, or points at a closed campaign answers
 * identically, so this screen cannot be walked to enumerate Units.
 */

import React, { useState } from 'react';
import { useLazyQuery, useMutation, useQuery } from '@apollo/client/react';
import { Alert, Box, Button, Card, CardContent, Chip, Stack, TextField, Typography } from '@mui/material';
import HowToRegIcon from '@mui/icons-material/HowToReg';
import { GET_UNIT_CAMPAIGN_JOIN_INFO, JOIN_UNIT_CAMPAIGN, LIST_MY_PROFILES, LIST_MY_SHARES } from '../lib/graphql';
import { JoinProfilePicker } from '../components/JoinProfilePicker';
import { ErrorAlert, ErrorNote } from '../components/ErrorAlert';
import { PageHeader } from '../components/PageHeader';
import { joinableProfiles, newIdempotencyKey, refreshQuery } from '../lib/units';
import type { GqlGetUnitCampaignJoinInfoQuery, GqlListMyProfilesQuery, GqlListMySharesQuery } from '../types/graphql-generated';

interface JoinedNotice {
  campaignName: string;
  status: string;
}

type JoinPreview = NonNullable<GqlGetUnitCampaignJoinInfoQuery['unitCampaignJoinInfo']>;
type ScoutProfile = GqlListMyProfilesQuery['listMyProfiles']['profiles'][number];

function readPreview(data: GqlGetUnitCampaignJoinInfoQuery | undefined): JoinPreview | null {
  return data?.unitCampaignJoinInfo ?? null;
}

function readProfiles(data: GqlListMyProfilesQuery | undefined): ScoutProfile[] {
  return data?.listMyProfiles.profiles ?? [];
}

function readLookupError(error: unknown): string | null {
  if (!error) return null;
  return (error as Error).message || 'That code does not match an open campaign.';
}

export const UnitCampaignJoinPage: React.FC = () => {
  const [code, setCode] = useState('');
  const [lookedUpCode, setLookedUpCode] = useState('');
  const [localMessage, setLocalMessage] = useState<string | null>(null);
  const [joined, setJoined] = useState<JoinedNotice | null>(null);

  // Apollo v4 answers a lazy query through its result object rather than through
  // completion callbacks, so the preview and the server's refusal are read from that
  // result. The code that was looked up is held separately: editing the field
  // afterwards must not re-point the preview at whatever the new text names.
  const [lookupJoinInfo, lookup] = useLazyQuery<GqlGetUnitCampaignJoinInfoQuery>(GET_UNIT_CAMPAIGN_JOIN_INFO);
  const profiles = useQuery<GqlListMyProfilesQuery>(LIST_MY_PROFILES, { variables: { limit: 100 } });
  // A profile shared with WRITE joins on the holder's behalf, so the picker's list is
  // both sources; a failed shares read simply leaves the owned profiles.
  const shares = useQuery<GqlListMySharesQuery>(LIST_MY_SHARES);
  const preview = readPreview(lookup.data);

  const handleLookup = () => {
    const joinCode = code.trim();
    if (!joinCode) {
      setLocalMessage('Enter the join code your Unit admin gave you.');
      return;
    }
    setLocalMessage(null);
    setJoined(null);
    setLookedUpCode(joinCode);
    void lookupJoinInfo({ variables: { joinCode } });
  };

  return (
    <>
      <PageHeader
        title="Join a Unit Campaign"
        subtitle="Your Unit admin runs a campaign under a join code. Enter it here with the Scout profile to enrol."
        icon={HowToRegIcon}
      />

      <JoinLookupCard
        code={code}
        onCodeChange={setCode}
        onLookup={handleLookup}
        loading={lookup.loading}
        localMessage={localMessage}
        serverError={readLookupError(lookup.error)}
      />

      <JoinPreviewCard preview={preview} />
      <JoinProfileCard
        preview={preview}
        joined={joined}
        profiles={joinableProfiles(readProfiles(profiles.data), shares.data?.listMyShares)}
        joinCode={lookedUpCode}
        onJoined={setJoined}
        onProfileUsed={() => Promise.all([profiles.refetch(), shares.refetch()])}
      />
      <JoinedNoticeAlert notice={joined} />
    </>
  );
};

const JoinLookupCard: React.FC<{
  code: string;
  onCodeChange: (code: string) => void;
  onLookup: () => void;
  loading: boolean;
  localMessage: string | null;
  serverError: string | null;
}> = ({ code, onCodeChange, onLookup, loading, localMessage, serverError }) => (
  <Card variant="outlined" sx={{ mb: 3 }}>
    <CardContent>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField
          label="Join code"
          value={code}
          onChange={(event) => onCodeChange(event.target.value)}
          sx={{ flexGrow: 1 }}
          inputProps={{ 'data-testid': 'join-code-input' }}
        />
        <Button variant="contained" onClick={onLookup} disabled={loading} data-testid="lookup-join-code">
          {loading ? 'Checking…' : 'Check code'}
        </Button>
      </Stack>
      <JoinLookupMessages localMessage={localMessage} serverError={serverError} />
    </CardContent>
  </Card>
);

/**
 * A message typed by the caller and a refusal from the server are different facts;
 * only one is shown, because "enter the code" above "that code is not known" reads
 * as though both happened.
 */
const JoinLookupMessages: React.FC<{ localMessage: string | null; serverError: string | null }> = ({
  localMessage,
  serverError,
}) => {
  if (localMessage) return <ErrorAlert sx={{ mt: 2 }} message={localMessage} />;
  if (serverError) return <ErrorAlert sx={{ mt: 2 }} message={serverError} />;
  return null;
};

const JoinPreviewCard: React.FC<{ preview: JoinPreview | null }> = ({ preview }) => {
  if (!preview) return null;
  return (
    <Card variant="outlined" sx={{ mb: 3 }} data-testid="join-preview">
      <CardContent>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">{preview.campaignName}</Typography>
          <Chip size="small" color="success" label="Open" />
        </Stack>
        <Typography color="text.secondary">
          {preview.unitDisplayName} · {preview.campaignYear} · {preview.catalogName}
        </Typography>
      </CardContent>
    </Card>
  );
};

/**
 * Joining is a mutation of the Scout's own campaign, so it is issued here rather
 * than in the page: the page keeps the preview, and this card keeps the profile
 * choice and whatever the server said about the attempt.
 */
const JoinProfileCard: React.FC<{
  preview: JoinPreview | null;
  joined: JoinedNotice | null;
  profiles: ScoutProfile[];
  joinCode: string;
  onJoined: (notice: JoinedNotice) => void;
  onProfileUsed: () => Promise<unknown>;
}> = ({ preview, joined, profiles, joinCode, onJoined, onProfileUsed }) => {
  const [profileId, setProfileId] = useState('');
  const [error, setError] = useState<string | null>(null);
  // One key for this card's intent: a retry after a dropped connection is the same
  // join and must replay the original write rather than ask for a second membership.
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [joinCampaign, { loading }] = useMutation(JOIN_UNIT_CAMPAIGN);

  // The card exists only once a code has resolved to an open campaign, and only
  // until the join lands; both are stated before the write so the write can assume
  // the campaign it is naming.
  if (!preview || joined) return null;

  const join = async () => {
    const campaignId = campaignIdForProfile(profiles, profileId);
    if (!campaignId) {
      setError('Choose a Scout profile that already has a campaign.');
      return;
    }
    setError(null);
    try {
      const result = await joinCampaign({
        variables: { input: { joinCode, campaignId, idempotency: { idempotencyKey } } },
      });
      onJoined({ campaignName: preview.campaignName, status: readMembershipStatus(result) });
      await refreshQuery(onProfileUsed);
    } catch (mutationError) {
      setError((mutationError as Error).message || 'You could not join this campaign.');
    }
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Which Scout profile is joining?
        </Typography>
        <Stack spacing={2}>
          <JoinProfilePicker profiles={profiles} value={profileId} onChange={setProfileId} disabled={loading} />
          <ErrorNote message={error} />
          <Box>
            <JoinSubmit loading={loading} disabled={!profileId} onJoin={join} />
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
};

const JoinSubmit: React.FC<{ loading: boolean; disabled: boolean; onJoin: () => Promise<void> }> = ({
  loading,
  disabled,
  onJoin,
}) => (
  <Button
    variant="contained"
    onClick={() => void onJoin()}
    disabled={loading || disabled}
    data-testid="submit-join"
  >
    {loading ? 'Joining…' : 'Join campaign'}
  </Button>
);

const JoinedNoticeAlert: React.FC<{ notice: JoinedNotice | null }> = ({ notice }) => {
  if (!notice) return null;
  return (
    <Alert severity="success" data-testid="join-success">
      {joinedMessage(notice)}
    </Alert>
  );
};

/** ACTIVE is the state a fresh join lands in; anything else is named as it is. */
function joinedMessage(notice: JoinedNotice): string {
  if (notice.status === 'ACTIVE') return `Joined ${notice.campaignName}. Your Unit admin can now add you to events.`;
  return `Your membership in ${notice.campaignName} is ${notice.status}.`;
}

/** A profile without a current campaign has nothing to attach to the Unit Campaign. */
function campaignIdForProfile(profiles: ScoutProfile[], profileId: string): string | undefined {
  return profiles.find((profile) => profile.profileId === profileId)?.latestCampaign?.campaignId;
}

function readMembershipStatus(result: unknown): string {
  const status = (result as { data?: { joinUnitCampaign?: { status?: string } } } | undefined)?.data?.joinUnitCampaign
    ?.status;
  return status ?? 'ACTIVE';
}
