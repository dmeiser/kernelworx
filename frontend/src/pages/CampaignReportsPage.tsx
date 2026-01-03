/**
 * UnitReportsPage - Generate and view shared campaign sales reports
 *
 * Provides three report views:
 * 1. Campaign Summary - Overall campaign totals
 * 2. Seller Report - Totals by seller with product breakdown
 * 3. Order Details - Each seller with all their orders
 */

import React, { useMemo, useState, useEffect, useCallback } from 'react';
import { useQuery } from '@apollo/client/react';
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
} from '@mui/material';
import { Download as DownloadIcon, Assessment as ReportIcon } from '@mui/icons-material';
import * as XLSX from 'xlsx';
import { GET_UNIT_REPORT, LIST_MY_SHARED_CAMPAIGNS } from '../lib/graphql';

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

type ReportView = 'summary' | 'detailed' | 'unit';

type SellerOrder = UnitOrderDetail & { sellerName: string };

type ProductTotals = Record<string, number>;

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount);

const getActiveCampaigns = (data?: { listMySharedCampaigns: SharedCampaign[] }) =>
  data?.listMySharedCampaigns?.filter((campaign) => campaign.isActive) || [];

const getProductList = (report?: UnitReport): string[] => {
  if (!report) return [];
  const allProducts = new Set<string>();
  report.sellers.forEach((seller) => {
    seller.orders.forEach((order) => {
      order.lineItems.forEach((item) => allProducts.add(item.productName));
    });
  });
  return Array.from(allProducts).sort();
};

const getAllOrders = (report?: UnitReport): SellerOrder[] => {
  if (!report) return [];
  return report.sellers.flatMap((seller) =>
    seller.orders.map((order) => ({ ...order, sellerName: seller.sellerName })),
  );
};

const calculateSellerProductTotals = (
  seller: UnitSellerSummary,
  productList: string[],
): { totals: ProductTotals; totalItems: number } => {
  const totals: ProductTotals = {};
  let totalItems = 0;
  seller.orders.forEach((order) => {
    order.lineItems.forEach((item) => {
      totals[item.productName] = (totals[item.productName] || 0) + item.quantity;
      totalItems += item.quantity;
    });
  });
  productList.forEach((product) => {
    if (!totals[product]) totals[product] = 0;
  });
  return { totals, totalItems };
};

const calculateGrandTotals = (report: UnitReport, productList: string[]) => {
  const grandTotals: ProductTotals = {};
  let grandTotalItems = 0;
  report.sellers.forEach((seller) => {
    seller.orders.forEach((order) => {
      order.lineItems.forEach((item) => {
        grandTotals[item.productName] = (grandTotals[item.productName] || 0) + item.quantity;
        grandTotalItems += item.quantity;
      });
    });
  });
  productList.forEach((product) => {
    if (!grandTotals[product]) grandTotals[product] = 0;
  });
  return { grandTotals, grandTotalItems };
};

const calculateProductTotalsForOrders = (orders: SellerOrder[]) => {
  const totals: ProductTotals = {};
  orders.forEach((order) => {
    order.lineItems.forEach((item) => {
      totals[item.productName] = (totals[item.productName] || 0) + item.quantity;
    });
  });
  return totals;
};

const calculateTotalItems = (report?: UnitReport): number => {
  if (!report) return 0;
  return report.sellers.reduce((sum, seller) => {
    const sellerItems = seller.orders.reduce((orderSum, order) => {
      return orderSum + order.lineItems.reduce((itemSum, item) => itemSum + item.quantity, 0);
    }, 0);
    return sum + sellerItems;
  }, 0);
};

const getTopSellers = (report?: UnitReport) => {
  if (!report) return [] as UnitSellerSummary[];
  return [...report.sellers].sort((a, b) => b.totalSales - a.totalSales).slice(0, 5);
};

const buildSellerReportWorkbook = (report: UnitReport, productList: string[]) => {
  const wb = XLSX.utils.book_new();

  const headerRow = ['Scout Name', ...productList, 'Total Items', 'Total Sales'];

  const dataRows = report.sellers.map((seller) => {
    const { totals, totalItems } = calculateSellerProductTotals(seller, productList);
    return [seller.sellerName, ...productList.map((product) => totals[product] || 0), totalItems, seller.totalSales];
  });

  const { grandTotals, grandTotalItems } = calculateGrandTotals(report, productList);
  const totalsRow = [
    'Total',
    ...productList.map((product) => grandTotals[product] || 0),
    grandTotalItems,
    report.totalSales,
  ];

  const sheetData = [headerRow, ...dataRows, totalsRow];
  const sheet = XLSX.utils.aoa_to_sheet(sheetData);
  XLSX.utils.book_append_sheet(wb, sheet, 'Seller Report');

  const fileName = `${report.unitType}_${report.unitNumber}_${report.campaignName}_${report.campaignYear}_Seller_Report.xlsx`;
  XLSX.writeFile(wb, fileName);
};

const buildOrderDetailsWorkbook = (report: UnitReport, allOrders: SellerOrder[], allProducts: string[]) => {
  const wb = XLSX.utils.book_new();

  const headerRow = ['Scout', 'Customer', ...allProducts, 'Total'];

  const dataRows = allOrders.map((order) => {
    const productQuantities = allProducts.map((product) => {
      const totalQuantity = order.lineItems
        .filter((li) => li.productName === product)
        .reduce((sum, item) => sum + item.quantity, 0);
      return totalQuantity || '';
    });

    return [order.sellerName, order.customerName, ...productQuantities, order.totalAmount];
  });

  const productTotals = calculateProductTotalsForOrders(allOrders);
  const totalsRow = ['Total', '', ...allProducts.map((product) => productTotals[product] || 0), report.totalSales];

  const sheetData = [headerRow, ...dataRows, totalsRow];
  const sheet = XLSX.utils.aoa_to_sheet(sheetData);
  XLSX.utils.book_append_sheet(wb, sheet, 'Order Details');

  const fileName = `${report.unitType}_${report.unitNumber}_${report.campaignName}_${report.campaignYear}_Order_Details.xlsx`;
  XLSX.writeFile(wb, fileName);
};

interface CampaignSelectorProps {
  campaigns: SharedCampaign[];
  selectedCode: string;
  loading: boolean;
  selectedCampaign: SharedCampaign | undefined;
  onSelect: (code: string) => void;
  onGenerate: () => void;
  canGenerate: boolean;
  loadingReport: boolean;
}

const CampaignSelectorCard: React.FC<CampaignSelectorProps> = ({
  campaigns,
  selectedCode,
  loading,
  selectedCampaign,
  onSelect,
  onGenerate,
  canGenerate,
  loadingReport,
}) => {
  if (loading) {
    return (
      <CampaignSelectorShell>
        <CircularProgress />
      </CampaignSelectorShell>
    );
  }

  if (!campaigns.length) {
    return (
      <CampaignSelectorShell>
        <Alert severity="info">
          You don't have any active shared campaigns yet. Create one to start generating reports.
        </Alert>
      </CampaignSelectorShell>
    );
  }

  return (
    <CampaignSelectorShell>
      <CampaignSelectorForm
        campaigns={campaigns}
        selectedCode={selectedCode}
        selectedCampaign={selectedCampaign}
        onSelect={onSelect}
        onGenerate={onGenerate}
        canGenerate={canGenerate}
        loadingReport={loadingReport}
      />
    </CampaignSelectorShell>
  );
};

const CampaignSelectorShell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Paper sx={{ p: 3 }}>
    <Stack spacing={2}>
      <Typography variant="h6">Select Shared Campaign</Typography>
      {children}
    </Stack>
  </Paper>
);

const CampaignSelectorForm: React.FC<{
  campaigns: SharedCampaign[];
  selectedCode: string;
  selectedCampaign: SharedCampaign | undefined;
  onSelect: (code: string) => void;
  onGenerate: () => void;
  canGenerate: boolean;
  loadingReport: boolean;
}> = ({ campaigns, selectedCode, selectedCampaign, onSelect, onGenerate, canGenerate, loadingReport }) => (
  <Stack spacing={2}>
    <TextField
      select
      label="Shared Campaign"
      value={selectedCode}
      onChange={(event) => onSelect(event.target.value)}
      fullWidth
      helperText="Select a shared campaign to view its sales report"
    >
      {campaigns.map((campaign) => (
        <MenuItem key={campaign.sharedCampaignCode} value={campaign.sharedCampaignCode}>
          {campaign.unitType} {campaign.unitNumber} - {campaign.campaignName} {campaign.campaignYear} (
          {campaign.catalog.catalogName}){campaign.description ? ` - ${campaign.description}` : ''}
        </MenuItem>
      ))}
    </TextField>

    {selectedCampaign ? <CampaignDetails campaign={selectedCampaign} /> : null}

    <Button
      variant="contained"
      onClick={onGenerate}
      disabled={!canGenerate || loadingReport}
      startIcon={loadingReport ? <CircularProgress size={20} /> : <ReportIcon />}
    >
      {loadingReport ? 'Generating...' : 'Generate Report'}
    </Button>
  </Stack>
);

const CampaignDetails: React.FC<{ campaign: SharedCampaign }> = ({ campaign }) => (
  <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50' }}>
    <Typography variant="subtitle2" gutterBottom>
      Campaign Details:
    </Typography>
    <Stack spacing={0.5}>
      <Typography variant="body2">
        <strong>Unit:</strong> {campaign.unitType} {campaign.unitNumber}
      </Typography>
      <Typography variant="body2">
        <strong>Location:</strong> {campaign.city}, {campaign.state}
      </Typography>
      <Typography variant="body2">
        <strong>Campaign:</strong> {campaign.campaignName} {campaign.campaignYear}
      </Typography>
      <Typography variant="body2">
        <strong>Catalog:</strong> {campaign.catalog.catalogName}
      </Typography>
    </Stack>
  </Paper>
);

const ReportSummaryChips: React.FC<{ report: UnitReport }> = ({ report }) => (
  <Stack direction="row" spacing={2}>
    <Chip label={`${report.sellers.length} Sellers`} color="primary" variant="outlined" />
    <Chip label={`${report.totalOrders} Orders`} color="secondary" variant="outlined" />
    <Chip label={`${formatCurrency(report.totalSales)} Total Sales`} color="success" variant="outlined" />
  </Stack>
);

const ReportViewSelector: React.FC<{
  view: ReportView;
  onChange: (view: ReportView) => void;
}> = ({ view, onChange }) => (
  <Stack direction="row" spacing={1}>
    <Button variant={view === 'unit' ? 'contained' : 'outlined'} onClick={() => onChange('unit')}>
      Unit Summary
    </Button>
    <Button variant={view === 'summary' ? 'contained' : 'outlined'} onClick={() => onChange('summary')}>
      Seller Report
    </Button>
    <Button variant={view === 'detailed' ? 'contained' : 'outlined'} onClick={() => onChange('detailed')}>
      Order Details
    </Button>
  </Stack>
);

const SellerReportSection: React.FC<{
  report: UnitReport;
  productList: string[];
  onExport: () => void;
}> = ({ report, productList, onExport }) => (
  <Paper sx={{ p: { xs: 1.5, sm: 3 } }}>
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        mb: 2,
      }}
    >
      <Typography variant="h6">Seller Report</Typography>
      <Button size="small" variant="outlined" startIcon={<DownloadIcon />} onClick={onExport}>
        Export to Excel
      </Button>
    </Box>
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: 'action.hover' }}>
            <TableCell>
              <strong>Scout</strong>
            </TableCell>
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
          </TableRow>
        </TableHead>
        <TableBody>
          {report.sellers.map((seller) => {
            const { totals, totalItems } = calculateSellerProductTotals(seller, productList);
            return (
              <TableRow key={seller.profileId}>
                <TableCell>{seller.sellerName}</TableCell>
                {productList.map((productName) => (
                  <TableCell key={productName} align="center">
                    {totals[productName] || 0}
                  </TableCell>
                ))}
                <TableCell align="center">
                  <strong>{totalItems}</strong>
                </TableCell>
                <TableCell align="right">{formatCurrency(seller.totalSales)}</TableCell>
              </TableRow>
            );
          })}
          <SellerTotalsRow report={report} productList={productList} />
        </TableBody>
      </Table>
    </TableContainer>
  </Paper>
);

const SellerTotalsRow: React.FC<{
  report: UnitReport;
  productList: string[];
}> = ({ report, productList }) => {
  const { grandTotals, grandTotalItems } = calculateGrandTotals(report, productList);
  return (
    <TableRow sx={{ bgcolor: 'action.hover' }}>
      <TableCell>
        <strong>Total</strong>
      </TableCell>
      {productList.map((productName) => (
        <TableCell key={productName} align="center">
          <strong>{grandTotals[productName] || 0}</strong>
        </TableCell>
      ))}
      <TableCell align="center">
        <strong>{grandTotalItems}</strong>
      </TableCell>
      <TableCell align="right">
        <strong>{formatCurrency(report.totalSales)}</strong>
      </TableCell>
    </TableRow>
  );
};

const OrderDetailsSection: React.FC<{
  report: UnitReport;
  allOrders: SellerOrder[];
  allProducts: string[];
  onExport: () => void;
}> = ({ report, allOrders, allProducts, onExport }) => (
  <Paper sx={{ p: { xs: 1.5, sm: 3 } }}>
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        mb: 2,
      }}
    >
      <Typography variant="h6">All Orders</Typography>
      <Button size="small" variant="outlined" startIcon={<DownloadIcon />} onClick={onExport}>
        Export to Excel
      </Button>
    </Box>
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: 'action.hover' }}>
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
                  .filter((line) => line.productName === product)
                  .reduce((sum, item) => sum + item.quantity, 0);
                return (
                  <TableCell key={product} align="center">
                    {totalQuantity > 0 ? totalQuantity : '-'}
                  </TableCell>
                );
              })}
              <TableCell align="right" sx={{ fontWeight: 'bold' }}>
                {formatCurrency(order.totalAmount)}
              </TableCell>
            </TableRow>
          ))}
          <OrderTotalsRow report={report} allOrders={allOrders} allProducts={allProducts} />
        </TableBody>
      </Table>
    </TableContainer>
  </Paper>
);

const OrderTotalsRow: React.FC<{
  report: UnitReport;
  allOrders: SellerOrder[];
  allProducts: string[];
}> = ({ report, allOrders, allProducts }) => {
  const productTotals = calculateProductTotalsForOrders(allOrders);
  return (
    <TableRow sx={{ bgcolor: 'action.hover' }}>
      <TableCell colSpan={2}>
        <strong>Total</strong>
      </TableCell>
      {allProducts.map((product) => (
        <TableCell key={product} align="center">
          <strong>{productTotals[product] || 0}</strong>
        </TableCell>
      ))}
      <TableCell align="right">
        <strong>{formatCurrency(report.totalSales)}</strong>
      </TableCell>
    </TableRow>
  );
};

const UnitSummarySection: React.FC<{
  report: UnitReport;
  totalItems: number;
  topSellers: UnitSellerSummary[];
}> = ({ report, totalItems, topSellers }) => (
  <Paper sx={{ p: 3 }}>
    <Stack spacing={3}>
      <Typography variant="h6">Unit Overview</Typography>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
        <Box flex={1}>
          <Typography variant="body2" color="text.secondary">
            Total Sellers
          </Typography>
          <Typography variant="h4">{report.sellers.length}</Typography>
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
          <Typography variant="h4">{formatCurrency(report.totalSales / report.sellers.length)}</Typography>
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
              <TableCell align="right">Items</TableCell>
              <TableCell align="right">Sales</TableCell>
              <TableCell align="right">% of Total</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {topSellers.map((seller, idx) => {
              const sellerItems = seller.orders.reduce((orderSum, order) => {
                return orderSum + order.lineItems.reduce((itemSum, item) => itemSum + item.quantity, 0);
              }, 0);

              return (
                <TableRow key={seller.profileId}>
                  <TableCell>{idx + 1}</TableCell>
                  <TableCell>{seller.sellerName}</TableCell>
                  <TableCell align="right">{sellerItems}</TableCell>
                  <TableCell align="right">{formatCurrency(seller.totalSales)}</TableCell>
                  <TableCell align="right">{((seller.totalSales / report.totalSales) * 100).toFixed(1)}%</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  </Paper>
);

export const CampaignReportsPage: React.FC = () => {
  const {
    campaigns,
    sharedCampaignsLoading,
    selectedSharedCampaignCode,
    setSelectedSharedCampaignCode,
    selectedCampaign,
    canGenerateReport,
    report,
    loading,
    error,
    reportView,
    setReportView,
    productList,
    allOrders,
    allProducts,
    totalItems,
    topSellers,
    handleGenerateReport,
    handleExportSellerReport,
    handleExportOrderDetails,
  } = useCampaignReportState();

  return (
    <Box sx={{ p: 3 }}>
      <Stack spacing={3}>
        <PageHeader />

        <CampaignSelectorCard
          campaigns={campaigns}
          selectedCode={selectedSharedCampaignCode}
          loading={sharedCampaignsLoading}
          selectedCampaign={selectedCampaign}
          onSelect={setSelectedSharedCampaignCode}
          onGenerate={handleGenerateReport}
          canGenerate={canGenerateReport}
          loadingReport={loading}
        />

        {error ? <Alert severity="error">Error loading report: {error.message}</Alert> : null}

        <ReportPanels
          report={report}
          reportView={reportView}
          onChangeView={setReportView}
          productList={productList}
          allOrders={allOrders}
          allProducts={allProducts}
          totalItems={totalItems}
          topSellers={topSellers}
          onExportSellerReport={handleExportSellerReport}
          onExportOrderDetails={handleExportOrderDetails}
        />
      </Stack>
    </Box>
  );
};

const useCampaignReportState = () => {
  const [reportView, setReportView] = useState<ReportView>('unit');

  const {
    campaigns,
    sharedCampaignsLoading,
    selectedSharedCampaignCode,
    setSelectedSharedCampaignCode,
    selectedCampaign,
    canGenerateReport,
  } = useSharedCampaignSelection();

  const { report, loading, error, refetch } = useUnitReport(selectedCampaign, canGenerateReport);
  const { productList, allOrders, allProducts, totalItems, topSellers } = useReportDerivatives(report);

  const { handleGenerateReport, handleExportSellerReport, handleExportOrderDetails } = useReportActions({
    canGenerateReport,
    refetch,
    report,
    productList,
    allOrders,
    allProducts,
  });

  return {
    campaigns,
    sharedCampaignsLoading,
    selectedSharedCampaignCode,
    setSelectedSharedCampaignCode,
    selectedCampaign,
    canGenerateReport,
    report,
    loading,
    error,
    reportView,
    setReportView,
    productList,
    allOrders,
    allProducts,
    totalItems,
    topSellers,
    handleGenerateReport,
    handleExportSellerReport,
    handleExportOrderDetails,
  };
};

const useSharedCampaignSelection = () => {
  const [selectedSharedCampaignCode, setSelectedSharedCampaignCode] = useState<string>('');

  const { data: sharedCampaignsData, loading: sharedCampaignsLoading } = useQuery<{
    listMySharedCampaigns: SharedCampaign[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  const campaigns = useMemo(() => getActiveCampaigns(sharedCampaignsData), [sharedCampaignsData]);

  useEffect(() => {
    if (campaigns.length === 1 && !selectedSharedCampaignCode) {
      setSelectedSharedCampaignCode(campaigns[0].sharedCampaignCode);
    }
  }, [campaigns, selectedSharedCampaignCode]);

  const selectedCampaign = useMemo(
    () => campaigns.find((campaign) => campaign.sharedCampaignCode === selectedSharedCampaignCode),
    [campaigns, selectedSharedCampaignCode],
  );

  return {
    campaigns,
    sharedCampaignsLoading,
    selectedSharedCampaignCode,
    setSelectedSharedCampaignCode,
    selectedCampaign,
    canGenerateReport: Boolean(selectedCampaign),
  };
};

// Helper: Extract unit report variables from campaign
const getUnitReportVariables = (campaign: SharedCampaign | undefined) => {
  if (!campaign) {
    return {
      unitType: undefined,
      unitNumber: undefined,
      city: undefined,
      state: undefined,
      campaignName: undefined,
      campaignYear: undefined,
      catalogId: undefined,
    };
  }
  return {
    unitType: campaign.unitType,
    unitNumber: campaign.unitNumber,
    city: campaign.city,
    state: campaign.state,
    campaignName: campaign.campaignName,
    campaignYear: campaign.campaignYear,
    catalogId: campaign.catalogId,
  };
};

const useUnitReport = (selectedCampaign: SharedCampaign | undefined, canGenerateReport: boolean) => {
  const variables = getUnitReportVariables(selectedCampaign);
  const { data, loading, error, refetch } = useQuery<{
    getUnitReport: UnitReport;
  }>(GET_UNIT_REPORT, {
    variables,
    skip: !canGenerateReport,
  });

  return { report: data?.getUnitReport, loading, error, refetch };
};

const useReportDerivatives = (report: UnitReport | undefined) =>
  useMemo(() => {
    const productList = getProductList(report);
    const allOrders = getAllOrders(report);

    return {
      productList,
      allOrders,
      allProducts: productList,
      totalItems: calculateTotalItems(report),
      topSellers: getTopSellers(report),
    };
  }, [report]);

// Helper: Create generate report handler
const createGenerateHandler = (canGenerate: boolean, refetch: () => Promise<unknown>) => {
  if (!canGenerate) return;
  refetch();
};

// Helper: Create export seller report handler
const createExportSellerHandler = (report: UnitReport | undefined, productList: string[]) => {
  if (!report || !productList.length) return;
  buildSellerReportWorkbook(report, productList);
};

// Helper: Create export order details handler
const createExportOrderHandler = (report: UnitReport | undefined, allOrders: SellerOrder[], allProducts: string[]) => {
  if (!report || !allOrders.length || !allProducts.length) return;
  buildOrderDetailsWorkbook(report, allOrders, allProducts);
};

const useReportActions = ({
  canGenerateReport,
  refetch,
  report,
  productList,
  allOrders,
  allProducts,
}: {
  canGenerateReport: boolean;
  refetch: () => Promise<unknown>;
  report: UnitReport | undefined;
  productList: string[];
  allOrders: SellerOrder[];
  allProducts: string[];
}) => {
  const handleGenerateReport = useCallback(
    () => createGenerateHandler(canGenerateReport, refetch),
    [canGenerateReport, refetch],
  );

  const handleExportSellerReport = useCallback(
    () => createExportSellerHandler(report, productList),
    [productList, report],
  );

  const handleExportOrderDetails = useCallback(
    () => createExportOrderHandler(report, allOrders, allProducts),
    [allOrders, allProducts, report],
  );

  return {
    handleGenerateReport,
    handleExportSellerReport,
    handleExportOrderDetails,
  };
};

const PageHeader: React.FC = () => (
  <Box>
    <Typography variant="h4" component="h1" gutterBottom>
      <ReportIcon sx={{ mr: 1, verticalAlign: 'bottom' }} />
      Shared Campaign Reports
    </Typography>
    <Typography variant="body2" color="text.secondary">
      View aggregated sales data for all sellers in your shared campaigns
    </Typography>
  </Box>
);

const ReportPanels: React.FC<{
  report?: UnitReport;
  reportView: ReportView;
  onChangeView: (view: ReportView) => void;
  productList: string[];
  allOrders: SellerOrder[];
  allProducts: string[];
  totalItems: number;
  topSellers: UnitSellerSummary[];
  onExportSellerReport: () => void;
  onExportOrderDetails: () => void;
}> = ({
  report,
  reportView,
  onChangeView,
  productList,
  allOrders,
  allProducts,
  totalItems,
  topSellers,
  onExportSellerReport,
  onExportOrderDetails,
}) => {
  if (!report) return null;

  const hasSellers = report.sellers.length > 0;

  return (
    <>
      <ReportHeaderCard report={report} hasSellers={hasSellers} />
      {hasSellers ? (
        <ReportViewContent
          report={report}
          reportView={reportView}
          onChangeView={onChangeView}
          productList={productList}
          allOrders={allOrders}
          allProducts={allProducts}
          totalItems={totalItems}
          topSellers={topSellers}
          onExportSellerReport={onExportSellerReport}
          onExportOrderDetails={onExportOrderDetails}
        />
      ) : null}
    </>
  );
};

const ReportHeaderCard: React.FC<{
  report: UnitReport;
  hasSellers: boolean;
}> = ({ report, hasSellers }) => (
  <Paper sx={{ p: 3 }}>
    <Stack spacing={2}>
      <Typography variant="h5">
        {report.unitType} {report.unitNumber} - {report.campaignName} {report.campaignYear}
      </Typography>
      <ReportSummaryChips report={report} />
      {!hasSellers && (
        <Alert severity="info">
          No sales data found for this unit in {report.campaignYear}. Make sure sellers have set their unit type and
          number on their profiles.
        </Alert>
      )}
    </Stack>
  </Paper>
);

const ReportViewContent: React.FC<{
  report: UnitReport;
  reportView: ReportView;
  onChangeView: (view: ReportView) => void;
  productList: string[];
  allOrders: SellerOrder[];
  allProducts: string[];
  totalItems: number;
  topSellers: UnitSellerSummary[];
  onExportSellerReport: () => void;
  onExportOrderDetails: () => void;
}> = ({
  report,
  reportView,
  onChangeView,
  productList,
  allOrders,
  allProducts,
  totalItems,
  topSellers,
  onExportSellerReport,
  onExportOrderDetails,
}) => {
  const viewContent: Record<ReportView, React.ReactNode> = {
    summary: <SellerReportSection report={report} productList={productList} onExport={onExportSellerReport} />,
    detailed: (
      <OrderDetailsSection
        report={report}
        allOrders={allOrders}
        allProducts={allProducts}
        onExport={onExportOrderDetails}
      />
    ),
    unit: <UnitSummarySection report={report} totalItems={totalItems} topSellers={topSellers} />,
  };

  return (
    <>
      <ReportViewSelector view={reportView} onChange={onChangeView} />
      {viewContent[reportView]}
    </>
  );
};
