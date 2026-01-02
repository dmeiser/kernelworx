/**
 * ScoutCampaignsPage - List all campaigns for a specific scout profile
 */

import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@apollo/client/react";
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

export const ScoutCampaignsPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{ profileId: string }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const dbProfileId = ensureProfileId(profileId);
  const navigate = useNavigate();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  // Fetch profile info
  const {
    data: profileData,
    loading: profileLoading,
    error: profileError,
  } = useQuery<{ getProfile: Profile }>(GET_PROFILE, {
    variables: { profileId: dbProfileId },
    skip: !dbProfileId,
  });

  // Fetch campaigns
  const {
    data: campaignsData,
    loading: campaignsLoading,
    error: campaignsError,
    refetch: refetchCampaigns,
  } = useQuery<{ listCampaignsByProfile: Campaign[] }>(
    LIST_CAMPAIGNS_BY_PROFILE,
    {
      variables: { profileId: dbProfileId },
      skip: !dbProfileId,
    },
  );

  // Create campaign mutation
  const [createCampaign] = useMutation(CREATE_CAMPAIGN, {
    onCompleted: () => {
      refetchCampaigns();
    },
  });

  const handleCreateCampaign = async (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => {
    if (!profileId) return;

    await createCampaign({
      variables: {
        input: {
          profileId: dbProfileId,
          campaignName,
          campaignYear,
          catalogId: ensureCatalogId(catalogId),
          ...(startDate && { startDate: new Date(startDate).toISOString() }),
          ...(endDate && { endDate: new Date(endDate).toISOString() }),
        },
      },
    });
  };

  const profile = profileData?.getProfile;
  const campaigns = campaignsData?.listCampaignsByProfile || [];
  const loading = profileLoading || campaignsLoading;
  const error = profileError || campaignsError;

  const canEdit = profile?.isOwner || profile?.permissions?.includes("WRITE");

  if (loading && !profile) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="400px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (!profileId || (!loading && !profile)) {
    return (
      <Alert severity="error">
        Profile not found or you don't have access to this profile.
      </Alert>
    );
  }

  return (
    <Box>
      {/* Breadcrumbs */}
      <Breadcrumbs sx={{ mb: 2 }}>
        <Link
          component="button"
          variant="body1"
          onClick={() => navigate("/scouts")}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Profiles
        </Link>
        <Typography color="text.primary">
          {profile?.sellerName || "Loading..."}
        </Typography>
      </Breadcrumbs>

      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Stack direction="row" alignItems="center" spacing={2}>
          <IconButton onClick={() => navigate("/scouts")} edge="start">
            <ArrowBackIcon />
          </IconButton>
          <Box>
            <Typography variant="h4" component="h1">
              {profile?.sellerName}
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
            onClick={() => setCreateDialogOpen(true)}
          >
            New Campaign
          </Button>
        )}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          Failed to load campaigns: {error.message}
        </Alert>
      )}

      {/* Campaigns Grid */}
      {campaigns.length > 0 && (
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
      )}

      {/* Empty State */}
      {campaigns.length === 0 && !loading && (
        <Alert severity="info">
          {canEdit
            ? 'No sales campaigns yet. Click "New Campaign" to get started!'
            : "No sales campaigns have been created for this profile yet."}
        </Alert>
      )}

      {/* Create Campaign Dialog */}
      <CreateCampaignDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={handleCreateCampaign}
      />
    </Box>
  );
};
