/**
 * CampaignSummaryPage - High-level statistics and summary for a campaign
 */

import React from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import {
  Box,
  Grid,
  Paper,
  Typography,
  Stack,
  CircularProgress,
  Alert,
} from "@mui/material";
import { ShoppingCart, AttachMoney, People } from "@mui/icons-material";
import { LIST_ORDERS_BY_CAMPAIGN } from "../lib/graphql";
import { ensureCampaignId } from "../lib/ids";

// Helper to safely decode URL component
const decodeUrlParam = (encoded: string | undefined): string =>
  encoded ? decodeURIComponent(encoded) : "";

// Helper to get orders from query data
const getOrders = (
  data: { listOrdersByCampaign: Order[] } | undefined,
): Order[] => data?.listOrdersByCampaign || [];

// Helper to calculate payment breakdown from orders
const calculatePaymentBreakdown = (orders: Order[]): Record<string, number> =>
  orders.reduce(
    (acc, order) => {
      acc[order.paymentMethod] = (acc[order.paymentMethod] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

// Helper to calculate product breakdown from orders
const calculateProductBreakdown = (
  orders: Order[],
): Record<string, { quantity: number; revenue: number }> =>
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
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);

interface LineItem {
  productId: string;
  productName: string;
  quantity: number;
  pricePerUnit: number;
  subtotal: number;
}

interface Order {
  orderId: string;
  customerName: string;
  paymentMethod: string;
  lineItems: LineItem[];
  totalAmount: number;
}

export const CampaignSummaryPage: React.FC = () => {
  const { campaignId: encodedCampaignId } = useParams<{ campaignId: string }>();
  const campaignId = decodeUrlParam(encodedCampaignId);
  const dbCampaignId = ensureCampaignId(campaignId);

  const {
    data: ordersData,
    loading,
    error,
  } = useQuery<{ listOrdersByCampaign: Order[] }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  const orders = getOrders(ordersData);

  // Calculate statistics
  const totalOrders = orders.length;
  const totalRevenue = orders.reduce(
    (sum, order) => sum + order.totalAmount,
    0,
  );
  const uniqueCustomers = new Set(orders.map((order) => order.customerName))
    .size;

  // Compute breakdowns using helpers
  const paymentBreakdown = calculatePaymentBreakdown(orders);
  const productBreakdown = calculateProductBreakdown(orders);
  const topProducts = getTopProducts(productBreakdown, 5);

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="200px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">Failed to load summary: {error.message}</Alert>
    );
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Campaign Summary
      </Typography>

      {/* Key Metrics */}
      <Grid container spacing={3} mb={4}>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Paper sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <ShoppingCart color="primary" sx={{ fontSize: 40 }} />
              <Box>
                <Typography variant="h4">{totalOrders}</Typography>
                <Typography variant="body2" color="text.secondary">
                  Total Orders
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Paper sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <AttachMoney color="success" sx={{ fontSize: 40 }} />
              <Box>
                <Typography variant="h4">
                  {formatCurrency(totalRevenue)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Total Sales
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Paper sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <People color="info" sx={{ fontSize: 40 }} />
              <Box>
                <Typography variant="h4">{uniqueCustomers}</Typography>
                <Typography variant="body2" color="text.secondary">
                  Unique Customers
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      {/* Payment Methods */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Payment Methods
        </Typography>
        <Grid container spacing={2}>
          {Object.entries(paymentBreakdown).map(([method, count]) => (
            <Grid key={method} size={{ xs: 6, sm: 4, md: 3 }}>
              <Box>
                <Typography variant="body1">
                  {method.replace("_", " ")}
                </Typography>
                <Typography variant="h6" color="primary">
                  {count} orders
                </Typography>
              </Box>
            </Grid>
          ))}
          {Object.keys(paymentBreakdown).length === 0 && (
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
            <Box key={productName}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
              >
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
