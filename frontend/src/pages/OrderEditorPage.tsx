/**
 * OrderEditorPage - Page for creating or editing an order
 */

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  Box,
  Button,
  TextField,
  Stack,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  IconButton,
  Divider,
  Alert,
  Paper,
  CircularProgress,
  Breadcrumbs,
  Link,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import {
  Add as AddIcon,
  Delete as DeleteIcon,
  ArrowBack as ArrowBackIcon,
  QrCode as QrCodeIcon,
} from '@mui/icons-material';
import {
  CREATE_ORDER,
  UPDATE_ORDER,
  GET_ORDER,
  GET_CAMPAIGN,
  GET_PROFILE,
  GET_PAYMENT_METHODS_FOR_PROFILE,
} from '../lib/graphql';
import { QrCodeImage } from '../components/QrCodeImage';
import { StateAutocomplete } from '../components/StateAutocomplete';
import { ensureProfileId, ensureCampaignId, ensureOrderId, toUrlId } from '../lib/ids';
import { useOrderForm, type OrderFormState, type LineItemInput } from '../hooks/useOrderForm';
import type { Product, Catalog, OrderAddress } from '../types';

// Payment method interface for dynamic payment methods
interface PaymentMethodOption {
  name: string;
  qrCodeUrl: string | null;
}

// ============================================================================
// Types (page-specific types not in shared entities)
// ============================================================================

interface CampaignData {
  campaignId: string;
  catalog?: Catalog;
}

interface ProfileData {
  profileId: string;
  isOwner: boolean;
  permissions?: string[];
}

interface OrderLineItem {
  productId: string;
  quantity: number;
}

interface OrderData {
  orderId: string;
  customerName?: string;
  customerPhone?: string;
  customerAddress?: OrderAddress;
  paymentMethod?: string;
  notes?: string;
  lineItems: OrderLineItem[];
}

// ============================================================================
// Helper Functions
// ============================================================================

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount);
}

function formatPhoneNumber(phone: string): string {
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) {
    return `(${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7, 11)}`;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6, 10)}`;
  }
  return phone;
}

function calculateTotal(lineItems: LineItemInput[], products: Product[]): number {
  return lineItems.reduce((sum, item) => {
    const product = products.find((p) => p.productId === item.productId);
    return sum + (product?.price || 0) * item.quantity;
  }, 0);
}

// ============================================================================
// Validation
// ============================================================================

interface ValidationResult {
  isValid: boolean;
  error?: string;
  validLineItems: LineItemInput[];
}

function validateOrderForm(customerName: string, lineItems: LineItemInput[]): ValidationResult {
  if (!customerName.trim()) {
    return {
      isValid: false,
      error: 'Customer name is required',
      validLineItems: [],
    };
  }

  const validLineItems = lineItems.filter((item) => item.productId && item.quantity > 0);

  if (validLineItems.length === 0) {
    return {
      isValid: false,
      error: 'At least one product is required',
      validLineItems: [],
    };
  }

  return { isValid: true, validLineItems };
}

/**
 * Gets the default payment method name.
 * Prefers "Cash" if available, otherwise uses the first method.
 */
function getDefaultPaymentMethodName(paymentMethods: PaymentMethodOption[]): string {
  const cashMethod = paymentMethods.find((m) => m.name === 'Cash');
  if (cashMethod) return 'Cash';
  return paymentMethods[0]?.name ?? '';
}

/**
 * Sets the default payment method when payment methods load.
 * Only sets default if no existing payment method is selected.
 */
function setDefaultPaymentMethod(
  paymentMethods: PaymentMethodOption[],
  orderData: OrderData | undefined,
  formState: OrderFormState,
): void {
  const shouldSetDefault = paymentMethods.length > 0 && !orderData && !formState.paymentMethod;
  if (!shouldSetDefault) return;

  formState.setPaymentMethod(getDefaultPaymentMethodName(paymentMethods));
}

// ============================================================================
// Input Builders
// ============================================================================

interface AddressInput {
  street: string | null;
  city: string | null;
  state: string | null;
  zipCode: string | null;
}

function trimOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed || null;
}

function buildAddressInput(formState: OrderFormState): AddressInput | null {
  const { street, city, state, zipCode } = formState;
  const hasAddress = street || city || state || zipCode;
  if (!hasAddress) {
    return null;
  }
  return {
    street: trimOrNull(street),
    city: trimOrNull(city),
    state: trimOrNull(state),
    zipCode: trimOrNull(zipCode),
  };
}

function buildCreateOrderInput(
  formState: OrderFormState,
  dbProfileId: string,
  dbCampaignId: string,
  validLineItems: LineItemInput[],
) {
  return {
    profileId: dbProfileId,
    campaignId: dbCampaignId,
    customerName: formState.customerName.trim(),
    customerPhone: formState.customerPhone.trim() || null,
    customerAddress: buildAddressInput(formState),
    orderDate: new Date().toISOString(),
    paymentMethod: formState.paymentMethod,
    lineItems: validLineItems,
    notes: formState.notes.trim() || null,
  };
}

function buildUpdateOrderInput(formState: OrderFormState, dbOrderId: string | null, validLineItems: LineItemInput[]) {
  if (!dbOrderId) {
    throw new Error('Order ID is required for update');
  }
  return {
    orderId: dbOrderId,
    customerName: formState.customerName.trim(),
    customerPhone: formState.customerPhone.trim() || null,
    customerAddress: buildAddressInput(formState),
    paymentMethod: formState.paymentMethod,
    lineItems: validLineItems,
    notes: formState.notes.trim() || null,
  };
}

// ============================================================================
// Sub-Components
// ============================================================================

interface OrderBreadcrumbsProps {
  profileId: string;
  onNavigate: (path: string) => void;
  onCancel: () => void;
  isEditing: boolean;
}

const OrderBreadcrumbs: React.FC<OrderBreadcrumbsProps> = ({ profileId, onNavigate, onCancel, isEditing }) => (
  <Breadcrumbs sx={{ mb: 2 }}>
    <Link
      component="button"
      variant="body2"
      onClick={() => onNavigate('/scouts')}
      sx={{ textDecoration: 'none', cursor: 'pointer' }}
    >
      Profiles
    </Link>
    <Link
      component="button"
      variant="body2"
      onClick={() => onNavigate(`/scouts/${toUrlId(profileId)}/campaigns`)}
      sx={{ textDecoration: 'none', cursor: 'pointer' }}
    >
      Campaigns
    </Link>
    <Link component="button" variant="body2" onClick={onCancel} sx={{ textDecoration: 'none', cursor: 'pointer' }}>
      Orders
    </Link>
    <Typography variant="body2" color="text.primary">
      {isEditing ? 'Edit Order' : 'New Order'}
    </Typography>
  </Breadcrumbs>
);

interface CustomerInfoFormProps {
  formState: OrderFormState;
  loading: boolean;
}

const CustomerInfoForm: React.FC<CustomerInfoFormProps> = ({ formState, loading }) => {
  const handlePhoneBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    formState.setCustomerPhone(formatPhoneNumber(e.target.value));
  };

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Customer Information
      </Typography>
      <Stack spacing={2}>
        <TextField
          fullWidth
          label="Customer Name"
          value={formState.customerName}
          onChange={(e) => formState.setCustomerName(e.target.value)}
          required
          disabled={loading}
        />
        <TextField
          fullWidth
          label="Phone Number"
          value={formState.customerPhone}
          onChange={(e) => formState.setCustomerPhone(e.target.value)}
          onBlur={handlePhoneBlur}
          placeholder="(555) 123-4567"
          disabled={loading}
        />
        <TextField
          fullWidth
          label="Street Address"
          value={formState.street}
          onChange={(e) => formState.setStreet(e.target.value)}
          disabled={loading}
        />
        <Stack direction="row" spacing={2}>
          <TextField
            fullWidth
            label="City"
            value={formState.city}
            onChange={(e) => formState.setCity(e.target.value)}
            disabled={loading}
          />
          <StateAutocomplete
            value={formState.state}
            onChange={formState.setState}
            disabled={loading}
            sx={{ width: 100 }}
          />
          <TextField
            label="Zip Code"
            value={formState.zipCode}
            onChange={(e) => formState.setZipCode(e.target.value)}
            sx={{ width: 120 }}
            disabled={loading}
          />
        </Stack>
      </Stack>
    </Paper>
  );
};

interface LineItemRowProps {
  item: LineItemInput;
  index: number;
  products: Product[];
  loading: boolean;
  canRemove: boolean;
  onProductChange: (value: string) => void;
  onQuantityChange: (value: string) => void;
  onRemove: () => void;
}

const LineItemRow: React.FC<LineItemRowProps> = ({
  item,
  index,
  products,
  loading,
  canRemove,
  onProductChange,
  onQuantityChange,
  onRemove,
}) => {
  const product = products.find((p) => p.productId === item.productId);
  const subtotal = product ? product.price * item.quantity : 0;

  return (
    <TableRow key={index}>
      <TableCell>
        <Select
          fullWidth
          value={item.productId}
          onChange={(e) => onProductChange(e.target.value)}
          disabled={loading}
          size="small"
        >
          {products.map((p) => (
            <MenuItem key={p.productId} value={p.productId}>
              {p.productName}
            </MenuItem>
          ))}
        </Select>
      </TableCell>
      <TableCell align="right">
        <TextField
          type="number"
          value={item.quantity}
          onChange={(e) => onQuantityChange(e.target.value)}
          disabled={loading}
          size="small"
          sx={{ width: 80 }}
          inputProps={{ min: 1, max: 99999, step: 1 }}
        />
      </TableCell>
      <TableCell align="right">{product ? formatCurrency(product.price) : '—'}</TableCell>
      <TableCell align="right">{formatCurrency(subtotal)}</TableCell>
      <TableCell align="right">
        <IconButton size="small" onClick={onRemove} disabled={loading || !canRemove} color="error">
          <DeleteIcon fontSize="small" />
        </IconButton>
      </TableCell>
    </TableRow>
  );
};

interface LineItemsTableProps {
  lineItems: LineItemInput[];
  products: Product[];
  loading: boolean;
  onAddItem: () => void;
  onRemoveItem: (index: number) => void;
  onItemChange: (index: number, field: 'productId' | 'quantity', value: string) => void;
}

const LineItemsTable: React.FC<LineItemsTableProps> = ({
  lineItems,
  products,
  loading,
  onAddItem,
  onRemoveItem,
  onItemChange,
}) => {
  const total = calculateTotal(lineItems, products);
  const canRemoveItems = lineItems.length > 1;

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">Products</Typography>
        <Button startIcon={<AddIcon />} onClick={onAddItem} disabled={loading}>
          Add Product
        </Button>
      </Stack>

      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell align="right">Quantity</TableCell>
            <TableCell align="right">Price</TableCell>
            <TableCell align="right">Subtotal</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {lineItems.map((item, index) => (
            <LineItemRow
              key={index}
              item={item}
              index={index}
              products={products}
              loading={loading}
              canRemove={canRemoveItems}
              onProductChange={(v) => onItemChange(index, 'productId', v)}
              onQuantityChange={(v) => onItemChange(index, 'quantity', v)}
              onRemove={() => onRemoveItem(index)}
            />
          ))}
        </TableBody>
      </Table>

      <Divider sx={{ my: 2 }} />

      <Box display="flex" justifyContent="flex-end">
        <Typography variant="h6">Total: {formatCurrency(total)}</Typography>
      </Box>
    </Paper>
  );
};

// ============================================================================
// QR Preview Modal
// ============================================================================

interface QRPreviewModalProps {
  open: boolean;
  onClose: () => void;
  qrCodeUrl: string | null;
  methodName: string;
}

const QRPreviewModal: React.FC<QRPreviewModalProps> = ({ open, onClose, qrCodeUrl, methodName }) => (
  <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
    <DialogTitle>Payment QR Code - {methodName}</DialogTitle>
    <DialogContent>
      <QrCodeImage qrCodeUrl={qrCodeUrl} methodName={methodName} maxHeight={300} />
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose}>Close</Button>
    </DialogActions>
  </Dialog>
);

// ============================================================================
// Payment Notes Form
// ============================================================================

function renderPaymentMethodOptions(
  paymentMethods: PaymentMethodOption[],
  paymentMethodsLoading: boolean,
): React.ReactNode[] {
  if (paymentMethodsLoading) {
    return [
      <MenuItem key="loading" value="" disabled>
        Loading...
      </MenuItem>,
    ];
  }
  if (paymentMethods.length === 0) {
    return [
      <MenuItem key="empty" value="" disabled>
        No payment methods available
      </MenuItem>,
    ];
  }
  return paymentMethods.map((method) => (
    <MenuItem key={method.name} value={method.name}>
      {method.name}
    </MenuItem>
  ));
}

// QR button with modal for payment method form
interface QRButtonWithModalProps {
  selectedMethod: PaymentMethodOption | null;
  canViewQR: boolean;
}

function useShowQRButton(selectedMethod: PaymentMethodOption | null, canViewQR: boolean): boolean {
  const hasQRCode = selectedMethod?.qrCodeUrl != null;
  return canViewQR && hasQRCode;
}

function getQRModalData(selectedMethod: PaymentMethodOption | null): { qrCodeUrl: string | null; methodName: string } {
  return {
    qrCodeUrl: selectedMethod?.qrCodeUrl ?? null,
    methodName: selectedMethod?.name ?? '',
  };
}

const QRButtonWithModal: React.FC<QRButtonWithModalProps> = ({ selectedMethod, canViewQR }) => {
  const [qrModalOpen, setQrModalOpen] = useState(false);
  const showQRButton = useShowQRButton(selectedMethod, canViewQR);

  if (!showQRButton) return null;

  const { qrCodeUrl, methodName } = getQRModalData(selectedMethod);

  return (
    <>
      <IconButton onClick={() => setQrModalOpen(true)} color="primary" aria-label="View QR code" sx={{ mt: 1 }}>
        <QrCodeIcon />
      </IconButton>
      <QRPreviewModal
        open={qrModalOpen}
        onClose={() => setQrModalOpen(false)}
        qrCodeUrl={qrCodeUrl}
        methodName={methodName}
      />
    </>
  );
};

interface PaymentNotesFormProps {
  paymentMethod: string;
  setPaymentMethod: (value: string) => void;
  notes: string;
  setNotes: (value: string) => void;
  loading: boolean;
  paymentMethods: PaymentMethodOption[];
  paymentMethodsLoading: boolean;
  canViewQR: boolean;
}

const PaymentNotesForm: React.FC<PaymentNotesFormProps> = ({
  paymentMethod,
  setPaymentMethod,
  notes,
  setNotes,
  loading,
  paymentMethods,
  paymentMethodsLoading,
  canViewQR,
}) => {
  const selectedMethod = paymentMethods.find((m) => m.name === paymentMethod) ?? null;
  // Only disable based on mutation loading, NOT query loading
  // If payment methods query fails, user should still be able to interact with the form
  const isFormDisabled = loading;

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Payment & Notes
      </Typography>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} alignItems="flex-start">
          <FormControl fullWidth disabled={isFormDisabled}>
            <InputLabel>Payment Method</InputLabel>
            <Select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)} label="Payment Method">
              {renderPaymentMethodOptions(paymentMethods, paymentMethodsLoading)}
            </Select>
          </FormControl>
          <QRButtonWithModal selectedMethod={selectedMethod} canViewQR={canViewQR} />
        </Stack>
        <TextField
          fullWidth
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          multiline
          rows={3}
          disabled={loading}
        />
      </Stack>
    </Paper>
  );
};

interface OrderHeaderProps {
  isEditing: boolean;
  onCancel: () => void;
}

const OrderHeader: React.FC<OrderHeaderProps> = ({ isEditing, onCancel }) => (
  <Stack direction="row" alignItems="center" spacing={2} mb={3}>
    <IconButton onClick={onCancel} edge="start">
      <ArrowBackIcon />
    </IconButton>
    <Typography variant="h4">{isEditing ? 'Edit Order' : 'Create Order'}</Typography>
  </Stack>
);

interface OrderErrorAlertProps {
  error: string | null;
  onClose: () => void;
}

const OrderErrorAlert: React.FC<OrderErrorAlertProps> = ({ error, onClose }) => {
  if (!error) {
    return null;
  }
  return (
    <Alert severity="error" sx={{ mb: 3 }} onClose={onClose}>
      {error}
    </Alert>
  );
};

interface OrderActionsProps {
  isEditing: boolean;
  loading: boolean;
  customerName: string;
  hasValidPaymentMethod: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}

const OrderActions: React.FC<OrderActionsProps> = ({
  isEditing,
  loading,
  customerName,
  hasValidPaymentMethod,
  onCancel,
  onSubmit,
}) => {
  const submitLabel = getSubmitLabel(isEditing, loading);
  const isDisabled = loading || !customerName.trim() || !hasValidPaymentMethod;
  return (
    <Stack direction="row" spacing={2} justifyContent="flex-end">
      <Button onClick={onCancel} disabled={loading}>
        Cancel
      </Button>
      <Button variant="contained" onClick={onSubmit} disabled={isDisabled}>
        {submitLabel}
      </Button>
    </Stack>
  );
};

function getSubmitLabel(isEditing: boolean, loading: boolean): string {
  if (loading) {
    return isEditing ? 'Updating...' : 'Creating...';
  }
  return isEditing ? 'Update Order' : 'Create Order';
}

// ============================================================================
// URL Parsing Helper
// ============================================================================

interface ParsedOrderParams {
  profileId: string;
  campaignId: string;
  orderId: string | null;
  dbProfileId: string;
  dbCampaignId: string;
  dbOrderId: string | null;
  isEditing: boolean;
  ordersUrl: string;
}

function parseOrderParams(params: { profileId?: string; campaignId?: string; orderId?: string }): ParsedOrderParams {
  const profileId = params.profileId ? decodeURIComponent(params.profileId) : '';
  const campaignId = params.campaignId ? decodeURIComponent(params.campaignId) : '';
  const orderId = params.orderId ? decodeURIComponent(params.orderId) : null;
  return {
    profileId,
    campaignId,
    orderId,
    dbProfileId: ensureProfileId(profileId)!,
    dbCampaignId: ensureCampaignId(campaignId)!,
    dbOrderId: orderId ? ensureOrderId(orderId)! : null,
    isEditing: !!orderId,
    ordersUrl: `/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(campaignId)}/orders`,
  };
}

// ============================================================================
// Submit Handler
// ============================================================================

interface SubmitOrderParams {
  formState: OrderFormState;
  urlParams: ParsedOrderParams;
  createOrder: (options: { variables: { input: ReturnType<typeof buildCreateOrderInput> } }) => Promise<unknown>;
  updateOrder: (options: { variables: { input: ReturnType<typeof buildUpdateOrderInput> } }) => Promise<unknown>;
  navigate: (path: string) => void;
}

async function submitOrder({
  formState,
  urlParams,
  createOrder,
  updateOrder,
  navigate,
}: SubmitOrderParams): Promise<void> {
  formState.setError(null);

  const validation = validateOrderForm(formState.customerName, formState.lineItems);
  if (!validation.isValid) {
    formState.setError(validation.error!);
    return;
  }

  formState.setLoading(true);

  try {
    await executeOrderMutation(formState, urlParams, validation.validLineItems, createOrder, updateOrder);
    navigate(urlParams.ordersUrl);
  } catch (err: unknown) {
    const error = err as { message?: string };
    formState.setError(error.message || 'Failed to save order');
    // Note: loading state is now handled by mutation onError callback
  }
}

async function executeOrderMutation(
  formState: OrderFormState,
  urlParams: ParsedOrderParams,
  validLineItems: LineItemInput[],
  createOrder: SubmitOrderParams['createOrder'],
  updateOrder: SubmitOrderParams['updateOrder'],
): Promise<void> {
  if (urlParams.isEditing) {
    const input = buildUpdateOrderInput(formState, urlParams.dbOrderId, validLineItems);
    await updateOrder({ variables: { input } });
  } else {
    const input = buildCreateOrderInput(formState, urlParams.dbProfileId, urlParams.dbCampaignId, validLineItems);
    await createOrder({ variables: { input } });
  }
}

// ============================================================================
// Main Component
// ============================================================================
// Data Fetching Hook
// ============================================================================

interface UseOrderDataResult {
  products: Product[];
  hasWritePermission: boolean;
  isOwnerOrWrite: boolean;
  paymentMethods: PaymentMethodOption[];
  paymentMethodsLoading: boolean;
  orderLoading: boolean;
  orderData: OrderData | undefined;
}

function extractProducts(campaignData: { getCampaign: CampaignData } | undefined): Product[] {
  return campaignData?.getCampaign?.catalog?.products ?? [];
}

function checkWritePermission(profileData: { getProfile: ProfileData } | undefined): boolean {
  const profile = profileData?.getProfile;
  if (!profile) {
    return false;
  }
  return profile.isOwner || hasWriteInPermissions(profile.permissions);
}

function checkIsOwnerOrWrite(profileData: { getProfile: ProfileData } | undefined): boolean {
  const profile = profileData?.getProfile;
  if (!profile) {
    return false;
  }
  return profile.isOwner || hasWriteInPermissions(profile.permissions);
}

function hasWriteInPermissions(permissions: string[] | undefined): boolean {
  return permissions?.includes('WRITE') ?? false;
}

function useOrderData(urlParams: ParsedOrderParams): UseOrderDataResult {
  const { data: campaignData } = useQuery<{ getCampaign: CampaignData }>(GET_CAMPAIGN, {
    variables: { campaignId: urlParams.dbCampaignId },
    skip: !urlParams.dbCampaignId,
  });

  const { data: profileData } = useQuery<{ getProfile: ProfileData }>(GET_PROFILE, {
    variables: { profileId: urlParams.dbProfileId },
    skip: !urlParams.dbProfileId,
  });

  const { data: orderData, loading: orderLoading } = useQuery<{
    getOrder: OrderData;
  }>(GET_ORDER, {
    variables: { orderId: urlParams.dbOrderId },
    skip: !urlParams.dbOrderId,
  });

  const { data: paymentMethodsData, loading: paymentMethodsLoading } = useQuery<{
    paymentMethodsForProfile: PaymentMethodOption[];
  }>(GET_PAYMENT_METHODS_FOR_PROFILE, {
    variables: { profileId: urlParams.dbProfileId },
    skip: !urlParams.dbProfileId,
  });

  return {
    products: extractProducts(campaignData),
    hasWritePermission: checkWritePermission(profileData),
    isOwnerOrWrite: checkIsOwnerOrWrite(profileData),
    paymentMethods: paymentMethodsData?.paymentMethodsForProfile ?? [],
    paymentMethodsLoading,
    orderLoading,
    orderData: orderData?.getOrder,
  };
}

// ============================================================================
// Loading and Error States
// ============================================================================

interface LoadingSpinnerProps {
  show: boolean;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ show }) => {
  if (!show) {
    return null;
  }
  return (
    <Box display="flex" justifyContent="center" py={4}>
      <CircularProgress />
    </Box>
  );
};

interface PermissionErrorProps {
  hasPermission: boolean;
}

const PermissionError: React.FC<PermissionErrorProps> = ({ hasPermission }) => {
  if (hasPermission) {
    return null;
  }
  return <Alert severity="error">You don't have permission to edit orders</Alert>;
};

// ============================================================================
// Main Component
// ============================================================================

export const OrderEditorPage: React.FC = () => {
  const params = useParams<{
    profileId: string;
    campaignId: string;
    orderId?: string;
  }>();
  const navigate = useNavigate();
  const urlParams = parseOrderParams(params);
  const formState = useOrderForm();
  const {
    products,
    hasWritePermission,
    isOwnerOrWrite,
    paymentMethods,
    paymentMethodsLoading,
    orderLoading,
    orderData,
  } = useOrderData(urlParams);

  const [createOrder] = useMutation(CREATE_ORDER, {
    onCompleted: () => {
      formState.setLoading(false);
    },
    onError: (error) => {
      formState.setError(error.message || 'Failed to create order');
      formState.setLoading(false);
    },
  });
  const [updateOrder] = useMutation(UPDATE_ORDER, {
    onCompleted: () => {
      formState.setLoading(false);
    },
    onError: (error) => {
      formState.setError(error.message || 'Failed to update order');
      formState.setLoading(false);
    },
  });

  useEffect(() => {
    if (!orderData) {
      return;
    }
    formState.loadFromOrder(orderData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderData]);

  // Set default payment method to "Cash" when payment methods load
  useEffect(() => {
    setDefaultPaymentMethod(paymentMethods, orderData, formState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paymentMethods, orderData]);

  const handleCancel = () => navigate(urlParams.ordersUrl);

  const handleSubmit = () => {
    // Validate payment method exists before submitting
    const methodExists = paymentMethods.some((m) => m.name === formState.paymentMethod);
    if (!methodExists) {
      formState.setError('Please select a valid payment method');
      return;
    }
    void submitOrder({
      formState,
      urlParams,
      createOrder,
      updateOrder,
      navigate,
    });
  };

  if (orderLoading) {
    return <LoadingSpinner show />;
  }

  if (!hasWritePermission) {
    return <PermissionError hasPermission={false} />;
  }

  return (
    <OrderEditorContent
      urlParams={urlParams}
      formState={formState}
      products={products}
      paymentMethods={paymentMethods}
      paymentMethodsLoading={paymentMethodsLoading}
      isOwnerOrWrite={isOwnerOrWrite}
      navigate={navigate}
      handleCancel={handleCancel}
      handleSubmit={handleSubmit}
    />
  );
};

// ============================================================================
// Order Editor Content
// ============================================================================

interface OrderEditorContentProps {
  urlParams: ParsedOrderParams;
  formState: OrderFormState;
  products: Product[];
  paymentMethods: PaymentMethodOption[];
  paymentMethodsLoading: boolean;
  isOwnerOrWrite: boolean;
  navigate: (path: string) => void;
  handleCancel: () => void;
  handleSubmit: () => void;
}

const OrderEditorContent: React.FC<OrderEditorContentProps> = ({
  urlParams,
  formState,
  products,
  paymentMethods,
  paymentMethodsLoading,
  isOwnerOrWrite,
  navigate,
  handleCancel,
  handleSubmit,
}) => {
  const hasValidPaymentMethod = paymentMethods.some((m) => m.name === formState.paymentMethod);

  return (
    <Box>
      <OrderBreadcrumbs
        profileId={urlParams.profileId}
        onNavigate={navigate}
        onCancel={handleCancel}
        isEditing={urlParams.isEditing}
      />

      <OrderHeader isEditing={urlParams.isEditing} onCancel={handleCancel} />

      <OrderErrorAlert error={formState.error} onClose={() => formState.setError(null)} />

      <CustomerInfoForm formState={formState} loading={formState.loading} />

      <LineItemsTable
        lineItems={formState.lineItems}
        products={products}
        loading={formState.loading}
        onAddItem={formState.addLineItem}
        onRemoveItem={formState.removeLineItem}
        onItemChange={formState.updateLineItem}
      />

      <PaymentNotesForm
        paymentMethod={formState.paymentMethod}
        setPaymentMethod={formState.setPaymentMethod}
        notes={formState.notes}
        setNotes={formState.setNotes}
        loading={formState.loading}
        paymentMethods={paymentMethods}
        paymentMethodsLoading={paymentMethodsLoading}
        canViewQR={isOwnerOrWrite}
      />

      <OrderActions
        isEditing={urlParams.isEditing}
        loading={formState.loading}
        customerName={formState.customerName}
        hasValidPaymentMethod={hasValidPaymentMethod}
        onCancel={handleCancel}
        onSubmit={handleSubmit}
      />
    </Box>
  );
};
