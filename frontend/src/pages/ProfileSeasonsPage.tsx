/**
 * ProfileSeasonsPage - List all seasons for a specific seller profile
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
import { SeasonCard } from "../components/SeasonCard";
import { CreateSeasonDialog } from "../components/CreateSeasonDialog";
import {
  GET_PROFILE,
  LIST_SEASONS_BY_PROFILE,
  CREATE_SEASON,
} from "../lib/graphql";

interface Season {
  seasonId: string;
  seasonName: string;
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

export const ProfileSeasonsPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{ profileId: string }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const navigate = useNavigate();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  // Fetch profile info
  const {
    data: profileData,
    loading: profileLoading,
    error: profileError,
  } = useQuery<{ getProfile: Profile }>(GET_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Fetch seasons
  const {
    data: seasonsData,
    loading: seasonsLoading,
    error: seasonsError,
    refetch: refetchSeasons,
  } = useQuery<{ listSeasonsByProfile: Season[] }>(LIST_SEASONS_BY_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Create season mutation
  const [createSeason] = useMutation(CREATE_SEASON, {
    onCompleted: () => {
      refetchSeasons();
    },
  });

  const handleCreateSeason = async (
    seasonName: string,
    startDate: string,
    endDate: string | null,
    catalogId: string,
  ) => {
    if (!profileId) return;

    // Convert YYYY-MM-DD to ISO 8601 datetime
    const startDateTime = new Date(startDate + "T00:00:00.000Z").toISOString();
    const endDateTime = endDate
      ? new Date(endDate + "T23:59:59.999Z").toISOString()
      : null;

    await createSeason({
      variables: {
        input: {
          profileId,
          seasonName,
          startDate: startDateTime,
          endDate: endDateTime,
          catalogId,
        },
      },
    });
  };

  const profile = profileData?.getProfile;
  const seasons = seasonsData?.listSeasonsByProfile || [];
  const loading = profileLoading || seasonsLoading;
  const error = profileError || seasonsError;

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
          onClick={() => navigate("/profiles")}
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
          <IconButton onClick={() => navigate("/profiles")} edge="start">
            <ArrowBackIcon />
          </IconButton>
          <Box>
            <Typography variant="h4" component="h1">
              {profile?.sellerName}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Sales Seasons
            </Typography>
          </Box>
        </Stack>
        {canEdit && (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setCreateDialogOpen(true)}
          >
            New Season
          </Button>
        )}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          Failed to load seasons: {error.message}
        </Alert>
      )}

      {/* Seasons Grid */}
      {seasons.length > 0 && (
        <Grid container spacing={2}>
          {seasons.map((season) => (
            <Grid key={season.seasonId} size={{ xs: 12, sm: 6, md: 4 }}>
              <SeasonCard
                seasonId={season.seasonId}
                seasonName={season.seasonName}
                startDate={season.startDate}
                endDate={season.endDate}
                totalOrders={season.totalOrders}
                totalRevenue={season.totalRevenue}
                profileId={profileId}
              />
            </Grid>
          ))}
        </Grid>
      )}

      {/* Empty State */}
      {seasons.length === 0 && !loading && (
        <Alert severity="info">
          {canEdit
            ? 'No sales seasons yet. Click "New Season" to get started!'
            : "No sales seasons have been created for this profile yet."}
        </Alert>
      )}

      {/* Create Season Dialog */}
      <CreateSeasonDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={handleCreateSeason}
      />
    </Box>
  );
};
