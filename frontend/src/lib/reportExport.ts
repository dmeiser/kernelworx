/**
 * Report export utilities for generating CSV/XLSX files from order data
 */

import * as XLSX from 'xlsx';

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
  if (!phone) return '';
  // Remove all non-digit characters
  const digits = phone.replace(/\D/g, '');
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
  if (!address) return '';
  const cityStateZip = [address.city, address.state, address.zipCode].filter(Boolean).join(' ');
  return [address.street, cityStateZip].filter(Boolean).join(', ');
}

function getUniqueProducts(orders: Order[]): string[] {
  return Array.from(new Set(orders.flatMap((order) => order.lineItems.map((item) => item.productName)))).sort();
}

// Characters that spreadsheet applications interpret as formula triggers.
const FORMULA_TRIGGER_RE = /^[=+\-@\t\r]/;

function sanitizeReportValue(value: string | number): string | number {
  // Force text treatment for cells that would otherwise be interpreted as formulas.
  if (typeof value === 'string' && FORMULA_TRIGGER_RE.test(value)) {
    return `'${value}`;
  }
  return value;
}

function prepareReportData(orders: Order[]) {
  const allProducts = getUniqueProducts(orders);
  const headers: (string | number)[] = ['Name', 'Phone', 'Address', ...allProducts, 'Total'].map(
    sanitizeReportValue,
  );

  const rows = [
    headers,
    ...orders.map((order) => {
      const quantities = order.lineItems.reduce<Record<string, number>>(
        (acc, item) => ({
          ...acc,
          [item.productName]: (acc[item.productName] || 0) + item.quantity,
        }),
        {},
      );

      const productCounts = allProducts.map((product) => quantities[product] || '');

      return [
        sanitizeReportValue(order.customerName),
        sanitizeReportValue(formatPhone(order.customerPhone)),
        sanitizeReportValue(formatAddress(order.customerAddress)),
        ...productCounts.map(sanitizeReportValue),
        order.totalAmount,
      ];
    }),
  ];

  return { headers, rows, allProducts };
}

function escapeCsvCell(value: string | number): string {
  const str = String(value);
  // Escape embedded double-quotes by doubling them, then wrap the whole cell in quotes.
  return `"${str.replace(/"/g, '""')}"`;
}

export function downloadAsCSV(orders: Order[], campaignId: string): void {
  const { rows } = prepareReportData(orders);

  // Convert to CSV
  const csv = rows.map((row) => row.map(escapeCsvCell).join(',')).join('\n');

  // Create blob and download
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);

  link.setAttribute('href', url);
  link.setAttribute('download', `campaign-${campaignId}.csv`);
  link.style.visibility = 'hidden';

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function downloadAsXLSX(orders: Order[], campaignId: string): void {
  const { rows } = prepareReportData(orders);

  // Create workbook
  const ws = XLSX.utils.aoa_to_sheet(rows);

  // Note: the community build of xlsx does not persist cell styles, so header styling is omitted.

  // Auto-size columns
  const colWidths = rows[0].map((_value: string | number, idx: number) => {
    let maxLength = String(rows[0][idx] || '').length;
    for (let i = 1; i < rows.length; i++) {
      const cellValue = String(rows[i][idx] || '');
      maxLength = Math.max(maxLength, cellValue.length);
    }
    return { wch: Math.min(maxLength + 2, 50) };
  });
  ws['!cols'] = colWidths;

  // Create workbook and add sheet
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Orders');

  // Download
  XLSX.writeFile(wb, `campaign-${campaignId}.xlsx`);
}
