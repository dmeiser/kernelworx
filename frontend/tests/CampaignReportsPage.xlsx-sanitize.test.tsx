/**
 * End-to-end behavior test for CampaignReportsPage XLSX sanitization.
 *
 * Verifies that user-controlled seller and customer names are neutralized
 * in the generated Seller Report and Order Details Excel workbooks before
 * XLSX.writeFile is called, preventing formula injection (#141).
 */
import '@testing-library/jest-dom';
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('xlsx', async (importOriginal) => {
  const mod = await importOriginal<typeof import('xlsx')>();
  return {
    ...mod,
    writeFile: vi.fn(),
  };
});

import * as XLSX from 'xlsx';
import { CampaignReportsPage } from '../src/pages/CampaignReportsPage';
import { GET_UNIT_REPORT, LIST_MY_SHARED_CAMPAIGNS } from '../src/lib/graphql';

const EVIDENCE_DIR = '/tmp/no-mistakes-evidence/01M0Z2DY7179BRQ3XMQRNZ9ZVX';

const TEST_CAMPAIGN = {
  __typename: 'SharedCampaign' as const,
  sharedCampaignCode: 'shared-abc',
  catalogId: 'catalog-1',
  campaignName: 'Fall Fundraiser',
  campaignYear: 2025,
  startDate: '2025-01-01',
  endDate: '2025-12-31',
  unitType: 'Troop',
  unitNumber: 101,
  city: 'Springfield',
  state: 'IL',
  createdBy: 'owner-1',
  createdByName: 'Owner One',
  creatorMessage: '',
  description: '',
  isActive: true,
  createdAt: '2025-01-01T00:00:00Z',
};

// Formula-triggering names simulate a malicious seller/customer trying to
// inject a spreadsheet formula.
const MALICIOUS_SELLER_NAME = '=HYPERLINK("http://evil.example","Scout Alpha")';
const MALICIOUS_CUSTOMER_NAME = '@SUM(A:A)';
const SAFE_SELLER_NAME = 'Scout Beta';

const UNIT_REPORT = {
  __typename: 'UnitReport' as const,
  unitType: 'Troop',
  unitNumber: 101,
  campaignName: 'Fall Fundraiser',
  campaignYear: 2025,
  totalSales: 120,
  totalOrders: 2,
  sellers: [
    {
      __typename: 'UnitSellerSummary' as const,
      profileId: 'profile-a',
      sellerName: MALICIOUS_SELLER_NAME,
      totalSales: 80,
      orderCount: 1,
      orders: [
        {
          __typename: 'UnitOrderDetail' as const,
          orderId: 'order-1',
          customerName: MALICIOUS_CUSTOMER_NAME,
          orderDate: '2025-02-01T00:00:00Z',
          totalAmount: 80,
          lineItems: [
            {
              __typename: 'LineItem' as const,
              productId: 'prod-1',
              productName: 'Caramel Corn',
              quantity: 4,
              pricePerUnit: 10,
              subtotal: 40,
            },
            {
              __typename: 'LineItem' as const,
              productId: 'prod-2',
              productName: 'Butter Corn',
              quantity: 4,
              pricePerUnit: 10,
              subtotal: 40,
            },
          ],
        },
      ],
    },
    {
      __typename: 'UnitSellerSummary' as const,
      profileId: 'profile-b',
      sellerName: SAFE_SELLER_NAME,
      totalSales: 40,
      orderCount: 1,
      orders: [
        {
          __typename: 'UnitOrderDetail' as const,
          orderId: 'order-2',
          customerName: 'Plain Customer',
          orderDate: '2025-02-02T00:00:00Z',
          totalAmount: 40,
          lineItems: [
            {
              __typename: 'LineItem' as const,
              productId: 'prod-1',
              productName: 'Caramel Corn',
              quantity: 2,
              pricePerUnit: 10,
              subtotal: 20,
            },
            {
              __typename: 'LineItem' as const,
              productId: 'prod-2',
              productName: 'Butter Corn',
              quantity: 2,
              pricePerUnit: 10,
              subtotal: 20,
            },
          ],
        },
      ],
    },
  ],
};

function createMocks(): MockedResponse[] {
  return [
    {
      request: {
        query: LIST_MY_SHARED_CAMPAIGNS,
      },
      result: {
        data: {
          __typename: 'Query',
          listMySharedCampaigns: [TEST_CAMPAIGN],
        },
      },
    },
    {
      request: {
        query: GET_UNIT_REPORT,
        variables: {
          unitType: TEST_CAMPAIGN.unitType,
          unitNumber: TEST_CAMPAIGN.unitNumber,
          city: TEST_CAMPAIGN.city,
          state: TEST_CAMPAIGN.state,
          campaignName: TEST_CAMPAIGN.campaignName,
          campaignYear: TEST_CAMPAIGN.campaignYear,
          catalogId: TEST_CAMPAIGN.catalogId,
        },
      },
      result: () => ({
        data: {
          __typename: 'Query',
          getUnitReport: UNIT_REPORT,
        },
      }),
    },
  ];
}

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <MemoryRouter initialEntries={['/reports']}>
        <Routes>
          <Route path="/reports" element={<CampaignReportsPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

function rowsFromWorkbook(wb: XLSX.WorkBook, sheetName: string) {
  const ws = wb.Sheets[sheetName];
  if (!ws) {
    throw new Error(`Sheet "${sheetName}" not found in workbook`);
  }
  return XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' }) as unknown[][];
}

describe('CampaignReportsPage XLSX formula injection sanitization', () => {
  const writeFileMock = vi.mocked(XLSX.writeFile);

  beforeEach(() => {
    writeFileMock.mockImplementation(() => undefined);
    writeFileMock.mockClear();
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('seller report neutralizes formula-triggering seller names before writing', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    // Wait for campaign auto-selection and generate the report.
    const generateButton = await screen.findByRole('button', { name: /Generate Report/i });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    await user.click(generateButton);

    await screen.findByText('Unit Overview');
    await user.click(screen.getByRole('button', { name: /Seller Report/i }));
    await user.click(screen.getByRole('button', { name: /Export to Excel/i }));

    await waitFor(() => expect(writeFileMock).toHaveBeenCalledTimes(1));
    const workbook = writeFileMock.mock.calls[0][0] as XLSX.WorkBook;
    expect(workbook).toBeDefined();

    const rows = rowsFromWorkbook(workbook, 'Seller Report');

    // First data row is the malicious seller; cell A2 should be text, not a formula.
    const sellerCell = rows[1][0];
    expect(sellerCell).toBe(`'${MALICIOUS_SELLER_NAME}`);

    // Static header and total labels are safe and pass through unchanged.
    expect(rows[0][0]).toBe('Scout Name');
    expect(rows[3][0]).toBe('Total');

    // Write an artifact so reviewers can open the generated file.
    const buffer = XLSX.write(workbook, { bookType: 'xlsx', type: 'buffer' });
    const artifactPath = path.join(EVIDENCE_DIR, 'seller-report-sanitized.xlsx');
    fs.writeFileSync(artifactPath, Buffer.from(buffer));
  });

  test('order details report neutralizes formula-triggering seller and customer names', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    const generateButton = await screen.findByRole('button', { name: /Generate Report/i });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    await user.click(generateButton);

    await screen.findByText('Unit Overview');
    await user.click(screen.getByRole('button', { name: /Order Details/i }));
    await user.click(screen.getByRole('button', { name: /Export to Excel/i }));

    await waitFor(() => expect(writeFileMock).toHaveBeenCalledTimes(1));
    const workbook = writeFileMock.mock.calls[0][0] as XLSX.WorkBook;
    expect(workbook).toBeDefined();

    const rows = rowsFromWorkbook(workbook, 'Order Details');

    // Malicious seller and customer names should be prefixed with an apostrophe.
    const sellerCell = rows[1][0];
    const customerCell = rows[1][1];
    expect(sellerCell).toBe(`'${MALICIOUS_SELLER_NAME}`);
    expect(customerCell).toBe(`'${MALICIOUS_CUSTOMER_NAME}`);

    // Safe names pass through unchanged.
    const safeRow = rows.find((row) => row[0] === SAFE_SELLER_NAME);
    expect(safeRow).toBeDefined();
    expect(safeRow![1]).toBe('Plain Customer');

    const buffer = XLSX.write(workbook, { bookType: 'xlsx', type: 'buffer' });
    const artifactPath = path.join(EVIDENCE_DIR, 'order-details-report-sanitized.xlsx');
    fs.writeFileSync(artifactPath, Buffer.from(buffer));
  });
});
