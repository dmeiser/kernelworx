/**
 * Report export tests
 */

import { describe, it, expect, vi } from 'vitest';
import { downloadAsCSV, downloadAsXLSX } from './reportExport';

const mockAoaToSheet = vi.fn();
const mockBookNew = vi.fn();
const mockBookAppendSheet = vi.fn();
const mockWriteFile = vi.fn();

vi.mock('xlsx', async () => {
  return {
    default: {
      utils: {
        aoa_to_sheet: mockAoaToSheet,
        book_new: mockBookNew,
        book_append_sheet: mockBookAppendSheet,
      },
      writeFile: mockWriteFile,
    },
    utils: {
      aoa_to_sheet: mockAoaToSheet,
      book_new: mockBookNew,
      book_append_sheet: mockBookAppendSheet,
    },
    writeFile: mockWriteFile,
  };
});

describe('downloadAsCSV', () => {
  it('downloads a CSV file without importing xlsx', () => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:mock-url'),
      revokeObjectURL: vi.fn(),
    });

    const orders = [
      {
        orderId: 'order-1',
        customerName: 'Alice',
        customerPhone: '5551234567',
        paymentMethod: 'cash',
        lineItems: [{ productId: 'p1', productName: 'Cookies', quantity: 2, pricePerUnit: 5, subtotal: 10 }],
        totalAmount: 10,
      },
    ];

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadAsCSV(orders, 'campaign-1');

    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');

    vi.unstubAllGlobals();
    clickSpy.mockRestore();
  });
});

describe('downloadAsXLSX', () => {
  beforeEach(() => {
    mockAoaToSheet.mockReturnValue({});
    mockBookNew.mockReturnValue({});
    vi.clearAllMocks();
  });

  it('dynamically imports xlsx and writes an Excel file', async () => {
    const orders = [
      {
        orderId: 'order-1',
        customerName: 'Alice',
        customerPhone: '5551234567',
        paymentMethod: 'cash',
        lineItems: [{ productId: 'p1', productName: 'Cookies', quantity: 2, pricePerUnit: 5, subtotal: 10 }],
        totalAmount: 10,
      },
    ];

    await downloadAsXLSX(orders, 'campaign-1');

    expect(mockAoaToSheet).toHaveBeenCalled();
    expect(mockBookNew).toHaveBeenCalled();
    expect(mockBookAppendSheet).toHaveBeenCalled();
    expect(mockWriteFile).toHaveBeenCalledWith(expect.anything(), 'campaign-campaign-1.xlsx');
  });
});
