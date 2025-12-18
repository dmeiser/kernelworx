/**
 * Report export utilities for generating CSV/XLSX files from order data
 */

import * as XLSX from "xlsx";

interface LineItem {
  productId: string;
  productName: string;
  quantity: number;
  pricePerUnit: number;
  subtotal: number;
}

interface Address {
  street?: string;
  city?: string;
  state?: string;
  zipCode?: string;
}

interface Order {
  orderId: string;
  customerName: string;
  customerPhone?: string;
  customerAddress?: Address;
  paymentMethod: string;
  lineItems: LineItem[];
  totalAmount: number;
}

function formatPhone(phone?: string): string {
  if (!phone) return "";
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
}

function formatAddress(address?: Address): string {
  if (!address) return "";
  const parts = [];
  if (address.street) parts.push(address.street);
  if (address.city || address.state || address.zipCode) {
    const cityStateZip = [address.city, address.state, address.zipCode]
      .filter(Boolean)
      .join(" ");
    if (cityStateZip) parts.push(cityStateZip);
  }
  return parts.join(", ");
}

function getUniqueProducts(orders: Order[]): string[] {
  return Array.from(
    new Set(
      orders.flatMap((order) =>
        order.lineItems.map((item) => item.productName),
      ),
    ),
  ).sort();
}

function prepareReportData(orders: Order[]) {
  const allProducts = getUniqueProducts(orders);

  // Build rows for export
  const rows: (string | number)[][] = [];

  // Header row
  const headers: (string | number)[] = [
    "Name",
    "Phone",
    "Address",
    ...allProducts,
    "Total",
  ];
  rows.push(headers);

  // Data rows
  for (const order of orders) {
    const row: (string | number)[] = [
      order.customerName,
      formatPhone(order.customerPhone),
      formatAddress(order.customerAddress),
    ];

    // Product quantities (sum duplicates)
    const lineItemsByProduct: Record<string, number> = {};
    for (const item of order.lineItems) {
      lineItemsByProduct[item.productName] = 
        (lineItemsByProduct[item.productName] || 0) + item.quantity;
    }

    for (const product of allProducts) {
      row.push(lineItemsByProduct[product] || "");
    }

    // Total
    row.push(order.totalAmount);
    rows.push(row);
  }

  return { headers, rows, allProducts };
}

export function downloadAsCSV(orders: Order[], seasonId: string): void {
  const { rows } = prepareReportData(orders);

  // Convert to CSV
  const csv = rows
    .map((row) => row.map((cell) => `"${cell}"`).join(","))
    .join("\n");

  // Create blob and download
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);

  link.setAttribute("href", url);
  link.setAttribute("download", `season-${seasonId}.csv`);
  link.style.visibility = "hidden";

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export function downloadAsXLSX(orders: Order[], seasonId: string): void {
  const { rows } = prepareReportData(orders);

  // Create workbook
  const ws = XLSX.utils.aoa_to_sheet(rows);

  // Style header row
  const headerStyle = {
    fill: { fgColor: { rgb: "4472C4" } },
    font: { bold: true, color: { rgb: "FFFFFF" } },
    alignment: { horizontal: "center", vertical: "center" },
  };

  for (let i = 0; i < rows[0].length; i++) {
    const cellAddress = XLSX.utils.encode_cell({ r: 0, c: i });
    if (ws[cellAddress]) {
      ws[cellAddress].s = headerStyle;
    }
  }

  // Auto-size columns
  const colWidths = rows[0].map((_value: string | number, idx: number) => {
    let maxLength = String(rows[0][idx] || "").length;
    for (let i = 1; i < rows.length; i++) {
      const cellValue = String(rows[i][idx] || "");
      maxLength = Math.max(maxLength, cellValue.length);
    }
    return { wch: Math.min(maxLength + 2, 50) };
  });
  ws["!cols"] = colWidths;

  // Create workbook and add sheet
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Orders");

  // Download
  XLSX.writeFile(wb, `season-${seasonId}.xlsx`);
}
