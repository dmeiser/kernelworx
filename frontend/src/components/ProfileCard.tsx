/**
 * ProfileCard component - Display a single scout profile with latest campaign stats
 *
 * Note: Unit fields have been moved to Campaign level as part of the Shared Campaign
 * refactor. Unit information is now displayed on campaigns, not profiles.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Card, CardContent, CardActions, Typography, Button, Chip, Stack, Box, CircularProgress } from '@mui/material';
import {
  Person as PersonIcon,
  Visibility as ViewIcon,
  Settings as SettingsIcon,
  TrendingUp as TrendingUpIcon,
  CalendarToday as CalendarIcon,
} from '@mui/icons-material';
import { LIST_CAMPAIGNS_BY_PROFILE } from '../lib/graphql';
import { ensureProfileId, toUrlId } from '../lib/ids';

interface Campaign {
  campaignId: string;
  campaignName: string;
  campaignYear: number;
  totalOrders: number;
  totalRevenue: number;
  startDate: string;
}

interface ProfileCardProps {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

const PermissionChip: React.FC<{ isOwner: boolean; hasWrite: boolean }> = ({ isOwner, hasWrite }) => {
  if (isOwner) return <Chip label="Owner" color="primary" size="small" />;
  if (hasWrite) return <Chip label="Editor" color="secondary" size="small" />;
  return <Chip label="Read-only" color="default" size="small" />;
};

const CampaignStatsBox: React.FC<{ campaign: Campaign }> = ({ campaign }) => (
  <Stack direction="row" spacing={2} alignItems="flex-start">
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        width: 40,
      }}
    >
      <CalendarIcon sx={{ fontSize: 40, color: 'text.secondary' }} />
    </Box>
    <Box
      sx={{
        flex: 1,
        p: 1.5,
        bgcolor: 'action.hover',
        borderRadius: 1,
      }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 500 }}>
        Current Campaign: {campaign.campaignName} {campaign.campaignYear}
      </Typography>
      <Stack direction="row" spacing={2}>
        <Box>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {campaign.totalOrders}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Orders
          </Typography>
        </Box>
        <Box>
          <Typography variant="body1" sx={{ fontWeight: 600, color: 'success.main' }}>
            ${(campaign?.totalRevenue ?? 0).toFixed(2)}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Sales
          </Typography>
        </Box>
      </Stack>
    </Box>
  </Stack>
);

const ProfileActions: React.FC<{
  profileId: string;
  isOwner: boolean;
  hasLatestCampaign: boolean;
  onViewLatest: () => void;
  onViewAll: () => void;
  onManage: () => void;
}> = ({ isOwner, hasLatestCampaign, onViewLatest, onViewAll, onManage }) => (
  <CardActions sx={{ pt: 0, flexDirection: 'column', gap: 1 }}>
    {hasLatestCampaign && (
      <Button fullWidth size="small" variant="contained" startIcon={<TrendingUpIcon />} onClick={onViewLatest}>
        View Latest Campaign
      </Button>
    )}
    <Button fullWidth size="small" variant="outlined" startIcon={<ViewIcon />} onClick={onViewAll}>
      View All Campaigns
    </Button>
    {isOwner && (
      <Button fullWidth size="small" variant="outlined" color="primary" startIcon={<SettingsIcon />} onClick={onManage}>
        Manage Scout
      </Button>
    )}
  </CardActions>
);

export const ProfileCard: React.FC<ProfileCardProps> = ({ profileId, sellerName, isOwner, permissions }) => {
  const navigate = useNavigate();

  // Fetch campaigns for latest campaign stats
  const { data: campaignsData, loading: campaignsLoading } = useQuery<{
    listCampaignsByProfile: Campaign[];
  }>(LIST_CAMPAIGNS_BY_PROFILE, {
    variables: { profileId: ensureProfileId(profileId) },
    skip: !profileId,
  });

  const campaigns = React.useMemo(() => campaignsData?.listCampaignsByProfile || [], [campaignsData]);

  // Get latest campaign by startDate
  const latestCampaign = React.useMemo(() => {
    if (!campaigns.length) return null;
    return [...campaigns].sort((a, b) => {
      const aTime = a.startDate ? new Date(a.startDate).getTime() : 0;
      const bTime = b.startDate ? new Date(b.startDate).getTime() : 0;
      return bTime - aTime;
    })[0];
  }, [campaigns]);

  const handleViewCampaigns = () => {
    navigate(`/scouts/${toUrlId(profileId)}/campaigns`);
  };

  const handleViewLatestCampaign = () => {
    if (latestCampaign) {
      navigate(`/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(latestCampaign.campaignId)}`);
    }
  };

  return (
    <Card elevation={2} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" spacing={2} alignItems="flex-start" mb={0.25}>
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            <PersonIcon color="primary" sx={{ fontSize: 40 }} />
          </Box>
          <Box flexGrow={1}>
            <Typography variant="h5" component="h3" sx={{ fontWeight: 600, mb: 0.5 }}>
              {sellerName}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
              <PermissionChip isOwner={isOwner} hasWrite={permissions.includes('WRITE')} />
            </Stack>
          </Box>
        </Stack>

        {/* Latest Campaign Stats */}
        {campaignsLoading ? (
          <CircularProgress size={20} sx={{ mt: 1 }} />
        ) : latestCampaign ? (
          <CampaignStatsBox campaign={latestCampaign} />
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            No campaigns yet
          </Typography>
        )}
      </CardContent>
      <ProfileActions
        profileId={profileId}
        isOwner={isOwner}
        hasLatestCampaign={Boolean(latestCampaign)}
        onViewLatest={handleViewLatestCampaign}
        onViewAll={handleViewCampaigns}
        onManage={() => navigate(`/scouts/${toUrlId(profileId)}/manage`)}
      />
    </Card>
  );
};
