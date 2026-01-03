/**
 * ScoutCampaignsPage - List all campaigns for a specific scout profile
 */

import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, ApolloError } from "@apollo/client/react";
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
} from "@mui/material";
import {
  Add as AddIcon,
  ArrowBack as ArrowBackIcon,
} from "@mui/icons-material";
import { CampaignCard } from "../components/CampaignCard";
import { CreateCampaignDialog } from "../components/CreateCampaignDialog";
import {
  GET_PROFILE,
  LIST_CAMPAIGNS_BY_PROFILE,
  CREATE_CAMPAIGN,
} from "../lib/graphql";
import { ensureProfileId, ensureCatalogId } from "../lib/ids";

interface Campaign {
  campaignId: string;
  campaignName: string;
  campaignYear: number;
  startDate: string;
  endDate?: string;
  catalogId: string;
  totalOrders?: number;
  totalRevenue?: number;
}

interface Profile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

// --- Helper Functions ---

function getDecodedProfileId(encodedProfileId: string | undefined): string {
  return encodedProfileId ? decodeURIComponent(encodedProfileId) : "";
}

function canEditProfile(profile: Profile | undefined): boolean {
  if (!profile) return false;
  return profile.isOwner || profile.permissions?.includes("WRITE");
}

// --- Sub-Components ---

const LoadingState: React.FC = () => (
  <Box
    display="flex"
    justifyContent="center"
    alignItems="center"
    minHeight="400px"
  >
    <CircularProgress />
  </Box>
);

const ProfileNotFoundState: React.FC = () => (
  <Alert severity="error">
    Profile not found or you don't have access to this profile.
  </Alert>
);

interface PageBreadcrumbsProps {
  sellerName: string | undefined;
  onNavigateBack: () => void;
}

const PageBreadcrumbs: React.FC<PageBreadcrumbsProps> = ({
  sellerName,
  onNavigateBack,
}) => (
  <Breadcrumbs sx={{ mb: 2 }}>
    <Link
      component="button"
      variant="body1"
      onClick={onNavigateBack}
      sx={{ textDecoration: "none", cursor: "pointer" }}
    >
      Profiles
    </Link>
    <Typography color="text.primary">{sellerName || "Loading..."}</Typography>
  </Breadcrumbs>
);

interface PageHeaderProps {
  sellerName: string | undefined;
  canEdit: boolean;
  onNavigateBack: () => void;
  onCreateClick: () => void;
}

const PageHeader: React.FC<PageHeaderProps> = ({
  sellerName,
  canEdit,
  onNavigateBack,
  onCreateClick,
}) => (
  <Stack
    direction="row"
    justifyContent="space-between"
    alignItems="center"
    mb={3}
  >
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
      <Button
        variant="contained"
        startIcon={<AddIcon />}
        onClick={onCreateClick}
      >
        New Campaign
      </Button>
    )}
  </Stack>
);

interface ErrorAlertProps {
  error: ApolloError | undefined;
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
}

const CampaignsGrid: React.FC<CampaignsGridProps> = ({
  campaigns,
  profileId,
}) => {
  if (campaigns.length === 0) return null;
  return (
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
  );
};

interface EmptyStateProps {
  canEdit: boolean;
  loading: boolean;
  campaignsCount: number;
}

const EmptyState: React.FC<EmptyStateProps> = ({
  canEdit,
  loading,
  campaignsCount,
}) => {
  if (campaignsCount > 0 || loading) return null;
  const message = canEdit
    ? 'No sales campaigns yet. Click "New Campaign" to get started!'
    : "No sales campaigns have been created for this profile yet.";
  return <Alert severity="info">{message}</Alert>;
};

// --- Custom Hooks for Data Fetching ---

function useProfileData(dbProfileId: string) {
  const { data, loading, error } = useQuery<{ getProfile: Profile }>(
    GET_PROFILE,
    {
      variables: { profileId: dbProfileId },
      skip: !dbProfileId,
    },
  );
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

// --- Helper for building campaign input ---

function buildCampaignInput(
  dbProfileId: string,
  campaignName: string,
  campaignYear: number,
  catalogId: string,
  startDate?: string,
  endDate?: string,
) {
  const input: Record<string, unknown> = {
    profileId: dbProfileId,
    campaignName,
    campaignYear,
    catalogId: ensureCatalogId(catalogId),
  };
  if (startDate) input.startDate = new Date(startDate).toISOString();
  if (endDate) input.endDate = new Date(endDate).toISOString();
  return input;
}

// --- Create Campaign Handler Hook ---

type MutationFn = ReturnType<typeof useMutation>[0];

function useCreateCampaignHandler(
  profileId: string,
  dbProfileId: string,
  createCampaign: MutationFn,
) {
  return async (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => {
    if (!profileId) return;
    const input = buildCampaignInput(
      dbProfileId,
      campaignName,
      campaignYear,
      catalogId,
      startDate,
      endDate,
    );
    await createCampaign({ variables: { input } });
  };
}

// --- Page Content Component ---

interface ScoutCampaignsContentProps {
  profile: Profile | undefined;
  profileId: string;
  campaigns: Campaign[];
  loading: boolean;
  error: ApolloError | undefined;
  onCreateCampaign: (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => Promise<void>;
}

const ScoutCampaignsContent: React.FC<ScoutCampaignsContentProps> = ({
  profile,
  profileId,
  campaigns,
  loading,
  error,
  onCreateCampaign,
}) => {
  const navigate = useNavigate();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const canEdit = canEditProfile(profile);
  const handleNavigateBack = () => navigate("/scouts");

  return (
    <Box>
      <PageBreadcrumbs
        sellerName={profile?.sellerName}
        onNavigateBack={handleNavigateBack}
      />
      <PageHeader
        sellerName={profile?.sellerName}
        canEdit={canEdit}
        onNavigateBack={handleNavigateBack}
        onCreateClick={() => setCreateDialogOpen(true)}
      />
      <ErrorAlert error={error} />
      <CampaignsGrid campaigns={campaigns} profileId={profileId} />
      <EmptyState
        canEdit={canEdit}
        loading={loading}
        campaignsCount={campaigns.length}
      />
      <CreateCampaignDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={onCreateCampaign}
      />
    </Box>
  );
};

// --- Combined Page Data Hook ---

interface ScoutCampaignsPageData {
  profile: Profile | undefined;
  campaigns: Campaign[];
  loading: boolean;
  error: ApolloError | undefined;
  handleCreateCampaign: (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => Promise<void>;
}

function useScoutCampaignsPageData(
  profileId: string,
  dbProfileId: string,
): ScoutCampaignsPageData {
  const { profile, profileLoading, profileError } = useProfileData(dbProfileId);
  const { campaigns, campaignsLoading, campaignsError, refetchCampaigns } =
    useCampaignsData(dbProfileId);

  const [createCampaign] = useMutation(CREATE_CAMPAIGN, {
    onCompleted: () => refetchCampaigns(),
  });

  const handleCreateCampaign = useCreateCampaignHandler(
    profileId,
    dbProfileId,
    createCampaign,
  );

  return {
    profile,
    campaigns,
    loading: profileLoading || campaignsLoading,
    error: profileError || campaignsError,
    handleCreateCampaign,
  };
}

// --- Early Return Helper ---

function shouldShowLoading(
  loading: boolean,
  profile: Profile | undefined,
): boolean {
  return loading && !profile;
}

function shouldShowNotFound(
  profileId: string,
  loading: boolean,
  profile: Profile | undefined,
): boolean {
  return !profileId || (!loading && !profile);
}

export const ScoutCampaignsPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{ profileId: string }>();
  const profileId = getDecodedProfileId(encodedProfileId);
  const dbProfileId = ensureProfileId(profileId);

  const { profile, campaigns, loading, error, handleCreateCampaign } =
    useScoutCampaignsPageData(profileId, dbProfileId);

  if (shouldShowLoading(loading, profile)) return <LoadingState />;
  if (shouldShowNotFound(profileId, loading, profile))
    return <ProfileNotFoundState />;

  return (
    <ScoutCampaignsContent
      profile={profile}
      profileId={profileId}
      campaigns={campaigns}
      loading={loading}
      error={error}
      onCreateCampaign={handleCreateCampaign}
    />
  );
};
