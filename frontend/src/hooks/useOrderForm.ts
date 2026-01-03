/**
 * Custom hook for managing order form state
 */

import { useState, useCallback } from "react";

export interface LineItemInput {
  productId: string;
  quantity: number;
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

// ============================================================================
// Helper Functions
// ============================================================================

function updateLineItemInArray(
  items: LineItemInput[],
  index: number,
  field: "productId" | "quantity",
  value: string,
): LineItemInput[] {
  const newItems = [...items];
  if (field === "quantity") {
    const parsed = parseInt(value) || 1;
    newItems[index][field] = Math.min(Math.max(1, parsed), 99999);
  } else {
    newItems[index][field] = value;
  }
  return newItems;
}

function loadCustomerInfo(
  order: OrderData,
  setCustomerName: (v: string) => void,
  setCustomerPhone: (v: string) => void,
): void {
  setCustomerName(order.customerName ?? "");
  setCustomerPhone(order.customerPhone ?? "");
}

function getOrDefault(value: string | undefined): string {
  return value ?? "";
}

function loadAddressInfo(
  address: OrderAddress | undefined,
  setStreet: (v: string) => void,
  setCity: (v: string) => void,
  setState: (v: string) => void,
  setZipCode: (v: string) => void,
): void {
  const safeAddress = address ?? {};
  setStreet(getOrDefault(safeAddress.street));
  setCity(getOrDefault(safeAddress.city));
  setState(getOrDefault(safeAddress.state));
  setZipCode(getOrDefault(safeAddress.zipCode));
}

function mapLineItems(items: OrderLineItem[]): LineItemInput[] {
  return items.map((item) => ({
    productId: item.productId,
    quantity: item.quantity,
  }));
}

// ============================================================================
// OrderFormState Interface
// ============================================================================

export interface OrderFormState {
  // Customer info
  customerName: string;
  setCustomerName: (value: string) => void;
  customerPhone: string;
  setCustomerPhone: (value: string) => void;

  // Address
  street: string;
  setStreet: (value: string) => void;
  city: string;
  setCity: (value: string) => void;
  state: string;
  setState: (value: string) => void;
  zipCode: string;
  setZipCode: (value: string) => void;

  // Payment
  paymentMethod: string;
  setPaymentMethod: (value: string) => void;
  notes: string;
  setNotes: (value: string) => void;

  // Line items
  lineItems: LineItemInput[];
  addLineItem: () => void;
  removeLineItem: (index: number) => void;
  updateLineItem: (
    index: number,
    field: "productId" | "quantity",
    value: string,
  ) => void;

  // Status
  loading: boolean;
  setLoading: (value: boolean) => void;
  error: string | null;
  setError: (value: string | null) => void;

  // Actions
  loadFromOrder: (order: OrderData) => void;
}

export function useOrderForm(): OrderFormState {
  // Customer info
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");

  // Address
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [zipCode, setZipCode] = useState("");

  // Payment
  const [paymentMethod, setPaymentMethod] = useState("CASH");
  const [notes, setNotes] = useState("");

  // Line items
  const [lineItems, setLineItems] = useState<LineItemInput[]>([
    { productId: "", quantity: 1 },
  ]);

  // Status
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addLineItem = useCallback(() => {
    setLineItems((prev) => [...prev, { productId: "", quantity: 1 }]);
  }, []);

  const removeLineItem = useCallback((index: number) => {
    setLineItems((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateLineItem = useCallback(
    (index: number, field: "productId" | "quantity", value: string) => {
      setLineItems((prev) => updateLineItemInArray(prev, index, field, value));
    },
    [],
  );

  const loadFromOrder = useCallback((order: OrderData) => {
    loadCustomerInfo(order, setCustomerName, setCustomerPhone);
    loadAddressInfo(
      order.customerAddress,
      setStreet,
      setCity,
      setState,
      setZipCode,
    );
    setPaymentMethod(order.paymentMethod || "CASH");
    setNotes(order.notes || "");
    setLineItems(mapLineItems(order.lineItems));
  }, []);

  return {
    customerName,
    setCustomerName,
    customerPhone,
    setCustomerPhone,
    street,
    setStreet,
    city,
    setCity,
    state,
    setState,
    zipCode,
    setZipCode,
    paymentMethod,
    setPaymentMethod,
    notes,
    setNotes,
    lineItems,
    addLineItem,
    removeLineItem,
    updateLineItem,
    loading,
    setLoading,
    error,
    setError,
    loadFromOrder,
  };
}
