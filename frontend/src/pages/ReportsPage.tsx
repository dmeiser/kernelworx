/**
 * ReportsPage - Generate and download campaign reports
 */

import React from 'react';
import { useParams } from 'react-router-dom';
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
  useMediaQuery,
  useTheme,
} from '@mui/material';
import {
  Download as DownloadIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
} from '@mui/icons-material';
import { LIST_ORDERS_BY_CAMPAIGN } from '../lib/graphql';
import { ensureCampaignId } from '../lib/ids';
import { downloadAsCSV, downloadAsXLSX } from '../lib/reportExport';

// Helper to format city/state/zip into a single string
const formatCityStateZip = (address: Order['customerAddress']): string =>
  [address?.city, address?.state, address?.zipCode].filter(Boolean).join(' ');

// Helper to check if address has displayable content
const hasAddressContent = (street: boolean, cityStateZip: string): boolean => street || Boolean(cityStateZip);

// Helper component to render customer address
const CustomerAddressCell: React.FC<{
  address: Order['customerAddress'];
}> = ({ address }) => {
  if (!address) return <>-</>;

  const cityStateZip = formatCityStateZip(address);
  const hasStreet = Boolean(address.street);

  if (!hasAddressContent(hasStreet, cityStateZip)) return <>-</>;

  return (
    <Box sx={{ fontSize: '0.875rem' }}>
      {hasStreet && <div>{address.street}</div>}
      {cityStateZip && <div>{cityStateZip}</div>}
    </Box>
  );
};

// Helper to safely decode URL component
const decodeUrlParam = (encoded: string | undefined): string => (encoded ? decodeURIComponent(encoded) : '');

// Helper to get orders from query data
const getOrdersFromData = (data: { listOrdersByCampaign: Order[] } | undefined): Order[] =>
  data?.listOrdersByCampaign || [];

// Helper to determine if query should be skipped
const shouldSkipQuery = (id: string): boolean => !id;

// Helper to get all unique products from orders
const getAllProducts = (orders: Order[]): string[] =>
  Array.from(new Set(orders.flatMap((order) => order.lineItems.map((item) => item.productName)))).sort();

// Helper component for order table content
const OrderTableContent: React.FC<{
  orders: Order[];
  ordersLoading: boolean;
}> = ({ orders, ordersLoading }) => {
  if (ordersLoading) {
    return (
      <Box display="flex" justifyContent="center" py={4}>
        <CircularProgress />
      </Box>
    );
  }

  if (orders.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No orders found for this campaign.
      </Typography>
    );
  }

  const allProducts = getAllProducts(orders);

  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: 'action.hover' }}>
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
            <OrderRow key={order.orderId} order={order} allProducts={allProducts} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

// Helper component for single order row
const OrderRow: React.FC<{ order: Order; allProducts: string[] }> = ({ order, allProducts }) => (
  <TableRow>
    <TableCell>{order.customerName}</TableCell>
    <TableCell>{formatPhone(order.customerPhone)}</TableCell>
    <TableCell>
      <CustomerAddressCell address={order.customerAddress} />
    </TableCell>
    {allProducts.map((product) => {
      const totalQuantity = order.lineItems
        .filter((li) => li.productName === product)
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
);

// Helper component for download buttons
const DownloadButtons: React.FC<{ orders: Order[]; campaignId: string }> = ({ orders, campaignId }) => {
  if (orders.length === 0) return null;
  return (
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
  );
};

// Helper component for mobile warning
const MobileWarning: React.FC<{ show: boolean }> = ({ show }) => {
  if (!show) return null;
  return (
    <Box
      mb={3}
      sx={{
        p: { xs: 1, sm: 2 },
        bgcolor: '#e3f2fd',
        borderRadius: 1,
      }}
    >
      <Typography variant="body2" sx={{ color: '#1976d2' }}>
        💡 <strong>Note:</strong> The order table below is designed for desktop viewing. For the best experience viewing
        and editing detailed order data, please use a larger screen.
      </Typography>
    </Box>
  );
};

// Helper to format currency
const formatCurrency = (amount: number): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount);

// Helper to format phone number
const formatPhone = (phone: string | undefined): string => {
  if (!phone) return '-';
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 11) {
    const last10 = digits.slice(-10);
    return `(${last10.slice(0, 3)}) ${last10.slice(3, 6)}-${last10.slice(6)}`;
  }
  return phone;
};

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
  const campaignId = decodeUrlParam(encodedCampaignId);
  const dbCampaignId = ensureCampaignId(campaignId);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  // About Reports collapse state - collapsed on mobile by default, expanded on desktop
  const [aboutExpanded, setAboutExpanded] = React.useState(!isMobile);

  // Update when screen size changes
  React.useEffect(() => {
    setAboutExpanded(!isMobile);
  }, [isMobile]);

  // Report format option (currently defaults to XLSX)
  const reportFormat: 'CSV' | 'XLSX' = 'XLSX';
  void reportFormat; // Used for future report format selection

  const { data: ordersData, loading: ordersLoading } = useQuery<{
    listOrdersByCampaign: Order[];
  }>(LIST_ORDERS_BY_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: shouldSkipQuery(dbCampaignId),
  });

  const orders = getOrdersFromData(ordersData);

  return (
    <Box sx={{ width: '100%' }}>
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
            '& li': {
              typography: 'body2',
              mb: 1,
            },
          }}
        >
          <li>
            <strong>Excel (XLSX):</strong> Formatted spreadsheet with product columns, suitable for further analysis and
            pivot tables.
          </li>
          <li>
            <strong>CSV:</strong> Plain text file, compatible with all spreadsheet programs and databases.
          </li>
        </Box>
      </Paper>

      {/* Mobile Warning */}
      <MobileWarning show={isMobile} />

      {/* Complete Order Table - Collapsible */}
      <Box mb={3}>
        <Button
          onClick={() => setAboutExpanded(!aboutExpanded)}
          startIcon={aboutExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          sx={{ mb: 1 }}
          size="small"
        >
          {aboutExpanded ? 'Hide Order Table' : 'Show Order Table'}
        </Button>
        {aboutExpanded && (
          <Box sx={{ width: '100%', overflowX: 'auto' }}>
            {/* Complete Order Table */}
            <Paper sx={{ p: { xs: 1.5, sm: 3 }, mt: 3 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h6">All Orders</Typography>
                <DownloadButtons orders={orders} campaignId={campaignId} />
              </Stack>

              <OrderTableContent orders={orders} ordersLoading={ordersLoading} />
            </Paper>
          </Box>
        )}
      </Box>
    </Box>
  );
};
