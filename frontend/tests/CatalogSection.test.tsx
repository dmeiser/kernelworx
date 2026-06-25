/**
 * Tests for CatalogSection component
 */

import React from 'react';
import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { SelectProps } from '@mui/material';
import { CatalogSection } from '../src/components/CatalogSection';

const publicCatalogs = [
  { catalogId: 'CAT~1', catalogName: '2025 Popcorn', products: [], isPublic: true },
  { catalogId: 'CAT~2', catalogName: '2025 Nuts', products: [], isPublic: true },
];

const myCatalogs = [{ catalogId: 'CAT~3', catalogName: 'My Custom', products: [], isPublic: false }];

describe('CatalogSection', () => {
  test('renders default label and select', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={myCatalogs}
      />,
    );

    expect(screen.getByText('Product Catalog')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  test('renders custom label', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={[]}
        myCatalogs={[]}
        label="Choose Catalog"
      />,
    );

    expect(screen.getByText('Choose Catalog')).toBeInTheDocument();
  });

  test('shows loading state', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={true}
        filteredPublicCatalogs={[]}
        myCatalogs={[]}
      />,
    );

    // Select should be disabled during loading
    const selectButton = screen.getByRole('combobox');
    expect(selectButton).toHaveAttribute('aria-disabled', 'true');
  });

  test('renders public and personal catalog groups', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={myCatalogs}
      />,
    );

    // Open the select dropdown
    fireEvent.mouseDown(screen.getByRole('combobox'));

    // Public group header + items
    expect(screen.getByText('Public Catalogs')).toBeInTheDocument();
    expect(screen.getByText('2025 Popcorn')).toBeInTheDocument();
    expect(screen.getByText('2025 Nuts')).toBeInTheDocument();

    // My Catalogs group header + items
    expect(screen.getByText('My Catalogs')).toBeInTheDocument();
    expect(screen.getByText('My Custom')).toBeInTheDocument();
  });

  test('shows "No catalogs available" when both lists empty and not loading', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={[]}
        myCatalogs={[]}
      />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(screen.getByText('No catalogs available')).toBeInTheDocument();
  });

  test('calls onCatalogChange on selection', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('2025 Popcorn'));
    expect(onChange).toHaveBeenCalledWith('CAT~1');
  });

  test('displays selected catalog name as render value', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId="CAT~1"
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    // The select should display the catalog name for selected value
    expect(screen.getByRole('combobox')).toHaveTextContent('2025 Popcorn');
  });

  test('renders empty string for unknown catalog ID in renderValue', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId="CAT~unknown"
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    // Should render empty since the catalogId is not in allCatalogs
    const select = screen.getByRole('combobox');
    // MUI renders a zero-width space (U+200B) for empty select display
    expect(select.textContent?.replace(/\u200B/g, '')).toBe('');
  });

  test('renders empty string when catalogId is empty in renderValue', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    const select = screen.getByRole('combobox');
    expect(select.textContent?.replace(/\u200B/g, '')).toBe('');
  });

  test('removes aria-hidden from root element when select opens', () => {
    const root = document.createElement('div');
    root.id = 'root';
    root.setAttribute('aria-hidden', 'true');
    document.body.appendChild(root);
    const removeAttrSpy = vi.spyOn(root, 'removeAttribute');

    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));

    expect(removeAttrSpy).toHaveBeenCalledWith('aria-hidden');

    document.body.removeChild(root);
  });

  test('handleOpen does nothing when root element is absent', () => {
    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    expect(() => fireEvent.mouseDown(screen.getByRole('combobox'))).not.toThrow();
  });

  test('handleOpen leaves root alone when aria-hidden is not true', () => {
    const root = document.createElement('div');
    root.id = 'root';
    root.setAttribute('aria-hidden', 'false');
    document.body.appendChild(root);
    const removeAttrSpy = vi.spyOn(root, 'removeAttribute');

    const onChange = vi.fn();
    render(
      <CatalogSection
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));

    expect(removeAttrSpy).not.toHaveBeenCalled();

    document.body.removeChild(root);
  });
});

describe('CatalogSection renderValue edge case', () => {
  afterEach(() => {
    vi.doUnmock('@mui/material');
  });

  test('returns empty string when MUI invokes renderValue with an empty value', async () => {
    vi.resetModules();
    vi.doMock('@mui/material', async (importOriginal) => {
      const actual = await importOriginal<typeof import('@mui/material')>();
      const MockSelect = React.forwardRef<HTMLDivElement, SelectProps<string>>((props, ref) => {
        const renderedValue = props.renderValue ? props.renderValue('') : '';
        return (
          <div ref={ref} role="combobox" data-testid="mock-select">
            {renderedValue}
          </div>
        );
      });
      return { ...actual, Select: MockSelect };
    });

    const { CatalogSection: CatalogSectionMocked } = await import('../src/components/CatalogSection');
    const onChange = vi.fn();
    render(
      <CatalogSectionMocked
        catalogId=""
        onCatalogChange={onChange}
        catalogsLoading={false}
        filteredPublicCatalogs={publicCatalogs}
        myCatalogs={[]}
      />,
    );

    expect(screen.getByTestId('mock-select')).toHaveTextContent('');
  });
});
