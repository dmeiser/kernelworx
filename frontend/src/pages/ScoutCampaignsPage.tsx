/**
 * ScoutCampaignsPage - List all campaigns for a specific scout profile
 */

import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import {
  Typography,
  Box,
  Button,
  Grid,
  Alert,
  CircularProgress,
  Stack,
  IconButton,
  Breadcrumbs,
  Link,
  Divider,
} from '@mui/material';
import { Add as AddIcon, ArrowBack as ArrowBackIcon } from '@mui/icons-material';
import { CampaignCard } from '../components/CampaignCard';
import { GET_PROFILE, LIST_CAMPAIGNS_BY_PROFILE } from '../lib/graphql';
import { ensureProfileId } from '../lib/ids';
import type { Campaign, SellerProfile } from '../types';

// Use SellerProfile with only the fields we need
type Profile = Pick<SellerProfile, 'profileId' | 'sellerName' | 'isOwner' | 'permissions'>;

// --- Helper Functions ---

function getDecodedProfileId(encodedProfileId: string | undefined): string {
  return encodedProfileId ? decodeURIComponent(encodedProfileId) : '';
}

// Separate campaigns into active and inactive
function separateCampaigns(campaigns: Campaign[]): { active: Campaign[]; inactive: Campaign[] } {
  const active: Campaign[] = [];
  const inactive: Campaign[] = [];
  
  for (const campaign of campaigns) {
    if (campaign.isActive === false) {
      inactive.push(campaign);
    } else {
      active.push(campaign);
    }
  }
  
  return { active, inactive };
}

// eslint-disable-next-line complexity
function canEditProfile(profile: Profile | undefined): boolean {
  if (!profile) return false;
  return (profile.isOwner ?? false) || (profile.permissions?.includes('WRITE') ?? false);
}

// --- Sub-Components ---

const LoadingState: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
    <CircularProgress />
  </Box>
);

const ProfileNotFoundState: React.FC = () => (
  <Alert severity="error">Profile not found or you don't have access to this profile.</Alert>
);

interface PageBreadcrumbsProps {
  sellerName: string | undefined;
  onNavigateBack: () => void;
}

const PageBreadcrumbs: React.FC<PageBreadcrumbsProps> = ({ sellerName, onNavigateBack }) => (
  <Breadcrumbs sx={{ mb: 2 }}>
    <Link
      component="button"
      variant="body1"
      onClick={onNavigateBack}
      sx={{ textDecoration: 'none', cursor: 'pointer' }}
    >
      Profiles
    </Link>
    <Typography color="text.primary">{sellerName || 'Loading...'}</Typography>
  </Breadcrumbs>
);

interface PageHeaderProps {
  sellerName: string | undefined;
  canEdit: boolean;
  onNavigateBack: () => void;
  onCreateClick: () => void;
}

const PageHeader: React.FC<PageHeaderProps> = ({ sellerName, canEdit, onNavigateBack, onCreateClick }) => (
  <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
    <Stack direction="row" alignItems="center" spacing={2}>
      <IconButton onClick={onNavigateBack} edge="start">
        <ArrowBackIcon />
      </IconButton>
      <Box>
        <Typography variant="h4" component="h1">
          {sellerName}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Sales Campaigns
        </Typography>
      </Box>
    </Stack>
    {canEdit && (
      <Button variant="contained" startIcon={<AddIcon />} onClick={onCreateClick}>
        New Campaign
      </Button>
    )}
  </Stack>
);

interface ErrorAlertProps {
  error: ReturnType<typeof useQuery>['error'];
}

const ErrorAlert: React.FC<ErrorAlertProps> = ({ error }) => {
  if (!error) return null;
  return (
    <Alert severity="error" sx={{ mb: 3 }}>
      Failed to load campaigns: {error.message}
    </Alert>
  );
};

interface CampaignsGridProps {
  campaigns: Campaign[];
  profileId: string;
  sectionTitle?: string;
}

const CampaignsGrid: React.FC<CampaignsGridProps> = ({ campaigns, profileId, sectionTitle }) => {
  if (campaigns.length === 0) return null;
  return (
    <Box>
      {sectionTitle && (
        <Typography variant="h6" gutterBottom>
          {sectionTitle}
        </Typography>
      )}
      <Grid container spacing={2}>
        {campaigns.map((campaign) => (
          <Grid key={campaign.campaignId} size={{ xs: 12, sm: 6, md: 4 }}>
            <CampaignCard
              campaignId={campaign.campaignId}
              campaignName={campaign.campaignName}
              campaignYear={campaign.campaignYear}
              totalOrders={campaign.totalOrders}
              totalRevenue={campaign.totalRevenue}
              profileId={profileId}
            />
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

interface EmptyStateProps {
  canEdit: boolean;
  loading: boolean;
  campaignsCount: number;
}

const EmptyState: React.FC<EmptyStateProps> = ({ canEdit, loading, campaignsCount }) => {
  if (campaignsCount > 0 || loading) return null;
  const message = canEdit
    ? 'No sales campaigns yet. Click "New Campaign" to get started!'
    : 'No sales campaigns have been created for this profile yet.';
  return <Alert severity="info">{message}</Alert>;
};

// --- Custom Hooks for Data Fetching ---

function useProfileData(dbProfileId: string) {
  const { data, loading, error } = useQuery<{ getProfile: Profile }>(GET_PROFILE, {
    variables: { profileId: dbProfileId },
    skip: !dbProfileId,
  });
  return {
    profile: data?.getProfile,
    profileLoading: loading,
    profileError: error,
  };
}

function useCampaignsData(dbProfileId: string) {
  const { data, loading, error, refetch } = useQuery<{
    listCampaignsByProfile: Campaign[];
  }>(LIST_CAMPAIGNS_BY_PROFILE, {
    variables: { profileId: dbProfileId },
    skip: !dbProfileId,
  });
  return {
    campaigns: data?.listCampaignsByProfile || [],
    campaignsLoading: loading,
    campaignsError: error,
    refetchCampaigns: refetch,
  };
}

// --- Main Component ---

// --- Page Content Component ---

interface ScoutCampaignsContentProps {
  profile: Profile | undefined;
  profileId: string;
  campaigns: Campaign[];
  loading: boolean;
  error: ReturnType<typeof useQuery>['error'];
}

const ScoutCampaignsContent: React.FC<ScoutCampaignsContentProps> = ({
  profile,
  profileId,
  campaigns,
  loading,
  error,
}) => {
  const navigate = useNavigate();

  const canEdit = canEditProfile(profile);
  const handleNavigateBack = () => navigate('/scouts');
  const handleCreateClick = () => navigate('/create-campaign');
  
  const { active, inactive } = separateCampaigns(campaigns);
  const showDivider = active.length > 0 && inactive.length > 0;

  return (
    <Box>
      <PageBreadcrumbs sellerName={profile?.sellerName} onNavigateBack={handleNavigateBack} />
      <PageHeader
        sellerName={profile?.sellerName}
        canEdit={canEdit}
        onNavigateBack={handleNavigateBack}
        onCreateClick={handleCreateClick}
      />
      <ErrorAlert error={error} />
      <CampaignsGrid campaigns={active} profileId={profileId} sectionTitle={inactive.length > 0 ? "Active Campaigns" : undefined} />
      {showDivider && <Divider sx={{ my: 4 }} />}
      <CampaignsGrid campaigns={inactive} profileId={profileId} sectionTitle="Inactive Campaigns" />
      <EmptyState canEdit={canEdit} loading={loading} campaignsCount={campaigns.length} />
    </Box>
  );
};

// --- Combined Page Data Hook ---

interface ScoutCampaignsPageData {
  profile: Profile | undefined;
  campaigns: Campaign[];
  loading: boolean;
  error: ReturnType<typeof useQuery>['error'];
}

function useScoutCampaignsPageData(dbProfileId: string): ScoutCampaignsPageData {
  const { profile, profileLoading, profileError } = useProfileData(dbProfileId);
  const { campaigns, campaignsLoading, campaignsError } = useCampaignsData(dbProfileId);

  return {
    profile,
    campaigns,
    loading: profileLoading || campaignsLoading,
    error: profileError || campaignsError,
  };
}

// --- Early Return Helper ---

function shouldShowLoading(loading: boolean, profile: Profile | undefined): boolean {
  return loading && !profile;
}

function shouldShowNotFound(profileId: string, loading: boolean, profile: Profile | undefined): boolean {
  return !profileId || (!loading && !profile);
}

export const ScoutCampaignsPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{ profileId: string }>();
  const profileId = getDecodedProfileId(encodedProfileId);
  const dbProfileId = ensureProfileId(profileId);

  const { profile, campaigns, loading, error } = useScoutCampaignsPageData(dbProfileId ?? '');

  if (shouldShowLoading(loading, profile)) return <LoadingState />;
  if (shouldShowNotFound(profileId, loading, profile)) return <ProfileNotFoundState />;

  return (
    <ScoutCampaignsContent
      profile={profile}
      profileId={profileId}
      campaigns={campaigns}
      loading={loading}
      error={error}
    />
  );
};
