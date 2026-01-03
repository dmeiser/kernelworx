/**
 * CampaignCard component - Display a single sales campaign
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toUrlId } from '../lib/ids';
import { Card, CardContent, CardActions, Typography, Button, Stack, Box, Chip } from '@mui/material';
import { ShoppingCart as OrdersIcon, AttachMoney as SalesIcon } from '@mui/icons-material';

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

const CampaignStatus: React.FC<{ isActive: boolean }> = ({ isActive }) =>
  isActive ? <Chip label="Active" color="success" size="small" /> : null;

const CampaignStats: React.FC<{
  totalOrders?: number;
  totalRevenue?: number;
}> = ({ totalOrders, totalRevenue }) => (
  <Stack spacing={1}>
    <StatRow
      icon={<OrdersIcon fontSize="small" color="action" />}
      label={`${totalOrders ?? 0} ${totalOrders === 1 ? 'order' : 'orders'}`}
    />
    <StatRow
      icon={<SalesIcon fontSize="small" color="action" />}
      label={`$${(totalRevenue ?? 0).toFixed(2)} in sales`}
    />
  </Stack>
);

const StatRow: React.FC<{ icon: React.ReactNode; label: string }> = ({ icon, label }) => (
  <Stack direction="row" spacing={1} alignItems="center">
    {icon}
    <Typography variant="body2">{label}</Typography>
  </Stack>
);

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
            <Stack direction="row" justifyContent="space-between" alignItems="start" mb={1}>
              <Typography variant="h6" component="h3">
                {campaignName} {campaignYear}
              </Typography>
              <CampaignStatus isActive={isActive} />
            </Stack>
          </Box>

          {/* Stats */}
          <CampaignStats totalOrders={totalOrders} totalRevenue={totalRevenue} />
        </Stack>
      </CardContent>
      <CardActions>
        <Button size="small" variant="outlined" onClick={handleViewCampaign} fullWidth>
          View Orders
        </Button>
      </CardActions>
    </Card>
  );
};
