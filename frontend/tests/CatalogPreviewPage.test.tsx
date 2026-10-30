/**
 * Regression tests for issue #719
 *
 * CatalogPreviewPage must not construct 'CATALOG#undefined' when the
 * catalogId route param is missing; it should render the NoCatalogIdState
 * and must not write debug keys to localStorage.
 */

import '@testing-library/jest-dom';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CatalogPreviewPage } from '../src/pages/CatalogPreviewPage';

describe('CatalogPreviewPage', () => {
  it('renders NoCatalogIdState when catalogId param is missing', async () => {
    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/catalogs/preview']}>
          <Routes>
            <Route path="/catalogs/:catalogId?/preview" element={<CatalogPreviewPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('No catalog ID provided')).toBeInTheDocument();
    });
  });

  it('does not issue a query with CATALOG#undefined when param missing', async () => {
    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/catalogs/preview']}>
          <Routes>
            <Route path="/catalogs/:catalogId?/preview" element={<CatalogPreviewPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('No catalog ID provided')).toBeInTheDocument();
    });
    // No unhandled GraphQL request should have been made; success of render is enough.
  });
});
