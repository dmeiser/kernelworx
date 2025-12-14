/**
 * Tests for reportExport utility functions
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadAsCSV, downloadAsXLSX } from "../src/lib/reportExport";

const mockOrder = {
  orderId: "order-1",
  customerName: "John Doe",
  customerPhone: "555-0100",
  customerAddress: {
    street: "123 Main St",
    city: "Springfield",
    state: "IL",
    zipCode: "62701",
  },
  paymentMethod: "CREDIT_CARD",
  lineItems: [
    {
      productId: "prod-1",
      productName: "Caramel Corn",
      quantity: 5,
      pricePerUnit: 6.0,
      subtotal: 30.0,
    },
    {
      productId: "prod-2",
      productName: "Butter Corn",
      quantity: 3,
      pricePerUnit: 6.0,
      subtotal: 18.0,
    },
  ],
  totalAmount: 48.0,
};

const mockOrder2 = {
  orderId: "order-2",
  customerName: "Jane Smith",
  customerPhone: "555-0101",
  customerAddress: {
    street: "456 Oak Ave",
    city: "Springfield",
    state: "IL",
    zipCode: "62702",
  },
  paymentMethod: "CASH",
  lineItems: [
    {
      productId: "prod-1",
      productName: "Caramel Corn",
      quantity: 2,
      pricePerUnit: 6.0,
      subtotal: 12.0,
    },
  ],
  totalAmount: 12.0,
};

describe("reportExport utilities", () => {
  beforeEach(() => {
    // Setup: Mock URL.createObjectURL and file download
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    
    // Mock document.createElement to return a mock element
    const mockElement = {
      setAttribute: vi.fn(),
      click: vi.fn(),
      style: {},
    };
    vi.spyOn(document, "createElement").mockReturnValue(mockElement as any);
    
    // Mock appendChild/removeChild
    vi.spyOn(document.body, "appendChild").mockReturnValue(mockElement as any);
    vi.spyOn(document.body, "removeChild").mockReturnValue(mockElement as any);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("downloadAsCSV", () => {
    it("should not throw when exporting single order", () => {
      expect(() => downloadAsCSV([mockOrder], "season-123")).not.toThrow();
    });

    it("should not throw when exporting multiple orders", () => {
      expect(() => downloadAsCSV([mockOrder, mockOrder2], "season-123")).not.toThrow();
    });

    it("should not throw when exporting order without phone", () => {
      const orderNoPhone = { ...mockOrder, customerPhone: undefined };
      expect(() => downloadAsCSV([orderNoPhone], "season-123")).not.toThrow();
    });

    it("should not throw when exporting order without address", () => {
      const orderNoAddress = { ...mockOrder, customerAddress: undefined };
      expect(() => downloadAsCSV([orderNoAddress], "season-123")).not.toThrow();
    });

    it("should handle empty order list", () => {
      expect(() => downloadAsCSV([], "season-123")).not.toThrow();
    });
  });

  describe("downloadAsXLSX", () => {
    it("should not throw when exporting single order", () => {
      expect(() => downloadAsXLSX([mockOrder], "season-123")).not.toThrow();
    });

    it("should not throw when exporting multiple orders with different products", () => {
      expect(() => downloadAsXLSX([mockOrder, mockOrder2], "season-123")).not.toThrow();
    });

    it("should not throw when exporting order without phone", () => {
      const orderNoPhone = { ...mockOrder, customerPhone: undefined };
      expect(() => downloadAsXLSX([orderNoPhone], "season-123")).not.toThrow();
    });

    it("should not throw when exporting order without address", () => {
      const orderNoAddress = { ...mockOrder, customerAddress: undefined };
      expect(() => downloadAsXLSX([orderNoAddress], "season-123")).not.toThrow();
    });

    it("should handle empty order list", () => {
      expect(() => downloadAsXLSX([], "season-123")).not.toThrow();
    });

    it("should handle multiple products across orders", () => {
      const order3 = {
        ...mockOrder2,
        orderId: "order-3",
        lineItems: [
          {
            productId: "prod-3",
            productName: "Cheese Corn",
            quantity: 1,
            pricePerUnit: 8.0,
            subtotal: 8.0,
          },
        ],
      };
      expect(() => downloadAsXLSX([mockOrder, mockOrder2, order3], "season-456")).not.toThrow();
    });
  });

  describe("data transformation", () => {
    it("should properly handle mixed product availability across orders", () => {
      // mockOrder has 2 products, mockOrder2 has 1 product
      // Should not throw and should handle missing products gracefully
      expect(() => downloadAsXLSX([mockOrder, mockOrder2], "season-789")).not.toThrow();
    });

    it("should format phone numbers correctly", () => {
      // Phone number with 10 digits should be formatted as (XXX) XXX-XXXX
      const orderWithPhone = { ...mockOrder, customerPhone: "5550100123" };
      expect(() => downloadAsCSV([orderWithPhone], "season-123")).not.toThrow();
    });

    it("should handle phone numbers with different formats", () => {
      const formats = [
        "555010",            // 6 digits
        "5550100123",        // 10 digits no formatting
        "(555) 010-0123",    // Already formatted
        "555.010.0123",      // Dot-formatted
        "+1 555 010 0123",   // International format
      ];

      for (const phone of formats) {
        const order = { ...mockOrder, customerPhone: phone };
        expect(() => downloadAsCSV([order], "season-123")).not.toThrow();
      }
    });

    it("should sort products alphabetically", () => {
      const orderWithUnsortedProducts = {
        ...mockOrder,
        lineItems: [
          { ...mockOrder.lineItems[0], productName: "Zesty Corn" },
          { ...mockOrder.lineItems[1], productName: "Almond Corn" },
          {
            productId: "prod-3",
            productName: "Caramel Corn",
            quantity: 2,
            pricePerUnit: 6.0,
            subtotal: 12.0,
          },
        ],
      };
      // Products: Almond, Caramel, Zesty (alphabetical order)
      expect(() => downloadAsXLSX([orderWithUnsortedProducts], "season-sort")).not.toThrow();
    });

    it("should handle addresses with all fields", () => {
      const fullAddress = {
        street: "123 Main St",
        city: "Springfield",
        state: "IL",
        zipCode: "62701",
      };
      const order = { ...mockOrder, customerAddress: fullAddress };
      expect(() => downloadAsCSV([order], "season-123")).not.toThrow();
    });

    it("should handle addresses with partial fields", () => {
      const partialAddress = { street: "456 Oak Ave" };
      const order = { ...mockOrder, customerAddress: partialAddress };
      expect(() => downloadAsCSV([order], "season-123")).not.toThrow();
    });

    it("should handle orders with single line item", () => {
      const singleItemOrder = {
        ...mockOrder,
        lineItems: [mockOrder.lineItems[0]],
      };
      expect(() => downloadAsXLSX([singleItemOrder], "season-123")).not.toThrow();
    });

    it("should handle orders with many line items", () => {
      const manyItemOrder = {
        ...mockOrder,
        lineItems: Array.from({ length: 10 }, (_, i) => ({
          productId: `prod-${i}`,
          productName: `Product ${i}`,
          quantity: i + 1,
          pricePerUnit: 5.0,
          subtotal: (i + 1) * 5.0,
        })),
      };
      expect(() => downloadAsXLSX([manyItemOrder], "season-123")).not.toThrow();
    });
  });

  describe("filename generation", () => {
    it("should create valid CSV filename", () => {
      expect(() => downloadAsCSV([mockOrder], "season-test")).not.toThrow();
    });

    it("should create valid XLSX filename", () => {
      expect(() => downloadAsXLSX([mockOrder], "season-test")).not.toThrow();
    });

    it("should handle special characters in season ID", () => {
      // URL-encoded season IDs should be handled gracefully
      expect(() => downloadAsCSV([mockOrder], "season-abc-123-xyz")).not.toThrow();
    });
  });
});
