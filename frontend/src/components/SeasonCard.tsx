/**
 * SeasonCard component - Display a single sales season
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Stack,
  Box,
  Chip,
} from "@mui/material";
import {
  CalendarToday as CalendarIcon,
  ShoppingCart as OrdersIcon,
  AttachMoney as SalesIcon,
} from "@mui/icons-material";

interface SeasonCardProps {
  seasonId: string;
  profileId: string;
  seasonName: string;
  startDate: string;
  endDate?: string;
  totalOrders?: number;
  totalRevenue?: number;
}

export const SeasonCard: React.FC<SeasonCardProps> = ({
  seasonId,
  profileId,
  seasonName,
  startDate,
  endDate,
  totalOrders,
  totalRevenue,
}) => {
  const navigate = useNavigate();

  const handleViewSeason = () => {
    navigate(
      `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(seasonId)}`,
    );
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const isActive = !endDate || new Date(endDate) >= new Date();

  return (
    <Card elevation={2}>
      <CardContent>
        <Stack spacing={2}>
          {/* Season Name & Status */}
          <Box>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="start"
              mb={1}
            >
              <Typography variant="h6" component="h3">
                {seasonName}
              </Typography>
              {isActive && <Chip label="Active" color="success" size="small" />}
            </Stack>

            <Typography variant="body2" color="text.secondary">
              {formatDate(startDate)}
              {endDate && ` - ${formatDate(endDate)}`}
            </Typography>
          </Box>

          {/* Stats */}
          <Stack spacing={1}>
            <Stack direction="row" spacing={1} alignItems="center">
              <OrdersIcon fontSize="small" color="action" />
              <Typography variant="body2">
                {totalOrders ?? 0} {totalOrders === 1 ? "order" : "orders"}
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <SalesIcon fontSize="small" color="action" />
              <Typography variant="body2">
                ${(totalRevenue ?? 0).toFixed(2)} in sales
              </Typography>
            </Stack>
          </Stack>
        </Stack>
      </CardContent>
      <CardActions>
        <Button
          size="small"
          variant="outlined"
          onClick={handleViewSeason}
          fullWidth
        >
          View Orders
        </Button>
      </CardActions>
    </Card>
  );
};
