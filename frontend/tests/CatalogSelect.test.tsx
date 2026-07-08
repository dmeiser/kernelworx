/**
 * Tests for CatalogSelect component
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CatalogSelect } from '../src/components/CatalogSelect';

const publicCatalogs = [
  { catalogId: 'CAT~1', catalogName: '2025 Popcorn', isPublic: true },
  { catalogId: 'CAT~2', catalogName: '2025 Nuts', isPublic: true, catalogType: 'ADMIN_MANAGED' },
];

const myCatalogs = [{ catalogId: 'CAT~3', catalogName: 'My Custom', isPublic: false }];

describe('CatalogSelect', () => {
  test('renders with default label', () => {
    const onChange = vi.fn();
    render(<CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={[]} />);

    expect(screen.getByRole('combobox', { name: /product catalog/i })).toBeInTheDocument();
  });

  test('renders with custom label and required marker', () => {
    const onChange = vi.fn();
    render(
      <CatalogSelect
        value=""
        onChange={onChange}
        myCatalogs={[]}
        publicCatalogs={[]}
        label="Choose Catalog"
        required
      />,
    );

    expect(screen.getByRole('combobox', { name: /choose catalog \*/i })).toBeInTheDocument();
  });

  test('shows loading state', () => {
    const onChange = vi.fn();
    render(<CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={[]} loading />);

    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(screen.getByText('Loading catalogs...')).toBeInTheDocument();
  });

  test('shows empty message when no catalogs are available', () => {
    const onChange = vi.fn();
    render(<CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={[]} />);

    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(screen.getByText('No catalogs available')).toBeInTheDocument();
  });

  test('renders my catalogs group and public catalogs group', () => {
    const onChange = vi.fn();
    render(
      <CatalogSelect value="" onChange={onChange} myCatalogs={myCatalogs} publicCatalogs={publicCatalogs} />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));

    expect(screen.getByText('My Catalogs')).toBeInTheDocument();
    expect(screen.getByText('My Custom')).toBeInTheDocument();
    expect(screen.getByText('Public Catalogs')).toBeInTheDocument();
    expect(screen.getByText('2025 Popcorn')).toBeInTheDocument();
  });

  test('renders official suffix for admin managed catalogs', () => {
    const onChange = vi.fn();
    render(
      <CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={publicCatalogs} />,
    );

    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(screen.getByText('2025 Nuts (Official)')).toBeInTheDocument();
  });

  test('calls onChange when selection changes', () => {
    const onChange = vi.fn();
    render(<CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={publicCatalogs} />);

    fireEvent.mouseDown(screen.getByRole('combobox', { name: /product catalog/i }));
    fireEvent.click(screen.getByRole('option', { name: '2025 Popcorn' }));

    expect(onChange).toHaveBeenCalledWith('CAT~1');
  });

  test('is disabled when disabled prop is true and not loading', () => {
    const onChange = vi.fn();
    render(
      <CatalogSelect value="" onChange={onChange} myCatalogs={[]} publicCatalogs={[]} disabled />,
    );

    expect(screen.getByRole('combobox')).toHaveAttribute('aria-disabled', 'true');
  });

  test('is not disabled while loading even when disabled prop is true', () => {
    const onChange = vi.fn();
    render(
      <CatalogSelect
        value=""
        onChange={onChange}
        myCatalogs={[]}
        publicCatalogs={[]}
        disabled
        loading
      />,
    );

    expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-disabled', 'true');
  });
});
