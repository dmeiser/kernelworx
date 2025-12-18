/**
 * ProfileCard component - Display a single seller profile with latest season stats
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import {
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Chip,
  Stack,
  Box,
  CircularProgress,
} from "@mui/material";
import {
  Person as PersonIcon,
  Visibility as ViewIcon,
  Settings as SettingsIcon,
  TrendingUp as TrendingUpIcon,
  CalendarToday as CalendarIcon,
} from "@mui/icons-material";
import { LIST_SEASONS_BY_PROFILE } from "../lib/graphql";

interface Season {
  seasonId: string;
  seasonName: string;
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

export const ProfileCard: React.FC<ProfileCardProps> = ({
  profileId,
  sellerName,
  isOwner,
  permissions,
}) => {
  const navigate = useNavigate();

  // Fetch seasons for latest season stats
  const { data: seasonsData, loading: seasonsLoading } = useQuery<{
    listSeasonsByProfile: Season[];
  }>(LIST_SEASONS_BY_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  const seasons = seasonsData?.listSeasonsByProfile || [];
  // Get latest season by startDate
  const latestSeason =
    seasons.length > 0
      ? [...seasons].sort(
          (a, b) =>
            new Date(b.startDate).getTime() - new Date(a.startDate).getTime(),
        )[0]
      : null;

  const handleViewSeasons = () => {
    navigate(`/profiles/${encodeURIComponent(profileId)}/seasons`);
  };

  const handleViewLatestSeason = () => {
    if (latestSeason) {
      navigate(
        `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(
          latestSeason.seasonId,
        )}`,
      );
    }
  };

  return (
    <Card
      elevation={2}
      sx={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" spacing={2} alignItems="flex-start" mb={0.25}>
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
            }}
          >
            <PersonIcon color="primary" sx={{ fontSize: 40 }} />
          </Box>
          <Box flexGrow={1}>
            <Typography
              variant="h5"
              component="h3"
              sx={{ fontWeight: 600, mb: 0.5 }}
            >
              {sellerName}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
              {isOwner && <Chip label="Owner" color="primary" size="small" />}
              {!isOwner && permissions.includes("WRITE") && (
                <Chip label="Editor" color="secondary" size="small" />
              )}
              {!isOwner && !permissions.includes("WRITE") && (
                <Chip label="Viewer" color="default" size="small" />
              )}
            </Stack>
          </Box>
        </Stack>

        {/* Latest Season Stats */}
        {seasonsLoading ? (
          <CircularProgress size={20} sx={{ mt: 1 }} />
        ) : latestSeason ? (
          <Stack direction="row" spacing={2} alignItems="flex-start">
            <Box
              sx={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                width: 40,
              }}
            >
              {latestSeason && (
                <CalendarIcon sx={{ fontSize: 40, color: "text.secondary" }} />
              )}
            </Box>
            <Box
              sx={{
                flex: 1,
                p: 1.5,
                bgcolor: "action.hover",
                borderRadius: 1,
              }}
            >
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ display: "block", mb: 1, fontWeight: 500 }}
              >
                Current Season: {latestSeason.seasonName}
              </Typography>
              <Stack direction="row" spacing={2}>
                <Box>
                  <Typography variant="body1" sx={{ fontWeight: 600 }}>
                    {latestSeason.totalOrders}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Orders
                  </Typography>
                </Box>
                <Box>
                  <Typography
                    variant="body1"
                    sx={{ fontWeight: 600, color: "success.main" }}
                  >
                    ${(latestSeason?.totalRevenue ?? 0).toFixed(2)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Sales
                  </Typography>
                </Box>
              </Stack>
            </Box>
          </Stack>
        ) : (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: "block", mt: 1 }}
          >
            No seasons yet
          </Typography>
        )}
      </CardContent>
      <CardActions sx={{ pt: 0, flexDirection: "column", gap: 1 }}>
        {latestSeason && (
          <Button
            fullWidth
            size="small"
            variant="contained"
            startIcon={<TrendingUpIcon />}
            onClick={handleViewLatestSeason}
          >
            View Latest Season
          </Button>
        )}
        <Button
          fullWidth
          size="small"
          variant="outlined"
          startIcon={<ViewIcon />}
          onClick={handleViewSeasons}
        >
          View All Seasons
        </Button>
        {isOwner && (
          <Button
            fullWidth
            size="small"
            variant="outlined"
            color="primary"
            startIcon={<SettingsIcon />}
            onClick={() =>
              navigate(`/profiles/${encodeURIComponent(profileId)}/manage`)
            }
          >
            Manage Seller Profile
          </Button>
        )}
      </CardActions>
    </Card>
  );
};
