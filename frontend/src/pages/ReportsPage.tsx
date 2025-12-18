/**
 * ReportsPage - Generate and download season reports
 */

import React, { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery } from "@apollo/client/react";
import {
  Box,
  Typography,
  Paper,
  Stack,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
  Link,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from "@mui/material";
import {
  Download as DownloadIcon,
  Description as FileIcon,
} from "@mui/icons-material";
import { REQUEST_SEASON_REPORT, LIST_ORDERS_BY_SEASON } from "../lib/graphql";
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

interface ReportResult {
  reportId: string;
  reportUrl?: string;
  status: string;
  expiresAt?: string;
}

export const ReportsPage: React.FC = () => {
  const { seasonId: encodedSeasonId } = useParams<{ seasonId: string }>();
  const seasonId = encodedSeasonId ? decodeURIComponent(encodedSeasonId) : "";
  const [format, setFormat] = useState<"CSV" | "XLSX">("XLSX");
  const [lastReport, setLastReport] = useState<ReportResult | null>(null);

  const { data: ordersData, loading: ordersLoading } = useQuery<{
    listOrdersBySeason: Order[];
  }>(LIST_ORDERS_BY_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  const [requestReport, { loading, error }] = useMutation<{
    requestSeasonReport: ReportResult;
  }>(REQUEST_SEASON_REPORT, {
    onCompleted: (data) => {
      setLastReport(data.requestSeasonReport);
    },
  });

  const handleGenerateReport = async () => {
    if (!seasonId) return;
    setLastReport(null);
    await requestReport({
      variables: {
        input: {
          seasonId,
          format,
        },
      },
    });
  };

  const orders = ordersData?.listOrdersBySeason || [];

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
    <Box>
      <Typography variant="h5" gutterBottom>
        Reports & Exports
      </Typography>

      {/* Report Info */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          About Reports
        </Typography>
        <Stack spacing={1}>
          <Typography variant="body2">
            • <strong>Excel (XLSX):</strong> Formatted spreadsheet with product
            columns, suitable for further analysis and pivot tables.
          </Typography>
          <Typography variant="body2">
            • <strong>CSV:</strong> Plain text file, compatible with all
            spreadsheet programs and databases.
          </Typography>
        </Stack>
      </Paper>

      {/* Complete Order Table */}
      <Paper sx={{ p: 3, mt: 3 }}>
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
                onClick={() => downloadAsCSV(orders, seasonId)}
                variant="outlined"
              >
                CSV
              </Button>
              <Button
                size="small"
                startIcon={<DownloadIcon />}
                onClick={() => downloadAsXLSX(orders, seasonId)}
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
            No orders found for this season.
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
                            .reduce((sum, item) => sum + item.quantity, 0);
                          return (
                            <TableCell key={product} align="center">
                              {totalQuantity > 0 ? totalQuantity : "-"}
                            </TableCell>
                          );
                        })}
                        <TableCell align="right" sx={{ fontWeight: "bold" }}>
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
  );
};
