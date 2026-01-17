/**
 * ProfileCard component - Display a single scout profile
 *
 * Note: Campaign stats removed to improve performance. Users can click through to see campaigns.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardActions, Typography, Button, Chip, Stack, Box } from '@mui/material';
import {
  Person as PersonIcon,
  Visibility as ViewIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { toUrlId } from '../lib/ids';

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

const ProfileActions: React.FC<{
  profileId: string;
  isOwner: boolean;
  onViewAll: () => void;
  onManage: () => void;
}> = ({ isOwner, onViewAll, onManage }) => (
  <CardActions sx={{ pt: 0, flexDirection: 'column', gap: 1 }}>
    <Button fullWidth size="small" variant="contained" startIcon={<ViewIcon />} onClick={onViewAll}>
      View Campaigns
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

  const handleViewCampaigns = () => {
    navigate(`/scouts/${toUrlId(profileId)}/campaigns`);
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
            <Stack direction="row" spacing={1} flexWrap="wrap">
              <PermissionChip isOwner={isOwner} hasWrite={permissions.includes('WRITE')} />
            </Stack>
          </Box>
        </Stack>
      </CardContent>
      <ProfileActions
        profileId={profileId}
        isOwner={isOwner}
        onViewAll={handleViewCampaigns}
        onManage={() => navigate(`/scouts/${toUrlId(profileId)}/manage`)}
      />
    </Card>
  );
};
