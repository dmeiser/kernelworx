/**
 * CampaignCard component - Display a single sales campaign
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { toUrlId } from "../lib/ids";
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
  ShoppingCart as OrdersIcon,
  AttachMoney as SalesIcon,
} from "@mui/icons-material";

interface CampaignCardProps {
  campaignId: string;
  profileId: string;
  campaignName: string;
  campaignYear: number;
  startDate?: string;
  endDate?: string;
  totalOrders?: number;
  totalRevenue?: number;
}

export const CampaignCard: React.FC<CampaignCardProps> = ({
  campaignId,
  profileId,
  campaignName,
  campaignYear,
  endDate,
  totalOrders,
  totalRevenue,
}) => {
  const navigate = useNavigate();

  const handleViewCampaign = () => {
    navigate(`/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(campaignId)}`);
  };

  const isActive = !endDate || new Date(endDate) >= new Date();

  return (
    <Card elevation={2}>
      <CardContent>
        <Stack spacing={2}>
          {/* Campaign Name & Status */}
          <Box>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="start"
              mb={1}
            >
              <Typography variant="h6" component="h3">
                {campaignName} {campaignYear}
              </Typography>
              {isActive && <Chip label="Active" color="success" size="small" />}
            </Stack>
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
          onClick={handleViewCampaign}
          fullWidth
        >
          View Orders
        </Button>
      </CardActions>
    </Card>
  );
};
