/**
 * OrdersPage - List and manage orders for a season
 */

import React, { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation } from "@apollo/client/react";
import {
  Box,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Stack,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Chip,
} from "@mui/material";
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
} from "@mui/icons-material";
import { OrderEditorDialog } from "../components/OrderEditorDialog";
import { SeasonSummaryTiles } from "../components/SeasonSummaryTiles";
import {
  LIST_ORDERS_BY_SEASON,
  DELETE_ORDER,
  GET_SEASON,
  GET_PROFILE,
} from "../lib/graphql";

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
  customerPhone?: string;
  orderDate: string;
  paymentMethod: string;
  lineItems: LineItem[];
  totalAmount: number;
  notes?: string;
}

interface Product {
  productId: string;
  productName: string;
  price: number;
}

export const OrdersPage: React.FC = () => {
  const { profileId: encodedProfileId, seasonId: encodedSeasonId } = useParams<{ profileId: string; seasonId: string }>();
  const profileId = encodedProfileId ? decodeURIComponent(encodedProfileId) : "";
  const seasonId = encodedSeasonId ? decodeURIComponent(encodedSeasonId) : "";
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingOrder, setEditingOrder] = useState<Order | null>(null);

  // Fetch profile (for permissions check)
  const { data: profileData } = useQuery<{ getProfile: any }>(GET_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Fetch season (for catalog/products)
  const { data: seasonData } = useQuery<{ getSeason: any }>(GET_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  // Fetch orders
  const {
    data: ordersData,
    loading: ordersLoading,
    error: ordersError,
    refetch: refetchOrders,
  } = useQuery<{ listOrdersBySeason: Order[] }>(LIST_ORDERS_BY_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  // Delete order mutation
  const [deleteOrder] = useMutation(DELETE_ORDER, {
    onCompleted: () => {
      refetchOrders();
    },
  });

  const orders = ordersData?.listOrdersBySeason || [];
  const products: Product[] = seasonData?.getSeason?.catalog?.products || [];
  const profile = profileData?.getProfile;
  const hasWritePermission = profile?.isOwner || profile?.permissions?.includes('WRITE');

  console.log("[OrdersPage] seasonId:", seasonId);
  console.log("[OrdersPage] getSeason:", seasonData?.getSeason);
  console.log("[OrdersPage] catalog:", seasonData?.getSeason?.catalog);
  console.log("[OrdersPage] products:", products);
  console.log("[OrdersPage] products.length:", products.length);

  const handleCreateOrder = () => {
    setEditingOrder(null);
    setEditorOpen(true);
  };

  const handleEditOrder = (order: Order) => {
    setEditingOrder(order);
    setEditorOpen(true);
  };

  const handleDeleteOrder = async (orderId: string) => {
    if (confirm("Are you sure you want to delete this order?")) {
      await deleteOrder({ variables: { orderId } });
    }
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(amount);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const formatPhoneNumber = (phone: string) => {
    // Format +1XXXXXXXXXX as (XXX) XXX-XXXX
    const digits = phone.replace(/\D/g, "");
    if (digits.length === 11 && digits.startsWith("1")) {
      const areaCode = digits.slice(1, 4);
      const prefix = digits.slice(4, 7);
      const lineNumber = digits.slice(7, 11);
      return `(${areaCode}) ${prefix}-${lineNumber}`;
    }
    return phone; // Return as-is if format is unexpected
  };

  const paymentMethodColors: Record<
    string,
    "default" | "primary" | "secondary" | "success" | "warning"
  > = {
    CASH: "success",
    CHECK: "primary",
    CREDIT_CARD: "secondary",
    OTHER: "default",
  };

  if (ordersLoading) {
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

  if (ordersError) {
    return (
      <Alert severity="error">
        Failed to load orders: {ordersError.message}
      </Alert>
    );
  }

  return (
    <Box>
      {/* Summary Tiles */}
      <SeasonSummaryTiles seasonId={seasonId} />

      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Typography variant="h5">Orders</Typography>
        {hasWritePermission && (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={handleCreateOrder}
          >
            New Order
          </Button>
        )}
      </Stack>

      {/* Orders Table */}
      {orders.length > 0 ? (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell>Phone</TableCell>
                <TableCell>Items</TableCell>
                <TableCell>Payment</TableCell>
                <TableCell align="right">Total</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {orders.map((order) => (
                <TableRow key={order.orderId} hover>
                  <TableCell>{formatDate(order.orderDate)}</TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight="medium">
                      {order.customerName}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {order.customerPhone
                        ? formatPhoneNumber(order.customerPhone)
                        : "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {order.lineItems.reduce(
                        (sum, item) => sum + item.quantity,
                        0,
                      )}{" "}
                      items
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={order.paymentMethod.replace("_", " ")}
                      size="small"
                      color={paymentMethodColors[order.paymentMethod]}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2" fontWeight="medium">
                      {formatCurrency(order.totalAmount)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {hasWritePermission && (
                      <>
                        <IconButton
                          size="small"
                          onClick={() => handleEditOrder(order)}
                          color="primary"
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          onClick={() => handleDeleteOrder(order.orderId)}
                          color="error"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Alert severity="info">
          No orders yet. Click "New Order" to add your first customer order!
        </Alert>
      )}

      {/* Order Editor Dialog */}
      <OrderEditorDialog
        open={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditingOrder(null);
        }}
        onComplete={() => {
          refetchOrders();
          setEditorOpen(false);
          setEditingOrder(null);
        }}
        order={editingOrder}
        seasonId={seasonId!}
        products={products}
      />
    </Box>
  );
};
