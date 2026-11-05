/**
 * JoinUnitCampaignPage - a participant's "join a unit's campaign by code" flow
 * (leaf 1.6.3). The participant picks one of their own Scout Campaigns, enters
 * the unit campaign's join code, and calls `joinUnitCampaign` to link their
 * campaign to the unit campaign. The server validates the code and the roster
 * identity; the page only ever sends the participant's own campaignId plus the
 * code.
 */

import React, { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { LIST_MY_PROFILES, LIST_CAMPAIGNS_BY_PROFILE, JOIN_UNIT_CAMPAIGN } from '../lib/graphql';
import { PageHeader } from '../components/PageHeader';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { EmptyState } from '../components/EmptyState';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { newUnitIdempotencyKey } from '../lib/unitForm';
import type { GqlCampaign, GqlSellerProfile, GqlUnitCampaignMembership } from '../types';

const selectProfiles = (data: { listMyProfiles: { profiles: GqlSellerProfile[] } } | undefined): GqlSellerProfile[] =>
  data ? data.listMyProfiles.profiles : [];

const selectCampaigns = (data: { listCampaignsByProfile: { campaigns: GqlCampaign[] } } | undefined): GqlCampaign[] =>
  data ? data.listCampaignsByProfile.campaigns : [];

const Shell: React.FC<{ children: React.ReactNode; subtitle?: string }> = ({ children, subtitle }) => (
  <Box>
    <PageHeader title="Join a Unit Campaign" subtitle={subtitle} />
    {children}
  </Box>
);

const CampaignPicker: React.FC<{
  profileId: string;
  selectedCampaignId: string | null;
  onSelect: (campaignId: string) => void;
}> = ({ profileId, selectedCampaignId, onSelect }) => {
  const { data, loading } = useQuery<{ listCampaignsByProfile: { campaigns: GqlCampaign[] } }>(
    LIST_CAMPAIGNS_BY_PROFILE,
    { variables: { profileId } },
  );
  const campaigns = selectCampaigns(data);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (campaigns.length === 0) {
    return (
      <Alert severity="info">
        This profile has no campaigns yet. Create one before joining a unit campaign.
      </Alert>
    );
  }
  return (
    <TextField
      select
      label="Your campaign to join"
      value={selectedCampaignId ?? ''}
      onChange={(e) => onSelect(e.target.value)}
    >
      {campaigns.map((c) => (
        <MenuItem key={c.campaignId} value={c.campaignId}>
          {c.campaignName} ({c.campaignYear})
        </MenuItem>
      ))}
    </TextField>
  );
};

const JoinForm: React.FC<{ profiles: GqlSellerProfile[] }> = ({ profiles }) => {
  const navigate = useNavigate();
  const [selectedProfileId, setSelectedProfileId] = useState<string>(profiles[0].profileId);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [joinCode, setJoinCode] = useState('');
  const [joinError, setJoinError] = useState<string | null>(null);

  const [join, { loading: joining }] = useMutation<{ joinUnitCampaign: GqlUnitCampaignMembership }>(
    JOIN_UNIT_CAMPAIGN,
    {
      onCompleted: () => {
        void navigate(`/scouts/${selectedProfileId}/campaigns`);
      },
      onError: (e) => setJoinError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e))),
    },
  );

  const handleProfileChange = (value: string) => {
    setSelectedProfileId(value);
    setSelectedCampaignId(null);
  };

  const handleCampaignChange = (value: string) => {
    setSelectedCampaignId(value);
    setJoinError(null);
  };

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    setJoinError(null);
    if (!selectedCampaignId || !joinCode.trim()) {
      setJoinError('Select a campaign and enter the join code.');
      return;
    }
    await join({
      variables: {
        input: {
          campaignId: selectedCampaignId,
          joinCode: joinCode.trim(),
          idempotency: { idempotencyKey: newUnitIdempotencyKey() },
        },
      },
    });
  };

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2}>
        <TextField
          select
          label="Your profile"
          value={selectedProfileId}
          onChange={(e) => handleProfileChange(e.target.value)}
        >
          {profiles.map((p) => (
            <MenuItem key={p.profileId} value={p.profileId}>
              {p.sellerName}
            </MenuItem>
          ))}
        </TextField>
        <CampaignPicker
          profileId={selectedProfileId}
          selectedCampaignId={selectedCampaignId}
          onSelect={handleCampaignChange}
        />
        {joinError && <Alert severity="error">{joinError}</Alert>}
        <form onSubmit={(e) => void handleJoin(e)}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <TextField
              label="Join code"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value)}
              sx={{ flex: 1 }}
              disabled={!selectedCampaignId}
            />
            <Button type="submit" variant="contained" disabled={!selectedCampaignId || joining}>
              {joining ? 'Joining…' : 'Join'}
            </Button>
          </Stack>
        </form>
        <Typography variant="caption" color="text.secondary">
          The join code is shown on the unit campaign's detail page. Joining links the selected campaign to that
          unit campaign.
        </Typography>
      </Stack>
    </Paper>
  );
};

const JoinUnitCampaignPage: React.FC = () => {
  const { data, loading, error } = useQuery<{ listMyProfiles: { profiles: GqlSellerProfile[] } }>(
    LIST_MY_PROFILES,
  );

  if (loading) {
    return (
      <Shell>
        <LoadingState minHeight="300px" />
      </Shell>
    );
  }
  if (error) {
    return (
      <Shell>
        <ErrorAlert message={error.message || 'Unable to load your profiles.'} />
      </Shell>
    );
  }
  const profiles = selectProfiles(data);
  if (profiles.length === 0) {
    return (
      <Shell>
        <EmptyState title="No profiles" message="You need a profile before you can join a unit campaign." />
      </Shell>
    );
  }

  return (
    <Shell subtitle="Link one of your campaigns to a unit's campaign.">
      <JoinForm profiles={profiles} />
    </Shell>
  );
};

export default JoinUnitCampaignPage;
