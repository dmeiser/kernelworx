/**
 * ReportsPage - Generate and download campaign reports
 */

import React from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import {
  Box,
  Typography,
  Paper,
  Stack,
  Button,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import {
  Download as DownloadIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
} from "@mui/icons-material";
import { LIST_ORDERS_BY_CAMPAIGN } from "../lib/graphql";
import { ensureCampaignId } from "../lib/ids";
import { downloadAsCSV, downloadAsXLSX } from "../lib/reportExport";

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
  customerAddress?: {
    street?: string;
    city?: string;
    state?: string;
    zipCode?: string;
  };
  paymentMethod: string;
  lineItems: LineItem[];
  totalAmount: number;
}

export const ReportsPage: React.FC = () => {
  const { campaignId: encodedCampaignId } = useParams<{ campaignId: string }>();
  const campaignId = encodedCampaignId
    ? decodeURIComponent(encodedCampaignId)
    : "";
  const dbCampaignId = ensureCampaignId(campaignId);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  // About Reports collapse state - collapsed on mobile by default, expanded on desktop
  const [aboutExpanded, setAboutExpanded] = React.useState(!isMobile);

  // Update when screen size changes
  React.useEffect(() => {
    setAboutExpanded(!isMobile);
  }, [isMobile]);

  // Report format option (currently defaults to XLSX)
  const reportFormat: "CSV" | "XLSX" = "XLSX";
  void reportFormat; // Used for future report format selection

  const { data: ordersData, loading: ordersLoading } = useQuery<{
    listOrdersByCampaign: Order[];
  }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  const orders = ordersData?.listOrdersByCampaign || [];

  const formatCurrency = (amount: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(amount);

  const formatPhone = (phone?: string) => {
    if (!phone) return "-";
    // Remove all non-digit characters
    const digits = phone.replace(/\D/g, "");
    // Format as (XXX) XXX-XXXX for 10 digits (US format)
    if (digits.length === 10) {
      return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
    }
    // Format as (XXX) XXX-XXXX for 11 digits (with 1 country code, just use last 10)
    if (digits.length === 11) {
      const last10 = digits.slice(-10);
      return `(${last10.slice(0, 3)}) ${last10.slice(3, 6)}-${last10.slice(6)}`;
    }
    // Return original if can't format standardly
    return phone;
  };

  return (
    <Box sx={{ width: "100%" }}>
      <Typography variant="h5" gutterBottom>
        Reports & Exports
      </Typography>

      {/* Report Info - Always Visible */}
      <Paper
        sx={{
          p: { xs: 1, sm: 3 },
          mb: 3,
        }}
      >
        <Typography variant="h6" gutterBottom>
          About Reports
        </Typography>
        <Box
          component="ul"
          sx={{
            m: 0,
            pl: { xs: 2.5, sm: 3 },
            "& li": {
              typography: "body2",
              mb: 1,
            },
          }}
        >
          <li>
            <strong>Excel (XLSX):</strong> Formatted spreadsheet with product
            columns, suitable for further analysis and pivot tables.
          </li>
          <li>
            <strong>CSV:</strong> Plain text file, compatible with all
            spreadsheet programs and databases.
          </li>
        </Box>
      </Paper>

      {/* Mobile Warning */}
      {isMobile && (
        <Box
          mb={3}
          sx={{
            p: { xs: 1, sm: 2 },
            bgcolor: "#e3f2fd",
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" sx={{ color: "#1976d2" }}>
            💡 <strong>Note:</strong> The order table below is designed for
            desktop viewing. For the best experience viewing and editing
            detailed order data, please use a larger screen.
          </Typography>
        </Box>
      )}

      {/* Complete Order Table - Collapsible */}
      <Box mb={3}>
        <Button
          onClick={() => setAboutExpanded(!aboutExpanded)}
          startIcon={aboutExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          sx={{ mb: 1 }}
          size="small"
        >
          {aboutExpanded ? "Hide Order Table" : "Show Order Table"}
        </Button>
        {aboutExpanded && (
          <Box sx={{ width: "100%", overflowX: "auto" }}>
            {/* Complete Order Table */}
            <Paper sx={{ p: { xs: 1.5, sm: 3 }, mt: 3 }}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                mb={2}
              >
                <Typography variant="h6">All Orders</Typography>
                {orders.length > 0 && (
                  <Stack direction="row" spacing={1}>
                    <Button
                      size="small"
                      startIcon={<DownloadIcon />}
                      onClick={() => downloadAsCSV(orders, campaignId)}
                      variant="outlined"
                    >
                      CSV
                    </Button>
                    <Button
                      size="small"
                      startIcon={<DownloadIcon />}
                      onClick={() => downloadAsXLSX(orders, campaignId)}
                      variant="outlined"
                    >
                      XLSX
                    </Button>
                  </Stack>
                )}
              </Stack>

              {ordersLoading ? (
                <Box display="flex" justifyContent="center" py={4}>
                  <CircularProgress />
                </Box>
              ) : orders.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No orders found for this campaign.
                </Typography>
              ) : (
                (() => {
                  // Get all unique products
                  const allProducts = Array.from(
                    new Set(
                      orders.flatMap((order) =>
                        order.lineItems.map((item) => item.productName),
                      ),
                    ),
                  ).sort();

                  return (
                    <TableContainer sx={{ overflowX: "auto" }}>
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ bgcolor: "action.hover" }}>
                            <TableCell>
                              <strong>Name</strong>
                            </TableCell>
                            <TableCell>
                              <strong>Phone</strong>
                            </TableCell>
                            <TableCell>
                              <strong>Address</strong>
                            </TableCell>
                            {allProducts.map((product) => (
                              <TableCell key={product} align="center">
                                <strong>{product}</strong>
                              </TableCell>
                            ))}
                            <TableCell align="right">
                              <strong>Total</strong>
                            </TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {orders.map((order) => (
                            <TableRow key={order.orderId}>
                              <TableCell>{order.customerName}</TableCell>
                              <TableCell>
                                {formatPhone(order.customerPhone)}
                              </TableCell>
                              <TableCell>
                                {order.customerAddress ? (
                                  <Box sx={{ fontSize: "0.875rem" }}>
                                    {order.customerAddress.street && (
                                      <div>{order.customerAddress.street}</div>
                                    )}
                                    {(order.customerAddress.city ||
                                      order.customerAddress.state ||
                                      order.customerAddress.zipCode) && (
                                      <div>
                                        {[
                                          order.customerAddress.city,
                                          order.customerAddress.state,
                                          order.customerAddress.zipCode,
                                        ]
                                          .filter(Boolean)
                                          .join(" ")}
                                      </div>
                                    )}
                                  </Box>
                                ) : (
                                  "-"
                                )}
                              </TableCell>
                              {allProducts.map((product) => {
                                const totalQuantity = order.lineItems
                                  .filter((li) => li.productName === product)
                                  .reduce(
                                    (sum, item) => sum + item.quantity,
                                    0,
                                  );
                                return (
                                  <TableCell key={product} align="center">
                                    {totalQuantity > 0 ? totalQuantity : "-"}
                                  </TableCell>
                                );
                              })}
                              <TableCell
                                align="right"
                                sx={{ fontWeight: "bold" }}
                              >
                                {formatCurrency(order.totalAmount)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  );
                })()
              )}
            </Paper>
          </Box>
        )}
      </Box>
    </Box>
  );
};
