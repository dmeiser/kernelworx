/**
 * OrderEditorDialog - Dialog for creating or editing an order
 *
 * Features:
 * - Customer information (name, phone, address)
 * - Product selection with quantities
 * - Payment method selection
 * - Order notes
 * - Automatic total calculation
 */

import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation } from '@apollo/client/react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  Box,
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
} from '@mui/material';
import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import { CREATE_ORDER, UPDATE_ORDER } from '../lib/graphql';
import { ensureProfileId, ensureCampaignId } from '../lib/ids';

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
  orderDate: string;
  paymentMethod: string;
  lineItems: LineItem[];
  totalAmount: number;
  notes?: string;
}

interface Product {
  productId: string;
  productName: string;
  price: number;
}

interface OrderEditorDialogProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  order: Order | null;
  campaignId: string;
  products: Product[];
}

interface LineItemInput {
  productId: string;
  quantity: number;
}

// Format phone number as user types: (123) 456-7890
const formatPhoneNumber = (value: string) => {
  const digits = value.replace(/\D/g, '');
  const limited = digits.slice(0, 10);

  if (limited.length <= 3) return limited;
  if (limited.length <= 6) return `(${limited.slice(0, 3)}) ${limited.slice(3)}`;
  return `(${limited.slice(0, 3)}) ${limited.slice(3, 6)}-${limited.slice(6)}`;
};

// Extract phone digits for E.164 format
const extractPhoneDigits = (phone: string): string => {
  const digits = phone.replace(/\D/g, '');
  return digits.startsWith('1') && digits.length === 11 ? digits.slice(1) : digits;
};

// Convert E.164 to display format
const e164ToDisplay = (phone: string): string => {
  const digits = extractPhoneDigits(phone);
  return formatPhoneNumber(digits);
};

// Parse optional address fields
interface ParsedAddress {
  street: string;
  city: string;
  state: string;
  zipCode: string;
}

const emptyAddress: ParsedAddress = {
  street: '',
  city: '',
  state: '',
  zipCode: '',
};

const parseAddressField = (value: string | undefined): string => value ?? '';

const parseOrderAddress = (addr?: {
  street?: string;
  city?: string;
  state?: string;
  zipCode?: string;
}): ParsedAddress => {
  if (!addr) return emptyAddress;
  return {
    street: parseAddressField(addr.street),
    city: parseAddressField(addr.city),
    state: parseAddressField(addr.state),
    zipCode: parseAddressField(addr.zipCode),
  };
};

// Build customer address input
const buildAddressInput = (street: string, city: string, state: string, zipCode: string) => ({
  street: street.trim() || undefined,
  city: city.trim() || undefined,
  state: state.trim() || undefined,
  zipCode: zipCode.trim() || undefined,
});

// Validate phone number length
const validatePhone = (phone: string): string | null => {
  const digits = phone.replace(/\D/g, '');
  const number = digits.startsWith('1') && digits.length === 11 ? digits.slice(1) : digits;
  return number.length !== 10 ? `Phone must be 10 digits. Got: ${number.length} digits` : null;
};

// Build phone in E.164 format
const buildE164Phone = (phone: string): string => {
  const number = extractPhoneDigits(phone);
  return `+1${number}`;
};

interface CustomerFieldsProps {
  customerName: string;
  setCustomerName: (v: string) => void;
  customerPhone: string;
  handlePhoneChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  street: string;
  setStreet: (v: string) => void;
  city: string;
  setCity: (v: string) => void;
  state: string;
  setState: (v: string) => void;
  zipCode: string;
  setZipCode: (v: string) => void;
  loading: boolean;
}

const CustomerFields: React.FC<CustomerFieldsProps> = ({
  customerName,
  setCustomerName,
  customerPhone,
  handlePhoneChange,
  street,
  setStreet,
  city,
  setCity,
  state,
  setState,
  zipCode,
  setZipCode,
  loading,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Customer Information
    </Typography>
    <Stack spacing={2}>
      <TextField
        autoFocus
        fullWidth
        label="Customer Name"
        value={customerName}
        onChange={(e) => setCustomerName(e.target.value)}
        disabled={loading}
        required
      />
      <TextField
        fullWidth
        label="Phone Number"
        value={customerPhone}
        onChange={handlePhoneChange}
        disabled={loading}
        helperText="Either phone or address is required"
        placeholder="(123) 456-7890"
      />
      <TextField
        fullWidth
        label="Street Address"
        value={street}
        onChange={(e) => setStreet(e.target.value)}
        disabled={loading}
      />
      <Stack direction="row" spacing={2}>
        <TextField fullWidth label="City" value={city} onChange={(e) => setCity(e.target.value)} disabled={loading} />
        <TextField
          label="State"
          value={state}
          onChange={(e) => setState(e.target.value)}
          disabled={loading}
          sx={{ width: 100 }}
        />
        <TextField
          label="ZIP Code"
          value={zipCode}
          onChange={(e) => setZipCode(e.target.value)}
          disabled={loading}
          sx={{ width: 150 }}
        />
      </Stack>
    </Stack>
  </Box>
);

interface LineItemRowProps {
  item: LineItemInput;
  index: number;
  products: Product[];
  loading: boolean;
  onProductChange: (index: number, productId: string) => void;
  onQuantityChange: (index: number, quantity: string) => void;
  onRemove: (index: number) => void;
}

const LineItemRow: React.FC<LineItemRowProps> = ({
  item,
  index,
  products,
  loading,
  onProductChange,
  onQuantityChange,
  onRemove,
}) => {
  const product = products.find((p) => p.productId === item.productId);
  const subtotal = product ? product.price * item.quantity : 0;

  return (
    <TableRow>
      <TableCell>
        <Select
          fullWidth
          value={item.productId}
          onChange={(e) => onProductChange(index, e.target.value)}
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
          onChange={(e) => onQuantityChange(index, e.target.value)}
          disabled={loading}
          size="small"
          sx={{ width: 80 }}
          inputProps={{ min: 1, max: 99999, step: 1 }}
        />
      </TableCell>
      <TableCell align="right">${product?.price.toFixed(2)}</TableCell>
      <TableCell align="right">
        <strong>${subtotal.toFixed(2)}</strong>
      </TableCell>
      <TableCell align="right">
        <IconButton size="small" onClick={() => onRemove(index)} disabled={loading}>
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
  onAdd: () => void;
  onProductChange: (index: number, productId: string) => void;
  onQuantityChange: (index: number, quantity: string) => void;
  onRemove: (index: number) => void;
  total: number;
}

const LineItemsTable: React.FC<LineItemsTableProps> = ({
  lineItems,
  products,
  loading,
  onAdd,
  onProductChange,
  onQuantityChange,
  onRemove,
  total,
}) => (
  <Box>
    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
      <Typography variant="subtitle1">Products</Typography>
      <Button size="small" startIcon={<AddIcon />} onClick={onAdd} disabled={loading || products.length === 0}>
        Add Product
      </Button>
    </Stack>

    {lineItems.length > 0 ? (
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell align="right">Quantity</TableCell>
            <TableCell align="right">Price</TableCell>
            <TableCell align="right">Subtotal</TableCell>
            <TableCell align="right"></TableCell>
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
              onProductChange={onProductChange}
              onQuantityChange={onQuantityChange}
              onRemove={onRemove}
            />
          ))}
          <TableRow>
            <TableCell colSpan={3} align="right">
              <strong>Total:</strong>
            </TableCell>
            <TableCell align="right">
              <Typography variant="h6" color="primary">
                ${total.toFixed(2)}
              </Typography>
            </TableCell>
            <TableCell></TableCell>
          </TableRow>
        </TableBody>
      </Table>
    ) : (
      <Alert severity="info">No products added yet. Click "Add Product" to start.</Alert>
    )}
  </Box>
);

const useCustomerFormState = () => {
  const [customerName, setCustomerName] = useState('');
  const [customerPhone, setCustomerPhone] = useState('');
  const [street, setStreet] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [zipCode, setZipCode] = useState('');

  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCustomerPhone(formatPhoneNumber(e.target.value));
  };

  const reset = () => {
    setCustomerName('');
    setCustomerPhone('');
    setStreet('');
    setCity('');
    setState('');
    setZipCode('');
  };

  const setAddressFields = (street: string, city: string, addrState: string, zipCode: string) => {
    setStreet(street);
    setCity(city);
    setState(addrState);
    setZipCode(zipCode);
  };

  const setAddressFromOrder = (addr: Order['customerAddress']) => {
    const a = parseOrderAddress(addr);
    setAddressFields(a.street, a.city, a.state, a.zipCode);
  };

  const setFromOrder = (o: Order) => {
    setCustomerName(o.customerName);
    setCustomerPhone(o.customerPhone ? e164ToDisplay(o.customerPhone) : '');
    setAddressFromOrder(o.customerAddress);
  };

  return {
    customerName,
    setCustomerName,
    customerPhone,
    handlePhoneChange,
    street,
    setStreet,
    city,
    setCity,
    state,
    setState,
    zipCode,
    setZipCode,
    hasAddress: street || city || state || zipCode,
    reset,
    setFromOrder,
  };
};

const useLineItemsState = (defaultProductId: string | undefined) => {
  const [lineItems, setLineItems] = useState<LineItemInput[]>([]);

  const handleAdd = () => {
    if (defaultProductId) {
      setLineItems([...lineItems, { productId: defaultProductId, quantity: 1 }]);
    }
  };

  const handleRemove = (index: number) => {
    setLineItems(lineItems.filter((_, i) => i !== index));
  };

  const handleProductChange = (index: number, productId: string) => {
    const newLineItems = [...lineItems];
    newLineItems[index].productId = productId;
    setLineItems(newLineItems);
  };

  const handleQuantityChange = (index: number, value: string) => {
    const newLineItems = [...lineItems];
    const parsed = parseInt(value, 10) || 1;
    newLineItems[index].quantity = Math.min(Math.max(1, parsed), 99999);
    setLineItems(newLineItems);
  };

  return {
    lineItems,
    setLineItems,
    handleAdd,
    handleRemove,
    handleProductChange,
    handleQuantityChange,
  };
};

const useOrderDetailsState = () => {
  const [paymentMethod, setPaymentMethod] = useState<string>('CASH');
  const [notes, setNotes] = useState('');
  const [orderDate, setOrderDate] = useState('');

  const reset = () => {
    setPaymentMethod('CASH');
    setNotes('');
    setOrderDate(new Date().toISOString().split('T')[0]);
  };

  const setFromOrder = (o: Order) => {
    setPaymentMethod(o.paymentMethod);
    setNotes(o.notes || '');
    setOrderDate(o.orderDate.split('T')[0]);
  };

  return {
    paymentMethod,
    setPaymentMethod,
    notes,
    setNotes,
    orderDate,
    setOrderDate,
    reset,
    setFromOrder,
  };
};

const calculateTotal = (lineItems: LineItemInput[], products: Product[]) =>
  lineItems.reduce((total, item) => {
    const product = products.find((p) => p.productId === item.productId);
    return total + (product ? product.price * item.quantity : 0);
  }, 0);

interface OrderDetailsFieldsProps {
  orderDate: string;
  setOrderDate: (v: string) => void;
  paymentMethod: string;
  setPaymentMethod: (v: string) => void;
  notes: string;
  setNotes: (v: string) => void;
  loading: boolean;
  lineItemsProps: LineItemsTableProps;
}

const OrderDetailsFields: React.FC<OrderDetailsFieldsProps> = ({
  orderDate,
  setOrderDate,
  paymentMethod,
  setPaymentMethod,
  notes,
  setNotes,
  loading,
  lineItemsProps,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Order Details
    </Typography>
    <Stack spacing={2}>
      <Stack direction="row" spacing={2}>
        <TextField
          label="Order Date"
          type="date"
          value={orderDate}
          onChange={(e) => setOrderDate(e.target.value)}
          disabled={loading}
          InputLabelProps={{ shrink: true }}
          required
          sx={{ flexGrow: 1 }}
        />
        <FormControl sx={{ flexGrow: 1 }}>
          <InputLabel>Payment Method</InputLabel>
          <Select
            value={paymentMethod}
            label="Payment Method"
            onChange={(e) => setPaymentMethod(e.target.value)}
            disabled={loading}
          >
            <MenuItem value="CASH">Cash</MenuItem>
            <MenuItem value="CHECK">Check</MenuItem>
            <MenuItem value="CREDIT_CARD">Credit Card</MenuItem>
            <MenuItem value="OTHER">Other</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      <LineItemsTable {...lineItemsProps} />

      <TextField
        fullWidth
        label="Notes (Optional)"
        multiline
        rows={2}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        disabled={loading}
        placeholder="Delivery instructions, special requests, etc."
      />
    </Stack>
  </Box>
);

const addOptionalInputFields = (
  input: Record<string, unknown>,
  customer: ReturnType<typeof useCustomerFormState>,
  notes: string,
): string | null => {
  if (customer.customerPhone.trim()) {
    const phoneError = validatePhone(customer.customerPhone);
    if (phoneError) return phoneError;
    input.customerPhone = buildE164Phone(customer.customerPhone);
  }

  if (customer.hasAddress) {
    input.customerAddress = buildAddressInput(customer.street, customer.city, customer.state, customer.zipCode);
  }

  if (notes.trim()) {
    input.notes = notes.trim();
  }

  return null;
};

// Form validation helper
const isFormComplete = (
  customer: ReturnType<typeof useCustomerFormState>,
  lineItems: LineItemInput[],
  orderDate: string,
): boolean => {
  const hasName = customer.customerName.trim().length > 0;
  const hasContact = Boolean(customer.customerPhone.trim().length > 0 || customer.hasAddress);
  const hasItems = lineItems.length > 0;
  const hasDate = orderDate.length > 0;
  return hasName && hasContact && hasItems && hasDate;
};

// Form initialization helpers
const initializeFromOrder = (
  order: NonNullable<OrderEditorDialogProps['order']>,
  customer: ReturnType<typeof useCustomerFormState>,
  lineItemsState: ReturnType<typeof useLineItemsState>,
  orderDetails: ReturnType<typeof useOrderDetailsState>,
) => {
  customer.setFromOrder(order);
  lineItemsState.setLineItems(
    order.lineItems.map((item) => ({
      productId: item.productId,
      quantity: item.quantity,
    })),
  );
  orderDetails.setFromOrder(order);
};

const resetAllForms = (
  customer: ReturnType<typeof useCustomerFormState>,
  lineItemsState: ReturnType<typeof useLineItemsState>,
  orderDetails: ReturnType<typeof useOrderDetailsState>,
) => {
  customer.reset();
  lineItemsState.setLineItems([]);
  orderDetails.reset();
};

// Line items props builder
const buildLineItemsProps = (
  lineItemsState: ReturnType<typeof useLineItemsState>,
  products: Product[],
  loading: boolean,
): LineItemsTableProps => ({
  lineItems: lineItemsState.lineItems,
  products,
  loading,
  onAdd: lineItemsState.handleAdd,
  onProductChange: lineItemsState.handleProductChange,
  onQuantityChange: lineItemsState.handleQuantityChange,
  onRemove: lineItemsState.handleRemove,
  total: calculateTotal(lineItemsState.lineItems, products),
});

// Submit execution helper
const executeOrderMutation = async (
  isUpdate: boolean,
  input: Record<string, unknown>,
  orderId: string | undefined,
  profileId: string,
  campaignId: string,
  createOrder: ReturnType<typeof useMutation>[0],
  updateOrder: ReturnType<typeof useMutation>[0],
) => {
  if (isUpdate && orderId) {
    await updateOrder({ variables: { input: { ...input, orderId } } });
  } else {
    await createOrder({
      variables: { input: { ...input, profileId, campaignId } },
    });
  }
};

// Get default product ID safely
const getDefaultProductId = (products: Product[]): string | undefined => {
  return products.length > 0 ? products[0].productId : undefined;
};

// Form initialization effect handler
const useFormInitEffect = (
  open: boolean,
  order: OrderEditorDialogProps['order'],
  customer: ReturnType<typeof useCustomerFormState>,
  lineItemsState: ReturnType<typeof useLineItemsState>,
  orderDetails: ReturnType<typeof useOrderDetailsState>,
) => {
  useEffect(() => {
    if (!open) return;
    if (order) {
      initializeFromOrder(order, customer, lineItemsState, orderDetails);
    } else {
      resetAllForms(customer, lineItemsState, orderDetails);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, order]);
};

// Submit button text helper
const getSubmitButtonText = (loading: boolean, isUpdate: boolean): string => {
  if (loading) return 'Saving...';
  return isUpdate ? 'Save Changes' : 'Create Order';
};

// Dialog title helper
const getDialogTitle = (isUpdate: boolean): string => {
  return isUpdate ? 'Edit Order' : 'New Order';
};

// Combine loading states
const combineLoading = (creating: boolean, updating: boolean): boolean => {
  return creating || updating;
};

// Combine error states
const combineErrors = (
  createError: ReturnType<typeof useMutation>[1]['error'],
  updateError: ReturnType<typeof useMutation>[1]['error'],
): ReturnType<typeof useMutation>[1]['error'] => {
  return createError ?? updateError;
};

// Error message formatter
const formatSubmitError = (err: unknown): string => {
  if (err instanceof Error) return err.message;
  return 'Unknown error';
};

// Submit handler helper
const prepareAndSubmit = async (
  input: Record<string, unknown>,
  customer: ReturnType<typeof useCustomerFormState>,
  notes: string,
  isUpdate: boolean,
  orderId: string | undefined,
  profileId: string,
  campaignId: string,
  createOrder: ReturnType<typeof useMutation>[0],
  updateOrder: ReturnType<typeof useMutation>[0],
): Promise<void> => {
  const validationError = addOptionalInputFields(input, customer, notes);
  if (validationError) {
    alert(validationError);
    return;
  }

  await executeOrderMutation(isUpdate, input, orderId, profileId, campaignId, createOrder, updateOrder);
};

export const OrderEditorDialog: React.FC<OrderEditorDialogProps> = ({
  open,
  onClose,
  onComplete,
  order,
  campaignId,
  products,
}) => {
  const { profileId } = useParams<{ profileId: string }>();
  const dbProfileId = ensureProfileId(profileId);
  const dbCampaignId = ensureCampaignId(campaignId);

  const customer = useCustomerFormState();
  const lineItemsState = useLineItemsState(getDefaultProductId(products));
  const orderDetails = useOrderDetailsState();
  const isUpdate = order !== null;

  useFormInitEffect(open, order, customer, lineItemsState, orderDetails);

  const [createOrder, { loading: creating, error: createError }] = useMutation(CREATE_ORDER, {
    onCompleted: onComplete,
  });
  const [updateOrder, { loading: updating, error: updateError }] = useMutation(UPDATE_ORDER, {
    onCompleted: onComplete,
  });

  const loading = combineLoading(creating, updating);
  const error = combineErrors(createError, updateError);
  const isFormValid = isFormComplete(customer, lineItemsState.lineItems, orderDetails.orderDate);

  const buildBaseInput = () => ({
    customerName: customer.customerName.trim(),
    orderDate: new Date(orderDetails.orderDate + 'T00:00:00.000Z').toISOString(),
    paymentMethod: orderDetails.paymentMethod,
    lineItems: lineItemsState.lineItems.map((item) => ({
      productId: item.productId,
      quantity: item.quantity,
    })),
  });

  const handleSubmit = async () => {
    if (!isFormValid) return;
    if (!dbProfileId) return;

    try {
      const input: Record<string, unknown> = buildBaseInput();
      await prepareAndSubmit(
        input,
        customer,
        orderDetails.notes,
        isUpdate,
        order?.orderId,
        dbProfileId,
        dbCampaignId!,
        createOrder,
        updateOrder,
      );
    } catch (err: unknown) {
      console.error('Failed to save order:', err);
      alert(`Error: ${formatSubmitError(err)}`);
    }
  };

  const handleClose = () => {
    if (!loading) onClose();
  };

  const lineItemsProps = buildLineItemsProps(lineItemsState, products, loading);
  const submitButtonText = getSubmitButtonText(loading, isUpdate);
  const dialogTitle = getDialogTitle(isUpdate);

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>{dialogTitle}</DialogTitle>
      <DialogContent>
        <Stack spacing={3} pt={1}>
          <CustomerFields
            customerName={customer.customerName}
            setCustomerName={customer.setCustomerName}
            customerPhone={customer.customerPhone}
            handlePhoneChange={customer.handlePhoneChange}
            street={customer.street}
            setStreet={customer.setStreet}
            city={customer.city}
            setCity={customer.setCity}
            state={customer.state}
            setState={customer.setState}
            zipCode={customer.zipCode}
            setZipCode={customer.setZipCode}
            loading={loading}
          />

          <Divider />

          <OrderDetailsFields
            orderDate={orderDetails.orderDate}
            setOrderDate={orderDetails.setOrderDate}
            paymentMethod={orderDetails.paymentMethod}
            setPaymentMethod={orderDetails.setPaymentMethod}
            notes={orderDetails.notes}
            setNotes={orderDetails.setNotes}
            loading={loading}
            lineItemsProps={lineItemsProps}
          />

          {error && <Alert severity="error">Failed to save order: {error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} variant="contained" disabled={!isFormValid || loading}>
          {submitButtonText}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
