/**
 * CampaignSummaryPage - High-level statistics and summary for a campaign
 */

import React from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Box, Grid, Paper, Typography, Stack } from '@mui/material';
import { ShoppingCart, AttachMoney, People } from '@mui/icons-material';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { LIST_ORDERS_BY_CAMPAIGN, GET_PAYMENT_METHODS_FOR_PROFILE } from '../lib/graphql';
import { ensureCampaignId, ensureProfileId } from '../lib/ids';
import type { Order } from '../types';
import type { GqlPaymentMethod } from '../types/graphql-generated';

// Helper to safely decode URL component
const decodeUrlParam = (encoded: string | undefined): string => (encoded ? decodeURIComponent(encoded) : '');

// Helper to get orders from query data
const getOrders = (data: { listOrdersByCampaign: Order[] } | undefined): Order[] => data?.listOrdersByCampaign || [];

// Helper to get active payment method names (lowercase for comparison)
const getActiveMethodNames = (methods: GqlPaymentMethod[]): Set<string> =>
  new Set(methods.map((m) => m.name.toLowerCase()));

// Helper to calculate payment totals (dollar amounts) from orders
interface PaymentTotal {
  amount: number;
  orderCount: number;
  isActive: boolean;
}

const calculatePaymentTotals = (orders: Order[], activeMethodNames: Set<string>): Record<string, PaymentTotal> =>
  orders.reduce(
    (acc, order) => {
      const methodName = order.paymentMethod;
      if (!acc[methodName]) {
        acc[methodName] = {
          amount: 0,
          orderCount: 0,
          isActive: activeMethodNames.has(methodName.toLowerCase()),
        };
      }
      acc[methodName].amount += order.totalAmount;
      acc[methodName].orderCount += 1;
      return acc;
    },
    {} as Record<string, PaymentTotal>,
  );

// Helper to sort payment totals alphabetically
const getSortedPaymentTotals = (totals: Record<string, PaymentTotal>): [string, PaymentTotal][] =>
  Object.entries(totals).sort((a, b) => a[0].toLowerCase().localeCompare(b[0].toLowerCase()));

// Helper to calculate product breakdown from orders
const calculateProductBreakdown = (orders: Order[]): Record<string, { quantity: number; revenue: number }> =>
  orders.reduce(
    (acc, order) => {
      order.lineItems.forEach((item) => {
        if (!acc[item.productName]) {
          acc[item.productName] = { quantity: 0, revenue: 0 };
        }
        acc[item.productName].quantity += item.quantity;
        acc[item.productName].revenue += item.subtotal;
      });
      return acc;
    },
    {} as Record<string, { quantity: number; revenue: number }>,
  );

// Helper to get top products sorted by revenue
const getTopProducts = (
  productBreakdown: Record<string, { quantity: number; revenue: number }>,
  limit: number,
): [string, { quantity: number; revenue: number }][] =>
  Object.entries(productBreakdown)
    .sort((a, b) => b[1].revenue - a[1].revenue)
    .slice(0, limit);

// Helper to format currency
const formatCurrency = (amount: number): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount);

// --- Sub-Components ---

interface MetricCardProps {
  icon: React.ReactNode;
  value: string | number;
  label: string;
}

const MetricCard: React.FC<MetricCardProps> = ({ icon, value, label }) => (
  <Paper sx={{ p: 3 }}>
    <Stack direction="row" spacing={2} alignItems="center">
      {icon}
      <Box>
        <Typography variant="h4">{value}</Typography>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
      </Box>
    </Stack>
  </Paper>
);

interface PaymentMethodItemProps {
  method: string;
  totals: PaymentTotal;
}

const PaymentMethodItem: React.FC<PaymentMethodItemProps> = ({ method, totals }) => (
  <Box>
    <Typography variant="body1">
      {method}
      {!totals.isActive && (
        <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          (inactive)
        </Typography>
      )}
    </Typography>
    <Typography variant="h6" color="primary">
      {formatCurrency(totals.amount)}
    </Typography>
    <Typography variant="body2" color="text.secondary">
      {totals.orderCount} {totals.orderCount === 1 ? 'order' : 'orders'}
    </Typography>
  </Box>
);

interface TopProductItemProps {
  productName: string;
  stats: { quantity: number; revenue: number };
}

const TopProductItem: React.FC<TopProductItemProps> = ({ productName, stats }) => (
  <Box>
    <Stack direction="row" justifyContent="space-between" alignItems="center">
      <Typography variant="body1">{productName}</Typography>
      <Stack direction="row" spacing={3} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          {stats.quantity} sold
        </Typography>
        <Typography variant="body1" fontWeight="medium">
          {formatCurrency(stats.revenue)}
        </Typography>
      </Stack>
    </Stack>
  </Box>
);

// --- Custom Hook ---

function useCampaignSummaryData(dbCampaignId: string | null, dbProfileId: string | null) {
  const {
    data: ordersData,
    loading: ordersLoading,
    error: ordersError,
  } = useQuery<{ listOrdersByCampaign: Order[] }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  const { data: paymentMethodsData, loading: paymentMethodsLoading } = useQuery<{
    paymentMethodsForProfile: GqlPaymentMethod[];
  }>(GET_PAYMENT_METHODS_FOR_PROFILE, {
    variables: { profileId: dbProfileId },
    skip: !dbProfileId,
  });

  const orders = getOrders(ordersData);
  const paymentMethods = paymentMethodsData?.paymentMethodsForProfile ?? [];
  const activeMethodNames = getActiveMethodNames(paymentMethods);

  return {
    orders,
    activeMethodNames,
    loading: ordersLoading || paymentMethodsLoading,
    error: ordersError,
  };
}

// --- Main Component ---

export const CampaignSummaryPage: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } = useParams<{
    profileId: string;
    campaignId: string;
  }>();
  const profileId = decodeUrlParam(encodedProfileId);
  const campaignId = decodeUrlParam(encodedCampaignId);
  const dbProfileId = ensureProfileId(profileId);
  const dbCampaignId = ensureCampaignId(campaignId);

  const { orders, activeMethodNames, loading, error } = useCampaignSummaryData(dbCampaignId, dbProfileId);

  // Calculate statistics
  const totalOrders = orders.length;
  const totalRevenue = orders.reduce((sum, order) => sum + order.totalAmount, 0);
  const uniqueCustomers = new Set(orders.map((order) => order.customerName)).size;

  // Compute breakdowns using helpers
  const paymentTotals = calculatePaymentTotals(orders, activeMethodNames);
  const sortedPaymentTotals = getSortedPaymentTotals(paymentTotals);
  const productBreakdown = calculateProductBreakdown(orders);
  const topProducts = getTopProducts(productBreakdown, 5);

  if (loading) {
    return <LoadingState minHeight="200px" />;
  }

  if (error) {
    return <ErrorAlert message={`Failed to load summary: ${error.message}`} />;
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Campaign Summary
      </Typography>

      {/* Key Metrics */}
      <Grid container spacing={3} mb={4}>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <MetricCard
            icon={<ShoppingCart color="primary" sx={{ fontSize: 40 }} />}
            value={totalOrders}
            label="Total Orders"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <MetricCard
            icon={<AttachMoney color="success" sx={{ fontSize: 40 }} />}
            value={formatCurrency(totalRevenue)}
            label="Total Sales"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <MetricCard
            icon={<People color="info" sx={{ fontSize: 40 }} />}
            value={uniqueCustomers}
            label="Unique Customers"
          />
        </Grid>
      </Grid>

      {/* Payment Methods */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Payment Methods
        </Typography>
        <Grid container spacing={2}>
          {sortedPaymentTotals.map(([method, totals]) => (
            <Grid key={method} size={{ xs: 6, sm: 4, md: 3 }}>
              <PaymentMethodItem method={method} totals={totals} />
            </Grid>
          ))}
          {sortedPaymentTotals.length === 0 && (
            <Grid size={{ xs: 12 }}>
              <Typography variant="body2" color="text.secondary">
                No orders yet
              </Typography>
            </Grid>
          )}
        </Grid>
      </Paper>

      {/* Top Products */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          Top Products
        </Typography>
        <Stack spacing={2}>
          {topProducts.map(([productName, stats]) => (
            <TopProductItem key={productName} productName={productName} stats={stats} />
          ))}
          {topProducts.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              No product sales yet
            </Typography>
          )}
        </Stack>
      </Paper>
    </Box>
  );
};
