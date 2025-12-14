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

  const {
    data: ordersData,
    loading: ordersLoading,
  } = useQuery<{ listOrdersBySeason: Order[] }>(LIST_ORDERS_BY_SEASON, {
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
    // Format as (XXX) XXX-XXXX if we have 10 digits
    if (digits.length === 10) {
      return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
    }
    // Return original if not 10 digits
    return phone;
  };

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Reports & Exports
      </Typography>

      {/* Generate Report */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Generate Season Report
        </Typography>
        <Typography variant="body2" color="text.secondary" paragraph>
          Export all orders for this season to Excel or CSV format. The report
          includes customer names, contact info, order details, payment methods,
          and totals.
        </Typography>

        <Stack direction="row" spacing={2} alignItems="center" mb={2}>
          <FormControl sx={{ minWidth: 200 }}>
            <InputLabel>Format</InputLabel>
            <Select
              value={format}
              label="Format"
              onChange={(e) => setFormat(e.target.value as "CSV" | "XLSX")}
              disabled={loading}
            >
              <MenuItem value="XLSX">
                <Stack direction="row" spacing={1} alignItems="center">
                  <FileIcon fontSize="small" />
                  <span>Excel (XLSX)</span>
                </Stack>
              </MenuItem>
              <MenuItem value="CSV">
                <Stack direction="row" spacing={1} alignItems="center">
                  <FileIcon fontSize="small" />
                  <span>CSV</span>
                </Stack>
              </MenuItem>
            </Select>
          </FormControl>

          <Button
            variant="contained"
            startIcon={
              loading ? <CircularProgress size={20} /> : <DownloadIcon />
            }
            onClick={handleGenerateReport}
            disabled={loading}
          >
            {loading ? "Generating..." : "Generate Report"}
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            Failed to generate report: {error.message}
          </Alert>
        )}

        {lastReport && (
          <Alert
            severity={lastReport.status === "COMPLETED" ? "success" : "info"}
            sx={{ mt: 2 }}
          >
            {lastReport.status === "COMPLETED" && lastReport.reportUrl ? (
              <Stack spacing={1}>
                <Typography variant="body2">
                  ✅ Report generated successfully! Your download is ready.
                </Typography>
                <Link
                  href={lastReport.reportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  download
                  sx={{ fontWeight: "medium" }}
                >
                  Download Report ({format})
                </Link>
                {lastReport.expiresAt && (
                  <Typography variant="caption" color="text.secondary">
                    Link expires:{" "}
                    {new Date(lastReport.expiresAt).toLocaleString()}
                  </Typography>
                )}
              </Stack>
            ) : lastReport.status === "PENDING" ? (
              <Typography variant="body2">
                ⏳ Report is being generated. This may take a moment...
              </Typography>
            ) : (
              <Typography variant="body2">
                ❌ Report generation failed. Please try again.
              </Typography>
            )}
          </Alert>
        )}
      </Paper>

      {/* Report Info */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          About Reports
        </Typography>
        <Stack spacing={1}>
          <Typography variant="body2">
            • <strong>Excel (XLSX):</strong> Formatted spreadsheet with multiple
            columns, suitable for further analysis and pivot tables.
          </Typography>
          <Typography variant="body2">
            • <strong>CSV:</strong> Plain text file, compatible with all
            spreadsheet programs and databases.
          </Typography>
          <Typography variant="body2">
            • Report links expire after 24 hours for security reasons.
          </Typography>
          <Typography variant="body2">
            • All customer data is securely encrypted during storage and
            transmission.
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
        ) : (() => {
          // Get all unique products
          const allProducts = Array.from(
            new Set(
              orders.flatMap((order) =>
                order.lineItems.map((item) => item.productName)
              )
            )
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
                      <TableCell>{order.customerPhone || "-"}</TableCell>
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
                        const item = order.lineItems.find(
                          (li) => li.productName === product
                        );
                        return (
                          <TableCell key={product} align="center">
                            {item ? item.quantity : "-"}
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
        })()}
      </Paper>
    </Box>
  );
};
