/**
 * ProfileCard component - Display a single scout profile with latest campaign
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardActions, Typography, Button, Chip, Stack, Box } from '@mui/material';
import {
  Person as PersonIcon,
  Visibility as ViewIcon,
  Settings as SettingsIcon,
  Campaign as CampaignIcon,
} from '@mui/icons-material';
import { toUrlId } from '../lib/ids';

interface ProfileCardProps {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
  latestCampaign?: {
    campaignId: string;
    campaignName: string;
    campaignYear: number;
    isActive: boolean;
  };
}

const PermissionChip: React.FC<{ isOwner: boolean; hasWrite: boolean }> = ({ isOwner, hasWrite }) => {
  if (isOwner) return <Chip label="Owner" color="primary" size="small" />;
  if (hasWrite) return <Chip label="Editor" color="secondary" size="small" />;
  return <Chip label="Read-only" color="default" size="small" />;
};

const ProfileActions: React.FC<{
  profileId: string;
  isOwner: boolean;
  latestCampaignId?: string;
  onViewAll: () => void;
  onManage: () => void;
  onViewLatest?: () => void;
}> = ({ isOwner, latestCampaignId, onViewAll, onManage, onViewLatest }) => (
  <CardActions sx={{ pt: 0, flexDirection: 'column', gap: 1 }}>
    {latestCampaignId && onViewLatest && (
      <Button fullWidth size="small" variant="contained" startIcon={<CampaignIcon />} onClick={onViewLatest}>
        View Latest Campaign
      </Button>
    )}
    <Button
      fullWidth
      size="small"
      variant={latestCampaignId ? 'outlined' : 'contained'}
      startIcon={<ViewIcon />}
      onClick={onViewAll}
    >
      View All Campaigns
    </Button>
    {isOwner && (
      <Button fullWidth size="small" variant="outlined" color="primary" startIcon={<SettingsIcon />} onClick={onManage}>
        Manage Scout
      </Button>
    )}
  </CardActions>
);

export const ProfileCard: React.FC<ProfileCardProps> = ({
  profileId,
  sellerName,
  isOwner,
  permissions,
  latestCampaign,
}) => {
  const navigate = useNavigate();

  const handleViewCampaigns = () => {
    navigate(`/scouts/${toUrlId(profileId)}/campaigns`);
  };

  const handleViewLatestCampaign = latestCampaign
    ? () => navigate(`/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(latestCampaign.campaignId)}`)
    : undefined;

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
            <Stack direction="row" spacing={1} flexWrap="wrap">
              <PermissionChip isOwner={isOwner} hasWrite={permissions.includes('WRITE')} />
            </Stack>
            {latestCampaign && (
              <Box mt={1.5}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Latest Campaign:
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {latestCampaign.campaignName} ({latestCampaign.campaignYear})
                </Typography>
              </Box>
            )}
          </Box>
        </Stack>
      </CardContent>
      <ProfileActions
        profileId={profileId}
        isOwner={isOwner}
        latestCampaignId={latestCampaign?.campaignId}
        onViewAll={handleViewCampaigns}
        onManage={() => navigate(`/scouts/${toUrlId(profileId)}/manage`)}
        onViewLatest={handleViewLatestCampaign}
      />
    </Card>
  );
};
