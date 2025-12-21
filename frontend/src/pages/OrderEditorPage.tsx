/**
 * OrderEditorPage - Page for creating or editing an order
 */

import React, { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@apollo/client/react";
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
} from "@mui/material";
import {
  Add as AddIcon,
  Delete as DeleteIcon,
  ArrowBack as ArrowBackIcon,
} from "@mui/icons-material";
import {
  CREATE_ORDER,
  UPDATE_ORDER,
  GET_ORDER,
  GET_SEASON,
  GET_PROFILE,
} from "../lib/graphql";

interface LineItemInput {
  productId: string;
  quantity: number;
}

interface Product {
  productId: string;
  productName: string;
  price: number;
}

interface Catalog {
  products: Product[];
}

interface SeasonData {
  seasonId: string;
  catalog?: Catalog;
}

interface ProfileData {
  profileId: string;
  isOwner: boolean;
  permissions?: string[];
}

interface OrderAddress {
  street?: string;
  city?: string;
  state?: string;
  zipCode?: string;
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

export const OrderEditorPage: React.FC = () => {
  const {
    profileId: encodedProfileId,
    seasonId: encodedSeasonId,
    orderId: encodedOrderId,
  } = useParams<{ profileId: string; seasonId: string; orderId?: string }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const seasonId = encodedSeasonId ? decodeURIComponent(encodedSeasonId) : "";
  const orderId = encodedOrderId ? decodeURIComponent(encodedOrderId) : null;
  const navigate = useNavigate();
  const isEditing = !!orderId;

  // Form state
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [zipCode, setZipCode] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("CASH");
  const [notes, setNotes] = useState("");
  const [lineItems, setLineItems] = useState<LineItemInput[]>([
    { productId: "", quantity: 1 },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch season data for products
  const { data: seasonData } = useQuery<{ getSeason: SeasonData }>(GET_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  // Fetch profile for permissions
  const { data: profileData } = useQuery<{ getProfile: ProfileData }>(
    GET_PROFILE,
    {
      variables: { profileId },
      skip: !profileId,
    },
  );

  // Fetch existing order if editing
  const { data: orderData, loading: orderLoading } = useQuery<{
    getOrder: OrderData;
  }>(GET_ORDER, {
    variables: { orderId },
    skip: !orderId,
  });

  const products: Product[] = seasonData?.getSeason?.catalog?.products || [];
  const profile = profileData?.getProfile;
  const hasWritePermission =
    profile?.isOwner || profile?.permissions?.includes("WRITE");

  // Load existing order data
  useEffect(() => {
    if (orderData?.getOrder) {
      const order = orderData.getOrder;
      setCustomerName(order.customerName || "");
      setCustomerPhone(order.customerPhone || "");
      setStreet(order.customerAddress?.street || "");
      setCity(order.customerAddress?.city || "");
      setState(order.customerAddress?.state || "");
      setZipCode(order.customerAddress?.zipCode || "");
      setPaymentMethod(order.paymentMethod || "CASH");
      setNotes(order.notes || "");
      setLineItems(
        order.lineItems.map((item: OrderLineItem) => ({
          productId: item.productId,
          quantity: item.quantity,
        })),
      );
    }
  }, [orderData]);

  // Mutations
  const [createOrder] = useMutation(CREATE_ORDER);
  const [updateOrder] = useMutation(UPDATE_ORDER);

  const handleAddLineItem = () => {
    setLineItems([...lineItems, { productId: "", quantity: 1 }]);
  };

  const handleRemoveLineItem = (index: number) => {
    setLineItems(lineItems.filter((_, i) => i !== index));
  };

  const handleLineItemChange = (
    index: number,
    field: "productId" | "quantity",
    value: string,
  ) => {
    const newItems = [...lineItems];
    if (field === "quantity") {
      const parsed = parseInt(value) || 1;
      // Limit to reasonable max (GraphQL Int max is 2,147,483,647)
      newItems[index][field] = Math.min(Math.max(1, parsed), 99999);
    } else {
      newItems[index][field] = value;
    }
    setLineItems(newItems);
  };

  const calculateTotal = () => {
    return lineItems.reduce((sum, item) => {
      const product = products.find((p) => p.productId === item.productId);
      return sum + (product?.price || 0) * item.quantity;
    }, 0);
  };

  const handleSubmit = async () => {
    setError(null);

    // Validation
    if (!customerName.trim()) {
      setError("Customer name is required");
      return;
    }

    const validLineItems = lineItems.filter(
      (item) => item.productId && item.quantity > 0,
    );
    if (validLineItems.length === 0) {
      setError("At least one product is required");
      return;
    }

    setLoading(true);

    try {
      if (isEditing && orderId) {
        const updateInput = {
          orderId,
          customerName: customerName.trim(),
          customerPhone: customerPhone.trim() || null,
          customerAddress:
            street || city || state || zipCode
              ? {
                  street: street.trim() || null,
                  city: city.trim() || null,
                  state: state.trim() || null,
                  zipCode: zipCode.trim() || null,
                }
              : null,
          paymentMethod,
          lineItems: validLineItems,
          notes: notes.trim() || null,
        };
        await updateOrder({
          variables: { input: updateInput },
        });
      } else {
        const createInput = {
          profileId,
          seasonId,
          customerName: customerName.trim(),
          customerPhone: customerPhone.trim() || null,
          customerAddress:
            street || city || state || zipCode
              ? {
                  street: street.trim() || null,
                  city: city.trim() || null,
                  state: state.trim() || null,
                  zipCode: zipCode.trim() || null,
                }
              : null,
          orderDate: new Date().toISOString(),
          paymentMethod,
          lineItems: validLineItems,
          notes: notes.trim() || null,
        };
        await createOrder({
          variables: { input: createInput },
        });
      }

      // Navigate back to orders page
      navigate(
        `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(seasonId)}/orders`,
      );
    } catch (err: unknown) {
      const error = err as { message?: string };
      setError(error.message || "Failed to save order");
      setLoading(false);
    }
  };

  const handleCancel = () => {
    navigate(
      `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(seasonId)}/orders`,
    );
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(amount);
  };

  const formatPhoneNumber = (phone: string) => {
    // Format +1XXXXXXXXXX as (XXX) XXX-XXXX
    const digits = phone.replace(/\D/g, "");
    if (digits.length === 11 && digits.startsWith("1")) {
      const areaCode = digits.slice(1, 4);
      const prefix = digits.slice(4, 7);
      const lineNumber = digits.slice(7, 11);
      return `(${areaCode}) ${prefix}-${lineNumber}`;
    }
    if (digits.length === 10) {
      const areaCode = digits.slice(0, 3);
      const prefix = digits.slice(3, 6);
      const lineNumber = digits.slice(6, 10);
      return `(${areaCode}) ${prefix}-${lineNumber}`;
    }
    return phone; // Return as-is if format is unexpected
  };

  if (orderLoading) {
    return (
      <Box display="flex" justifyContent="center" py={4}>
        <CircularProgress />
      </Box>
    );
  }

  if (!hasWritePermission) {
    return (
      <Alert severity="error">You don't have permission to edit orders</Alert>
    );
  }

  return (
    <Box>
      {/* Breadcrumbs */}
      <Breadcrumbs sx={{ mb: 2 }}>
        <Link
          component="button"
          variant="body2"
          onClick={() => navigate("/profiles")}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Profiles
        </Link>
        <Link
          component="button"
          variant="body2"
          onClick={() => navigate(`/profiles/${encodeURIComponent(profileId)}`)}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Seasons
        </Link>
        <Link
          component="button"
          variant="body2"
          onClick={handleCancel}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Orders
        </Link>
        <Typography variant="body2" color="text.primary">
          {isEditing ? "Edit Order" : "New Order"}
        </Typography>
      </Breadcrumbs>

      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} mb={3}>
        <IconButton onClick={handleCancel} edge="start">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">
          {isEditing ? "Edit Order" : "Create Order"}
        </Typography>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Customer Information */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Customer Information
        </Typography>
        <Stack spacing={2}>
          <TextField
            fullWidth
            label="Customer Name"
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            required
            disabled={loading}
          />
          <TextField
            fullWidth
            label="Phone Number"
            value={customerPhone}
            onChange={(e) => setCustomerPhone(e.target.value)}
            onBlur={(e) => {
              const formatted = formatPhoneNumber(e.target.value);
              setCustomerPhone(formatted);
            }}
            placeholder="(555) 123-4567"
            disabled={loading}
          />
          <TextField
            fullWidth
            label="Street Address"
            value={street}
            onChange={(e) => setStreet(e.target.value)}
            disabled={loading}
          />
          <Stack direction="row" spacing={2}>
            <TextField
              fullWidth
              label="City"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              disabled={loading}
            />
            <TextField
              label="State"
              value={state}
              onChange={(e) => setState(e.target.value)}
              sx={{ width: 100 }}
              disabled={loading}
            />
            <TextField
              label="Zip Code"
              value={zipCode}
              onChange={(e) => setZipCode(e.target.value)}
              sx={{ width: 120 }}
              disabled={loading}
            />
          </Stack>
        </Stack>
      </Paper>

      {/* Line Items */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          mb={2}
        >
          <Typography variant="h6">Products</Typography>
          <Button
            startIcon={<AddIcon />}
            onClick={handleAddLineItem}
            disabled={loading}
          >
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
            {lineItems.map((item, index) => {
              const product = products.find(
                (p) => p.productId === item.productId,
              );
              const subtotal = product ? product.price * item.quantity : 0;
              return (
                <TableRow key={index}>
                  <TableCell>
                    <Select
                      fullWidth
                      value={item.productId}
                      onChange={(e) =>
                        handleLineItemChange(index, "productId", e.target.value)
                      }
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
                      onChange={(e) =>
                        handleLineItemChange(index, "quantity", e.target.value)
                      }
                      disabled={loading}
                      size="small"
                      sx={{ width: 80 }}
                      inputProps={{ min: 1, max: 99999, step: 1 }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    {product ? formatCurrency(product.price) : "—"}
                  </TableCell>
                  <TableCell align="right">
                    {formatCurrency(subtotal)}
                  </TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="small"
                      onClick={() => handleRemoveLineItem(index)}
                      disabled={loading || lineItems.length === 1}
                      color="error"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>

        <Divider sx={{ my: 2 }} />

        <Box display="flex" justifyContent="flex-end">
          <Typography variant="h6">
            Total: {formatCurrency(calculateTotal())}
          </Typography>
        </Box>
      </Paper>

      {/* Payment & Notes */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Payment & Notes
        </Typography>
        <Stack spacing={2}>
          <FormControl fullWidth disabled={loading}>
            <InputLabel>Payment Method</InputLabel>
            <Select
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              label="Payment Method"
            >
              <MenuItem value="CASH">Cash</MenuItem>
              <MenuItem value="CHECK">Check</MenuItem>
              <MenuItem value="CREDIT_CARD">Credit Card</MenuItem>
              <MenuItem value="OTHER">Other</MenuItem>
            </Select>
          </FormControl>
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

      {/* Actions */}
      <Stack direction="row" spacing={2} justifyContent="flex-end">
        <Button onClick={handleCancel} disabled={loading}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={loading || !customerName.trim()}
        >
          {loading
            ? isEditing
              ? "Updating..."
              : "Creating..."
            : isEditing
              ? "Update Order"
              : "Create Order"}
        </Button>
      </Stack>
    </Box>
  );
};
