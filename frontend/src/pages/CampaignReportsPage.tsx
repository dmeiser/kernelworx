/**
 * UnitReportsPage - Generate and view shared campaign sales reports
 *
 * Provides three report views:
 * 1. Campaign Summary - Overall campaign totals
 * 2. Seller Report - Totals by seller with product breakdown
 * 3. Order Details - Each seller with all their orders
 */

import React, { useState } from "react";
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
  TextField,
  MenuItem,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
  Chip,
} from "@mui/material";
import {
  ExpandMore as ExpandMoreIcon,
  Download as DownloadIcon,
  Assessment as ReportIcon,
} from "@mui/icons-material";
import {
  GET_UNIT_REPORT,
  LIST_MY_CAMPAIGN_PREFILLS,
} from "../lib/graphql";
import * as XLSX from "xlsx";

interface CampaignPrefill {
  prefillCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  seasonName: string;
  seasonYear: number;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  description?: string;
  isActive: boolean;
}

interface LineItem {
  productId: string;
  productName: string;
  quantity: number;
  pricePerUnit: number;
  subtotal: number;
}

interface UnitOrderDetail {
  orderId: string;
  customerName: string;
  orderDate: string;
  totalAmount: number;
  lineItems: LineItem[];
}

interface UnitSellerSummary {
  profileId: string;
  sellerName: string;
  totalSales: number;
  orderCount: number;
  orders: UnitOrderDetail[];
}

interface UnitReport {
  unitType: string;
  unitNumber: number;
  seasonName: string;
  seasonYear: number;
  sellers: UnitSellerSummary[];
  totalSales: number;
  totalOrders: number;
}

type ReportView = "summary" | "detailed" | "unit";

export const CampaignReportsPage: React.FC = () => {
  const [selectedPrefillCode, setSelectedPrefillCode] = useState<string>("");
  const [reportView, setReportView] = useState<ReportView>("unit");

  // Fetch user's shared campaigns
  const { data: prefillsData, loading: prefillsLoading } = useQuery<{
    listMyCampaignPrefills: CampaignPrefill[];
  }>(LIST_MY_CAMPAIGN_PREFILLS);

  const campaigns = prefillsData?.listMyCampaignPrefills?.filter(
    (p) => p.isActive
  ) || [];

  // Auto-select campaign if only 1 exists
  React.useEffect(() => {
    if (campaigns.length === 1 && !selectedPrefillCode) {
      setSelectedPrefillCode(campaigns[0].prefillCode);
    }
  }, [campaigns, selectedPrefillCode]);

  const selectedCampaign = campaigns.find(
    (c) => c.prefillCode === selectedPrefillCode
  );

  const canGenerateReport = !!selectedCampaign;

  const { data, loading, error, refetch } = useQuery<{
    getUnitReport: UnitReport;
  }>(GET_UNIT_REPORT, {
    variables: {
      unitType: selectedCampaign?.unitType,
      unitNumber: selectedCampaign?.unitNumber,
      city: selectedCampaign?.city,
      state: selectedCampaign?.state,
      seasonName: selectedCampaign?.seasonName,
      seasonYear: selectedCampaign?.seasonYear,
      catalogId: selectedCampaign?.catalogId,
    },
    skip: !canGenerateReport,
  });

  const report = data?.getUnitReport;

  const handleGenerateReport = () => {
    if (canGenerateReport) {
      refetch();
    }
  };

  const formatCurrency = (amount: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(amount);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const exportToExcel = () => {
    if (!report) return;

    const wb = XLSX.utils.book_new();

    // Sheet 1: Seller Summary
    const summaryData = [
      ["Seller Name", "Total Sales", "Order Count"],
      ...report.sellers.map((seller) => [
        seller.sellerName,
        seller.totalSales,
        seller.orderCount,
      ]),
      [],
      ["Unit Total", report.totalSales, report.totalOrders],
    ];
    const summarySheet = XLSX.utils.aoa_to_sheet(summaryData);
    XLSX.utils.book_append_sheet(wb, summarySheet, "Seller Summary");

    // Sheet 2: Detailed Orders
    const detailedData: (string | number)[][] = [
      [
        "Seller",
        "Customer",
        "Order Date",
        "Product",
        "Quantity",
        "Price",
        "Subtotal",
        "Order Total",
      ],
    ];

    report.sellers.forEach((seller) => {
      seller.orders.forEach((order) => {
        order.lineItems.forEach((item, idx) => {
          detailedData.push([
            idx === 0 ? seller.sellerName : "",
            idx === 0 ? order.customerName : "",
            idx === 0 ? formatDate(order.orderDate) : "",
            item.productName,
            item.quantity,
            item.pricePerUnit,
            item.subtotal,
            idx === 0 ? order.totalAmount : "",
          ]);
        });
      });
    });

    const detailedSheet = XLSX.utils.aoa_to_sheet(detailedData);
    XLSX.utils.book_append_sheet(wb, detailedSheet, "Detailed Orders");

    // Download
    const fileName = `${report.unitType}_${report.unitNumber}_${report.seasonName}_${report.seasonYear}_Report.xlsx`;
    XLSX.writeFile(wb, fileName);
  };

  return (
    <Box sx={{ p: 3 }}>
      <Stack spacing={3}>
        {/* Header */}
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            <ReportIcon sx={{ mr: 1, verticalAlign: "bottom" }} />
            Shared Campaign Reports
          </Typography>
          <Typography variant="body2" color="text.secondary">
            View aggregated sales data for all sellers in your shared campaigns
          </Typography>
        </Box>

        {/* Campaign Selector */}
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Typography variant="h6">Select Shared Campaign</Typography>

            {prefillsLoading ? (
              <CircularProgress />
            ) : campaigns.length === 0 ? (
              <Alert severity="info">
                You don't have any active shared campaigns yet. Create one to
                start generating reports.
              </Alert>
            ) : (
              <>
                <TextField
                  select
                  label="Shared Campaign"
                  value={selectedPrefillCode}
                  onChange={(e) => setSelectedPrefillCode(e.target.value)}
                  fullWidth
                  helperText="Select a shared campaign to view its sales report"
                >
                  {campaigns.map((campaign) => (
                    <MenuItem
                      key={campaign.prefillCode}
                      value={campaign.prefillCode}
                    >
                      {campaign.unitType} {campaign.unitNumber} -{" "}
                      {campaign.seasonName} {campaign.seasonYear} (
                      {campaign.catalog.catalogName})
                      {campaign.description && ` - ${campaign.description}`}
                    </MenuItem>
                  ))}
                </TextField>

                {selectedCampaign && (
                  <Paper variant="outlined" sx={{ p: 2, bgcolor: "grey.50" }}>
                    <Typography variant="subtitle2" gutterBottom>
                      Campaign Details:
                    </Typography>
                    <Stack spacing={0.5}>
                      <Typography variant="body2">
                        <strong>Unit:</strong> {selectedCampaign.unitType}{" "}
                        {selectedCampaign.unitNumber}
                      </Typography>
                      <Typography variant="body2">
                        <strong>Location:</strong> {selectedCampaign.city},{" "}
                        {selectedCampaign.state}
                      </Typography>
                      <Typography variant="body2">
                        <strong>Season:</strong> {selectedCampaign.seasonName}{" "}
                        {selectedCampaign.seasonYear}
                      </Typography>
                      <Typography variant="body2">
                        <strong>Catalog:</strong>{" "}
                        {selectedCampaign.catalog.catalogName}
                      </Typography>
                    </Stack>
                  </Paper>
                )}

                <Button
                  variant="contained"
                  onClick={handleGenerateReport}
                  disabled={!canGenerateReport || loading}
                  startIcon={
                    loading ? <CircularProgress size={20} /> : <ReportIcon />
                  }
                >
                  {loading ? "Generating..." : "Generate Report"}
                </Button>
              </>
            )}
          </Stack>
        </Paper>

        {/* Error Display */}
        {error && (
          <Alert severity="error">Error loading report: {error.message}</Alert>
        )}

        {/* Report Display */}
        {report && (
          <>
            {/* Report Header */}
            <Paper sx={{ p: 3 }}>
              <Stack spacing={2}>
                <Box
                  display="flex"
                  justifyContent="space-between"
                  alignItems="center"
                >
                  <Typography variant="h5">
                    {report.unitType} {report.unitNumber} - {report.seasonName}{" "}
                    {report.seasonYear}
                  </Typography>
                  <Button
                    variant="outlined"
                    startIcon={<DownloadIcon />}
                    onClick={exportToExcel}
                  >
                    Export to Excel
                  </Button>
                </Box>

                <Stack direction="row" spacing={2}>
                  <Chip
                    label={`${report.sellers.length} Sellers`}
                    color="primary"
                    variant="outlined"
                  />
                  <Chip
                    label={`${report.totalOrders} Orders`}
                    color="secondary"
                    variant="outlined"
                  />
                  <Chip
                    label={`${formatCurrency(report.totalSales)} Total Sales`}
                    color="success"
                    variant="outlined"
                  />
                </Stack>

                {report.sellers.length === 0 && (
                  <Alert severity="info">
                    No sales data found for this unit in {report.seasonYear}.
                    Make sure sellers have set their unit type and number on
                    their profiles.
                  </Alert>
                )}
              </Stack>
            </Paper>

            {/* Report View Selector */}
            {report.sellers.length > 0 && (
              <Stack direction="row" spacing={1}>
                <Button
                  variant={reportView === "unit" ? "contained" : "outlined"}
                  onClick={() => setReportView("unit")}
                >
                  Unit Summary
                </Button>
                <Button
                  variant={reportView === "summary" ? "contained" : "outlined"}
                  onClick={() => setReportView("summary")}
                >
                  Seller Report
                </Button>
                <Button
                  variant={reportView === "detailed" ? "contained" : "outlined"}
                  onClick={() => setReportView("detailed")}
                >
                  Order Details
                </Button>
              </Stack>
            )}

            {/* Seller Report View - Products by Seller */}
            {reportView === "summary" && report.sellers.length > 0 && (
              <Paper>
                <TableContainer>
                  <Table>
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Scout Name</strong>
                        </TableCell>
                        {(() => {
                          // Get all unique product names across all sellers
                          const allProducts = new Set<string>();
                          report.sellers.forEach((seller) => {
                            seller.orders.forEach((order) => {
                              order.lineItems.forEach((item) => {
                                allProducts.add(item.productName);
                              });
                            });
                          });
                          const productList = Array.from(allProducts).sort();

                          return (
                            <>
                              {productList.map((productName) => (
                                <TableCell key={productName} align="right">
                                  <strong>{productName}</strong>
                                </TableCell>
                              ))}
                              <TableCell align="right">
                                <strong>Total Sales</strong>
                              </TableCell>
                            </>
                          );
                        })()}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {report.sellers.map((seller) => {
                        // Get all unique products across all sellers for consistent columns
                        const allProducts = new Set<string>();
                        report.sellers.forEach((s) => {
                          s.orders.forEach((order) => {
                            order.lineItems.forEach((item) => {
                              allProducts.add(item.productName);
                            });
                          });
                        });
                        const productList = Array.from(allProducts).sort();

                        // Aggregate quantities by product for this seller
                        const productTotals: Record<string, number> = {};
                        seller.orders.forEach((order) => {
                          order.lineItems.forEach((item) => {
                            productTotals[item.productName] =
                              (productTotals[item.productName] || 0) +
                              item.quantity;
                          });
                        });

                        return (
                          <TableRow key={seller.profileId}>
                            <TableCell>{seller.sellerName}</TableCell>
                            {productList.map((productName) => (
                              <TableCell key={productName} align="right">
                                {productTotals[productName] || 0}
                              </TableCell>
                            ))}
                            <TableCell align="right">
                              {formatCurrency(seller.totalSales)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                      {/* Totals Row */}
                      <TableRow>
                        <TableCell>
                          <strong>Total</strong>
                        </TableCell>
                        {(() => {
                          // Get all unique products
                          const allProducts = new Set<string>();
                          report.sellers.forEach((s) => {
                            s.orders.forEach((order) => {
                              order.lineItems.forEach((item) => {
                                allProducts.add(item.productName);
                              });
                            });
                          });
                          const productList = Array.from(allProducts).sort();

                          // Calculate totals for each product
                          const grandTotals: Record<string, number> = {};
                          report.sellers.forEach((seller) => {
                            seller.orders.forEach((order) => {
                              order.lineItems.forEach((item) => {
                                grandTotals[item.productName] =
                                  (grandTotals[item.productName] || 0) +
                                  item.quantity;
                              });
                            });
                          });

                          return (
                            <>
                              {productList.map((productName) => (
                                <TableCell key={productName} align="right">
                                  <strong>
                                    {grandTotals[productName] || 0}
                                  </strong>
                                </TableCell>
                              ))}
                              <TableCell align="right">
                                <strong>
                                  {formatCurrency(report.totalSales)}
                                </strong>
                              </TableCell>
                            </>
                          );
                        })()}
                      </TableRow>
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            )}

            {/* Detailed Seller View */}
            {reportView === "detailed" && report.sellers.length > 0 && (
              <Stack spacing={2}>
                {report.sellers.map((seller) => (
                  <Accordion
                    key={seller.profileId}
                    defaultExpanded={report.sellers.length === 1}
                  >
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Box
                        sx={{
                          width: "100%",
                          display: "flex",
                          justifyContent: "space-between",
                          pr: 2,
                        }}
                      >
                        <Typography>
                          <strong>{seller.sellerName}</strong>
                        </Typography>
                        <Typography color="text.secondary">
                          {seller.orderCount} orders •{" "}
                          {formatCurrency(seller.totalSales)}
                        </Typography>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                      <TableContainer>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell>Customer</TableCell>
                              <TableCell>Date</TableCell>
                              <TableCell>Products</TableCell>
                              <TableCell align="right">Total</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {seller.orders.map((order) => (
                              <TableRow key={order.orderId}>
                                <TableCell>{order.customerName}</TableCell>
                                <TableCell>
                                  {formatDate(order.orderDate)}
                                </TableCell>
                                <TableCell>
                                  {order.lineItems.map((item, idx) => (
                                    <div key={idx}>
                                      {item.quantity}x {item.productName}
                                    </div>
                                  ))}
                                </TableCell>
                                <TableCell align="right">
                                  {formatCurrency(order.totalAmount)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Stack>
            )}

            {/* Unit Summary View */}
            {reportView === "unit" && report.sellers.length > 0 && (
              <Paper sx={{ p: 3 }}>
                <Stack spacing={3}>
                  <Typography variant="h6">Unit Overview</Typography>

                  <Stack direction={{ xs: "column", sm: "row" }} spacing={3}>
                    <Box flex={1}>
                      <Typography variant="body2" color="text.secondary">
                        Total Sellers
                      </Typography>
                      <Typography variant="h4">
                        {report.sellers.length}
                      </Typography>
                    </Box>
                    <Box flex={1}>
                      <Typography variant="body2" color="text.secondary">
                        Total Orders
                      </Typography>
                      <Typography variant="h4">{report.totalOrders}</Typography>
                    </Box>
                    <Box flex={1}>
                      <Typography variant="body2" color="text.secondary">
                        Total Sales
                      </Typography>
                      <Typography variant="h4" color="success.main">
                        {formatCurrency(report.totalSales)}
                      </Typography>
                    </Box>
                    <Box flex={1}>
                      <Typography variant="body2" color="text.secondary">
                        Avg per Seller
                      </Typography>
                      <Typography variant="h4">
                        {formatCurrency(
                          report.totalSales / report.sellers.length,
                        )}
                      </Typography>
                    </Box>
                  </Stack>

                  <Typography variant="h6" sx={{ mt: 2 }}>
                    Top Sellers
                  </Typography>
                  <TableContainer>
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell>Rank</TableCell>
                          <TableCell>Seller</TableCell>
                          <TableCell align="right">Sales</TableCell>
                          <TableCell align="right">% of Total</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {report.sellers.slice(0, 5).map((seller, idx) => (
                          <TableRow key={seller.profileId}>
                            <TableCell>{idx + 1}</TableCell>
                            <TableCell>{seller.sellerName}</TableCell>
                            <TableCell align="right">
                              {formatCurrency(seller.totalSales)}
                            </TableCell>
                            <TableCell align="right">
                              {(
                                (seller.totalSales / report.totalSales) *
                                100
                              ).toFixed(1)}
                              %
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Stack>
              </Paper>
            )}
          </>
        )}
      </Stack>
    </Box>
  );
};
