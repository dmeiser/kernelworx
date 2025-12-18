/**
 * SeasonSummaryTiles - Summary statistics tiles for a season
 *
 * Displays key metrics:
 * - Total Orders
 * - Total Sales
 * - Unique Customers
 */

import React from "react";
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
import {
  ShoppingCart,
  AttachMoney,
  People,
  Inventory2,
} from "@mui/icons-material";
import { LIST_ORDERS_BY_SEASON } from "../lib/graphql";

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

interface SeasonSummaryTilesProps {
  seasonId: string;
}

export const SeasonSummaryTiles: React.FC<SeasonSummaryTilesProps> = ({
  seasonId,
}) => {
  const {
    data: ordersData,
    loading,
    error,
  } = useQuery<{ listOrdersBySeason: Order[] }>(LIST_ORDERS_BY_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  const orders = ordersData?.listOrdersBySeason || [];

  // Calculate statistics
  const totalOrders = orders.length;
  const totalRevenue = orders.reduce(
    (sum, order) => sum + order.totalAmount,
    0,
  );
  const uniqueCustomers = new Set(orders.map((order) => order.customerName))
    .size;
  const totalItemsSold = orders.reduce(
    (sum, order) =>
      sum +
      order.lineItems.reduce((itemSum, item) => itemSum + item.quantity, 0),
    0,
  );

  const formatCurrency = (amount: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(amount);

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="100px"
      >
        <CircularProgress size={40} />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">
        Failed to load summary statistics: {error.message}
      </Alert>
    );
  }

  return (
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

      <Grid size={{ xs: 12, sm: 6, md: 3 }}>
        <Paper sx={{ p: 3 }}>
          <Stack direction="row" spacing={2} alignItems="center">
            <Inventory2 color="primary" sx={{ fontSize: 40 }} />
            <Box>
              <Typography variant="h4">{totalItemsSold}</Typography>
              <Typography variant="body2" color="text.secondary">
                Items Sold
              </Typography>
            </Box>
          </Stack>
        </Paper>
      </Grid>
    </Grid>
  );
};
