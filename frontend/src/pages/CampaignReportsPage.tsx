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
  Alert,
  Chip,
} from "@mui/material";
import {
  Download as DownloadIcon,
  Assessment as ReportIcon,
} from "@mui/icons-material";
import {
  GET_UNIT_REPORT,
  LIST_MY_SHARED_CAMPAIGNS,
} from "../lib/graphql";
import * as XLSX from "xlsx";

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
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
  campaignName: string;
  campaignYear: number;
  sellers: UnitSellerSummary[];
  totalSales: number;
  totalOrders: number;
}

type ReportView = "summary" | "detailed" | "unit";

export const CampaignReportsPage: React.FC = () => {
  const [selectedSharedCampaignCode, setSelectedSharedCampaignCode] = useState<string>("");
  const [reportView, setReportView] = useState<ReportView>("unit");

  // Fetch user's shared campaigns
  const { data: sharedCampaignsData, loading: sharedCampaignsLoading } = useQuery<{
    listMySharedCampaigns: SharedCampaign[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  const campaigns = sharedCampaignsData?.listMySharedCampaigns?.filter(
    (p) => p.isActive
  ) || [];

  // Auto-select campaign if only 1 exists
  React.useEffect(() => {
    if (campaigns.length === 1 && !selectedSharedCampaignCode) {
      setSelectedSharedCampaignCode(campaigns[0].sharedCampaignCode);
    }
  }, [campaigns, selectedSharedCampaignCode]);

  const selectedCampaign = campaigns.find(
    (c) => c.sharedCampaignCode === selectedSharedCampaignCode
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
      campaignName: selectedCampaign?.campaignName,
      campaignYear: selectedCampaign?.campaignYear,
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

  const exportSellerReport = () => {
    if (!report) return;

    const wb = XLSX.utils.book_new();

    // Get all unique products
    const allProducts = new Set<string>();
    report.sellers.forEach((seller) => {
      seller.orders.forEach((order) => {
        order.lineItems.forEach((item) => {
          allProducts.add(item.productName);
        });
      });
    });
    const productList = Array.from(allProducts).sort();

    // Build header row
    const headerRow = ["Scout Name", ...productList, "Total Items", "Total Sales"];

    // Build data rows
    const dataRows = report.sellers.map((seller) => {
      // Calculate product totals for this seller
      const productTotals: Record<string, number> = {};
      let sellerTotalItems = 0;
      seller.orders.forEach((order) => {
        order.lineItems.forEach((item) => {
          productTotals[item.productName] = (productTotals[item.productName] || 0) + item.quantity;
          sellerTotalItems += item.quantity;
        });
      });

      return [
        seller.sellerName,
        ...productList.map((product) => productTotals[product] || 0),
        sellerTotalItems,
        seller.totalSales,
      ];
    });

    // Build totals row
    const grandTotals: Record<string, number> = {};
    let grandTotalItems = 0;
    report.sellers.forEach((seller) => {
      seller.orders.forEach((order) => {
        order.lineItems.forEach((item) => {
          grandTotals[item.productName] = (grandTotals[item.productName] || 0) + item.quantity;
          grandTotalItems += item.quantity;
        });
      });
    });

    const totalsRow = [
      "Total",
      ...productList.map((product) => grandTotals[product] || 0),
      grandTotalItems,
      report.totalSales,
    ];

    // Combine all rows
    const sheetData = [headerRow, ...dataRows, totalsRow];
    const sheet = XLSX.utils.aoa_to_sheet(sheetData);
    XLSX.utils.book_append_sheet(wb, sheet, "Seller Report");

    // Download
    const fileName = `${report.unitType}_${report.unitNumber}_${report.campaignName}_${report.campaignYear}_Seller_Report.xlsx`;
    XLSX.writeFile(wb, fileName);
  };

  const exportOrderDetails = () => {
    if (!report) return;

    const wb = XLSX.utils.book_new();

    // Flatten all orders from all sellers
    const allOrders = report.sellers.flatMap((seller) =>
      seller.orders.map((order) => ({
        ...order,
        sellerName: seller.sellerName,
      }))
    );

    // Get all unique products
    const allProducts = Array.from(
      new Set(
        allOrders.flatMap((order) =>
          order.lineItems.map((item) => item.productName)
        )
      )
    ).sort();

    // Build header row
    const headerRow = ["Scout", "Customer", ...allProducts, "Total"];

    // Build data rows
    const dataRows = allOrders.map((order) => {
      const productQuantities = allProducts.map((product) => {
        const totalQuantity = order.lineItems
          .filter((li) => li.productName === product)
          .reduce((sum, item) => sum + item.quantity, 0);
        return totalQuantity || "";
      });

      return [
        order.sellerName,
        order.customerName,
        ...productQuantities,
        order.totalAmount,
      ];
    });

    // Build totals row
    const productTotals: Record<string, number> = {};
    allOrders.forEach((order) => {
      order.lineItems.forEach((item) => {
        productTotals[item.productName] =
          (productTotals[item.productName] || 0) + item.quantity;
      });
    });

    const totalsRow = [
      "Total",
      "",
      ...allProducts.map((product) => productTotals[product] || 0),
      report.totalSales,
    ];

    // Combine all rows
    const sheetData = [headerRow, ...dataRows, totalsRow];
    const sheet = XLSX.utils.aoa_to_sheet(sheetData);
    XLSX.utils.book_append_sheet(wb, sheet, "Order Details");

    // Download
    const fileName = `${report.unitType}_${report.unitNumber}_${report.campaignName}_${report.campaignYear}_Order_Details.xlsx`;
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

            {sharedCampaignsLoading ? (
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
                  value={selectedSharedCampaignCode}
                  onChange={(e) => setSelectedSharedCampaignCode(e.target.value)}
                  fullWidth
                  helperText="Select a shared campaign to view its sales report"
                >
                  {campaigns.map((campaign) => (
                    <MenuItem
                      key={campaign.sharedCampaignCode}
                      value={campaign.sharedCampaignCode}
                    >
                      {campaign.unitType} {campaign.unitNumber} -{" "}
                      {campaign.campaignName} {campaign.campaignYear} (
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
                        <strong>Campaign:</strong> {selectedCampaign.campaignName}{" "}
                        {selectedCampaign.campaignYear}
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
                <Typography variant="h5">
                  {report.unitType} {report.unitNumber} - {report.campaignName}{" "}
                  {report.campaignYear}
                </Typography>

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
                    No sales data found for this unit in {report.campaignYear}.
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
              <Paper sx={{ p: { xs: 1.5, sm: 3 } }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
                  <Typography variant="h6">Seller Report</Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<DownloadIcon />}
                    onClick={exportSellerReport}
                  >
                    Export to Excel
                  </Button>
                </Box>
                <TableContainer sx={{ overflowX: "auto" }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow sx={{ bgcolor: "action.hover" }}>
                        <TableCell>
                          <strong>Scout</strong>
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
                                <TableCell key={productName} align="center">
                                  <strong>{productName}</strong>
                                </TableCell>
                              ))}
                              <TableCell align="center">
                                <strong>Total Items</strong>
                              </TableCell>
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
                        let sellerTotalItems = 0;
                        seller.orders.forEach((order) => {
                          order.lineItems.forEach((item) => {
                            productTotals[item.productName] =
                              (productTotals[item.productName] || 0) +
                              item.quantity;
                            sellerTotalItems += item.quantity;
                          });
                        });

                        return (
                          <TableRow key={seller.profileId}>
                            <TableCell>{seller.sellerName}</TableCell>
                            {productList.map((productName) => (
                              <TableCell key={productName} align="center">
                                {productTotals[productName] || 0}
                              </TableCell>
                            ))}
                            <TableCell align="center">
                              <strong>{sellerTotalItems}</strong>
                            </TableCell>
                            <TableCell align="right">
                              {formatCurrency(seller.totalSales)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                      {/* Totals Row */}
                      <TableRow sx={{ bgcolor: "action.hover" }}>
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
                          let grandTotalItems = 0;
                          report.sellers.forEach((seller) => {
                            seller.orders.forEach((order) => {
                              order.lineItems.forEach((item) => {
                                grandTotals[item.productName] =
                                  (grandTotals[item.productName] || 0) +
                                  item.quantity;
                                grandTotalItems += item.quantity;
                              });
                            });
                          });

                          return (
                            <>
                              {productList.map((productName) => (
                                <TableCell key={productName} align="center">
                                  <strong>
                                    {grandTotals[productName] || 0}
                                  </strong>
                                </TableCell>
                              ))}
                              <TableCell align="center">
                                <strong>{grandTotalItems}</strong>
                              </TableCell>
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

            {/* Order Details View - All Orders Table (like individual campaign report) */}
            {reportView === "detailed" && report.sellers.length > 0 && (
              <Paper sx={{ p: { xs: 1.5, sm: 3 } }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
                  <Typography variant="h6">
                    All Orders
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<DownloadIcon />}
                    onClick={exportOrderDetails}
                  >
                    Export to Excel
                  </Button>
                </Box>
                {(() => {
                  // Flatten all orders from all sellers into a single list
                  const allOrders = report.sellers.flatMap((seller) =>
                    seller.orders.map((order) => ({
                      ...order,
                      sellerName: seller.sellerName,
                    }))
                  );

                  // Get all unique products
                  const allProducts = Array.from(
                    new Set(
                      allOrders.flatMap((order) =>
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
                              <strong>Scout</strong>
                            </TableCell>
                            <TableCell>
                              <strong>Customer</strong>
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
                          {allOrders.map((order) => (
                            <TableRow key={order.orderId}>
                              <TableCell>{order.sellerName}</TableCell>
                              <TableCell>{order.customerName}</TableCell>
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
                          {/* Totals Row */}
                          <TableRow sx={{ bgcolor: "action.hover" }}>
                            <TableCell colSpan={2}>
                              <strong>Total</strong>
                            </TableCell>
                            {(() => {
                              // Calculate totals for each product
                              const productTotals: Record<string, number> = {};
                              allOrders.forEach((order) => {
                                order.lineItems.forEach((item) => {
                                  productTotals[item.productName] =
                                    (productTotals[item.productName] || 0) + item.quantity;
                                });
                              });

                              return (
                                <>
                                  {allProducts.map((product) => (
                                    <TableCell key={product} align="center">
                                      <strong>{productTotals[product] || 0}</strong>
                                    </TableCell>
                                  ))}
                                  <TableCell align="right">
                                    <strong>{formatCurrency(report.totalSales)}</strong>
                                  </TableCell>
                                </>
                              );
                            })()}
                          </TableRow>
                        </TableBody>
                      </Table>
                    </TableContainer>
                  );
                })()}
              </Paper>
            )}

            {/* Unit Summary View */}
            {reportView === "unit" && report.sellers.length > 0 && (
              <Paper sx={{ p: 3 }}>
                <Stack spacing={3}>
                  <Typography variant="h6">Unit Overview</Typography>

                  {(() => {
                    // Calculate total items across all sellers
                    const totalItems = report.sellers.reduce((sum, seller) => {
                      const sellerItems = seller.orders.reduce((orderSum, order) => {
                        return orderSum + order.lineItems.reduce((itemSum, item) => itemSum + item.quantity, 0);
                      }, 0);
                      return sum + sellerItems;
                    }, 0);

                    return (
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
                            Total Items
                          </Typography>
                          <Typography variant="h4">{totalItems}</Typography>
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
                    );
                  })()}

                  <Typography variant="h6" sx={{ mt: 2 }}>
                    Top Sellers
                  </Typography>
                  <TableContainer>
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell>Rank</TableCell>
                          <TableCell>Seller</TableCell>
                          <TableCell align="right">Items</TableCell>
                          <TableCell align="right">Sales</TableCell>
                          <TableCell align="right">% of Total</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {report.sellers.slice(0, 5).map((seller, idx) => {
                          // Calculate total items for this seller
                          const sellerItems = seller.orders.reduce((orderSum, order) => {
                            return orderSum + order.lineItems.reduce((itemSum, item) => itemSum + item.quantity, 0);
                          }, 0);

                          return (
                            <TableRow key={seller.profileId}>
                              <TableCell>{idx + 1}</TableCell>
                              <TableCell>{seller.sellerName}</TableCell>
                              <TableCell align="right">{sellerItems}</TableCell>
                              <TableCell align="right">
                                {formatCurrency(seller.totalSales)}
                              </TableCell>
                              <TableCell align="right">
                                {
                                  (
                                  (seller.totalSales / report.totalSales) *
                                  100
                                ).toFixed(1)
                                }%
                              </TableCell>
                            </TableRow>
                          );
                        })}
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
