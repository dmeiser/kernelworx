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
import {
  ensureProfileId,
  ensureCampaignId,
  ensureOrderId,
  toUrlId,
} from "../lib/ids";

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

// --- Helper Functions (extracted outside component) ---

const formatCurrency = (amount: number): string => {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
};

const formatPhoneNumber = (phone: string): string => {
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) {
    const areaCode = digits.slice(1, 4);
    const prefix = digits.slice(4, 7);
    const lineNumber = digits.slice(7, 11);
    return `(${areaCode}) ${prefix}-${lineNumber}`;
  }
  return phone;
};

const getPaymentMethodColor = (
  method: string,
): "default" | "primary" | "secondary" | "success" | "warning" => {
  const colors: Record<
    string,
    "default" | "primary" | "secondary" | "success" | "warning"
  > = {
    CASH: "success",
    CHECK: "primary",
    CREDIT_CARD: "secondary",
    OTHER: "default",
  };
  return colors[method] ?? "default";
};

const getTotalItems = (lineItems: LineItem[]): number => {
  return lineItems.reduce((sum, item) => sum + item.quantity, 0);
};

const checkWritePermission = (
  profile: ProfilePermissions | undefined,
): boolean => {
  if (!profile) return false;
  return profile.isOwner || (profile.permissions?.includes("WRITE") ?? false);
};

// --- Sub-Components ---

interface SummarySectionProps {
  summaryExpanded: boolean;
  onToggle: () => void;
  campaignId: string;
}

const SummarySection: React.FC<SummarySectionProps> = ({
  summaryExpanded,
  onToggle,
  campaignId,
}) => (
  <Box mb={3}>
    <Button
      onClick={onToggle}
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
);

interface OrdersHeaderProps {
  hasWritePermission: boolean;
  onCreateOrder: () => void;
}

const OrdersHeader: React.FC<OrdersHeaderProps> = ({
  hasWritePermission,
  onCreateOrder,
}) => (
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
        onClick={onCreateOrder}
      >
        New Order
      </Button>
    )}
  </Stack>
);

interface OrderRowProps {
  order: Order;
  hasWritePermission: boolean;
  onEdit: (orderId: string) => void;
  onDelete: (orderId: string) => void;
}

const OrderRow: React.FC<OrderRowProps> = ({
  order,
  hasWritePermission,
  onEdit,
  onDelete,
}) => (
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
        {order.customerPhone ? formatPhoneNumber(order.customerPhone) : "—"}
      </Typography>
    </TableCell>
    <TableCell>
      <Typography variant="body2">{getTotalItems(order.lineItems)}</Typography>
    </TableCell>
    <TableCell>
      <Chip
        label={order.paymentMethod.replace("_", " ")}
        size="small"
        color={getPaymentMethodColor(order.paymentMethod)}
      />
    </TableCell>
    <TableCell align="right">
      <Typography variant="body2" fontWeight="medium">
        {formatCurrency(order.totalAmount)}
      </Typography>
    </TableCell>
    {hasWritePermission && (
      <TableCell align="right">
        <Stack direction={{ xs: "column", sm: "row" }} spacing={0.5}>
          <IconButton
            size="small"
            onClick={() => onEdit(order.orderId)}
            color="primary"
          >
            <EditIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            onClick={() => onDelete(order.orderId)}
            color="error"
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>
      </TableCell>
    )}
  </TableRow>
);

interface OrdersTableProps {
  orders: Order[];
  hasWritePermission: boolean;
  onEdit: (orderId: string) => void;
  onDelete: (orderId: string) => void;
}

const OrdersTable: React.FC<OrdersTableProps> = ({
  orders,
  hasWritePermission,
  onEdit,
  onDelete,
}) => (
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
          {hasWritePermission && <TableCell align="right">Actions</TableCell>}
        </TableRow>
      </TableHead>
      <TableBody>
        {orders.map((order) => (
          <OrderRow
            key={order.orderId}
            order={order}
            hasWritePermission={hasWritePermission}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </TableBody>
    </Table>
  </TableContainer>
);

// --- URL Parameter Helpers ---

const decodeParam = (param: string | undefined): string => {
  return param ? decodeURIComponent(param) : "";
};

// --- Custom Hook for Orders Data ---

interface UseOrdersDataParams {
  profileId: string;
  campaignId: string;
}

const useOrdersData = ({ profileId, campaignId }: UseOrdersDataParams) => {
  const dbProfileId = ensureProfileId(profileId);
  const dbCampaignId = ensureCampaignId(campaignId);

  const { data: profileData } = useQuery<{ getProfile: ProfilePermissions }>(
    GET_PROFILE,
    {
      variables: { profileId: dbProfileId },
      skip: !dbProfileId,
    },
  );

  const {
    data: ordersData,
    loading: ordersLoading,
    error: ordersError,
    refetch: refetchOrders,
  } = useQuery<{ listOrdersByCampaign: Order[] }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  const [deleteOrder] = useMutation(DELETE_ORDER, {
    onCompleted: () => {
      refetchOrders();
    },
  });

  return {
    orders: ordersData?.listOrdersByCampaign ?? [],
    profile: profileData?.getProfile,
    loading: ordersLoading,
    error: ordersError,
    deleteOrder,
  };
};

// --- Main Component ---

interface OrdersContentProps {
  orders: Order[];
  hasWritePermission: boolean;
  summaryExpanded: boolean;
  onToggleSummary: () => void;
  campaignId: string;
  onCreateOrder: () => void;
  onEditOrder: (orderId: string) => void;
  onDeleteOrder: (orderId: string) => void;
}

const OrdersContent: React.FC<OrdersContentProps> = ({
  orders,
  hasWritePermission,
  summaryExpanded,
  onToggleSummary,
  campaignId,
  onCreateOrder,
  onEditOrder,
  onDeleteOrder,
}) => (
  <Box>
    <SummarySection
      summaryExpanded={summaryExpanded}
      onToggle={onToggleSummary}
      campaignId={campaignId}
    />
    <OrdersHeader
      hasWritePermission={hasWritePermission}
      onCreateOrder={onCreateOrder}
    />
    {orders.length > 0 ? (
      <OrdersTable
        orders={orders}
        hasWritePermission={hasWritePermission}
        onEdit={onEditOrder}
        onDelete={onDeleteOrder}
      />
    ) : (
      <Alert severity="info">
        No orders yet. Click "New Order" to add your first customer order!
      </Alert>
    )}
  </Box>
);

export const OrdersPage: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } =
    useParams<{
      profileId: string;
      campaignId: string;
    }>();
  const profileId = decodeParam(encodedProfileId);
  const campaignId = decodeParam(encodedCampaignId);
  const navigate = useNavigate();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  const [summaryExpanded, setSummaryExpanded] = React.useState(!isMobile);

  React.useEffect(() => {
    setSummaryExpanded(!isMobile);
  }, [isMobile]);

  const { orders, profile, loading, error, deleteOrder } = useOrdersData({
    profileId,
    campaignId,
  });

  const hasWritePermission = checkWritePermission(profile);

  const handleCreateOrder = () => {
    navigate(
      `/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(campaignId)}/orders/new`,
    );
  };

  const handleEditOrder = (orderId: string) => {
    navigate(
      `/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(campaignId)}/orders/${toUrlId(orderId)}/edit`,
    );
  };

  const handleDeleteOrder = async (orderId: string) => {
    if (confirm("Are you sure you want to delete this order?")) {
      await deleteOrder({ variables: { orderId: ensureOrderId(orderId) } });
    }
  };

  const handleToggleSummary = () => {
    setSummaryExpanded(!summaryExpanded);
  };

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
      <Alert severity="error">Failed to load orders: {error.message}</Alert>
    );
  }

  return (
    <OrdersContent
      orders={orders}
      hasWritePermission={hasWritePermission}
      summaryExpanded={summaryExpanded}
      onToggleSummary={handleToggleSummary}
      campaignId={campaignId}
      onCreateOrder={handleCreateOrder}
      onEditOrder={handleEditOrder}
      onDeleteOrder={handleDeleteOrder}
    />
  );
};
