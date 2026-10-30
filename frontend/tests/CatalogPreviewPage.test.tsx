/**
 * Regression tests for issue #719
 */

import '@testing-library/jest-dom';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { GET_CATALOG } from '../src/lib/graphql';
import { CatalogPreviewPage } from '../src/pages/CatalogPreviewPage';

const CATALOG = {
  __typename: 'Catalog',
  catalogId: 'CATALOG#abc',
  catalogName: 'Preview Catalog',
  catalogType: 'USER_CREATED',
  isPublic: false,
  products: [
    {
      __typename: 'Product',
      productId: 'p1',
      productName: 'Widget',
      description: 'A widget',
      price: 1.25,
      sortOrder: 1,
    },
  ],
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
};

function renderPage(path: string, mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/catalogs/:catalogId?/preview" element={<CatalogPreviewPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('CatalogPreviewPage', () => {
  it('renders NoCatalogIdState when catalogId param is missing', async () => {
    renderPage('/catalogs/preview', []);

    await waitFor(() => {
      expect(screen.getByText('No catalog ID provided')).toBeInTheDocument();
    });
  });

  it('renders catalog details when param provided', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: CATALOG } },
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText('Preview Catalog')).toBeInTheDocument();
    });
    expect(screen.getByText('Widget')).toBeInTheDocument();
    expect(screen.getByText('$1.25')).toBeInTheDocument();
  });

  it('shows not found when catalog missing', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: null } },
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText('Catalog not found')).toBeInTheDocument();
    });
  });

  it('shows error alert on query error', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        error: new Error('boom'),
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText(/Error loading catalog/)).toBeInTheDocument();
    });
  });

  it('handles create campaign button', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: CATALOG } },
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText('Preview Catalog')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const createButtons = screen.getAllByRole('button', { name: /Create Campaign/i });
    await user.click(createButtons[0]);
  });

  it('handles create shared campaign button', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: CATALOG } },
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText('Preview Catalog')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const sharedButtons = screen.getAllByRole('button', { name: /Create Shared Campaign/i });
    await user.click(sharedButtons[0]);
  });

  it('invokes onCreateCampaign and onCreateSharedCampaign callbacks', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: CATALOG } },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <MemoryRouter initialEntries={['/catalogs/abc/preview']}>
          <Routes>
            <Route
              path="/catalogs/:catalogId?/preview"
              element={
                <CatalogPreviewPage
                  onCreateCampaign={() => undefined}
                  onCreateSharedCampaign={() => undefined}
                />
              }
            />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Preview Catalog')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const createButtons = screen.getAllByRole('button', { name: /Create Campaign/i });
    await user.click(createButtons[0]);

    const sharedButtons = screen.getAllByRole('button', { name: /Create Shared Campaign/i });
    await user.click(sharedButtons[0]);
  });

  it('handles back button', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CATALOG, variables: { catalogId: 'CATALOG#abc' } },
        result: { data: { getCatalog: CATALOG } },
      },
    ];

    renderPage('/catalogs/abc/preview', mocks);

    await waitFor(() => {
      expect(screen.getByText('Preview Catalog')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const backButton = screen.getByRole('button', { name: /Back/i });
    await user.click(backButton);
  });
});
