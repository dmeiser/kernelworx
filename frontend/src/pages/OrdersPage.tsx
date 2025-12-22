/**
 * OrdersPage - List and manage orders for a campaign
 */

import React from "react";
import { useParams, useNavigate } from "react-router-dom";
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
  Collapse,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
} from "@mui/icons-material";
import { CampaignSummaryTiles } from "../components/CampaignSummaryTiles";
import {
  LIST_ORDERS_BY_CAMPAIGN,
  DELETE_ORDER,
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

interface ProfilePermissions {
  profileId: string;
  isOwner: boolean;
  permissions?: string[];
}

export const OrdersPage: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } = useParams<{
    profileId: string;
    campaignId: string;
  }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const campaignId = encodedCampaignId ? decodeURIComponent(encodedCampaignId) : "";
  const navigate = useNavigate();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  // Summary collapse state - collapsed on mobile by default, expanded on desktop
  const [summaryExpanded, setSummaryExpanded] = React.useState(!isMobile);

  // Update when screen size changes
  React.useEffect(() => {
    setSummaryExpanded(!isMobile);
  }, [isMobile]);

  // Fetch profile (for permissions check)
  const { data: profileData } = useQuery<{ getProfile: ProfilePermissions }>(
    GET_PROFILE,
    {
      variables: { profileId },
      skip: !profileId,
    },
  );

  // Fetch orders
  const {
    data: ordersData,
    loading: ordersLoading,
    error: ordersError,
    refetch: refetchOrders,
  } = useQuery<{ listOrdersByCampaign: Order[] }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId },
    skip: !campaignId,
  });

  // Delete order mutation
  const [deleteOrder] = useMutation(DELETE_ORDER, {
    onCompleted: () => {
      refetchOrders();
    },
  });

  const orders = ordersData?.listOrdersByCampaign || [];
  const profile = profileData?.getProfile;
  const hasWritePermission =
    profile?.isOwner || profile?.permissions?.includes("WRITE");

  const handleCreateOrder = () => {
    navigate(
      `/scouts/${encodeURIComponent(profileId)}/campaigns/${encodeURIComponent(campaignId)}/orders/new`,
    );
  };

  const handleEditOrder = (orderId: string) => {
    navigate(
      `/scouts/${encodeURIComponent(profileId)}/campaigns/${encodeURIComponent(campaignId)}/orders/${encodeURIComponent(orderId)}/edit`,
    );
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
      {/* Summary Section with Collapse */}
      <Box mb={3}>
        <Button
          onClick={() => setSummaryExpanded(!summaryExpanded)}
          startIcon={summaryExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          sx={{ mb: 1 }}
          size="small"
        >
          {summaryExpanded ? "Hide Summary" : "Show Summary"}
        </Button>
        <Collapse in={summaryExpanded}>
          <Box mb={2}>
            <CampaignSummaryTiles campaignId={campaignId} />
          </Box>
        </Collapse>
      </Box>

      {/* Header */}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={2}
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
          <Table
            size="small"
            sx={{
              "& .MuiTableCell-root": {
                px: { xs: 1, sm: 2 },
                py: { xs: 0.75, sm: 1.5 },
              },
            }}
          >
            <TableHead>
              <TableRow>
                <TableCell sx={{ display: { xs: "none", sm: "table-cell" } }}>
                  Date
                </TableCell>
                <TableCell>Customer</TableCell>
                <TableCell sx={{ display: { xs: "none", md: "table-cell" } }}>
                  Phone
                </TableCell>
                <TableCell>Items</TableCell>
                <TableCell>Payment</TableCell>
                <TableCell align="right">Total</TableCell>
                {hasWritePermission && (
                  <TableCell align="right">Actions</TableCell>
                )}
              </TableRow>
            </TableHead>
            <TableBody>
              {orders.map((order) => (
                <TableRow key={order.orderId} hover>
                  <TableCell sx={{ display: { xs: "none", sm: "table-cell" } }}>
                    {formatDate(order.orderDate)}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight="medium">
                      {order.customerName}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ display: { xs: "none", md: "table-cell" } }}>
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
                      )}
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
                  {hasWritePermission && (
                    <TableCell align="right">
                      <Stack
                        direction={{ xs: "column", sm: "row" }}
                        spacing={0.5}
                      >
                        <IconButton
                          size="small"
                          onClick={() => handleEditOrder(order.orderId)}
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
                      </Stack>
                    </TableCell>
                  )}
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
    </Box>
  );
};
