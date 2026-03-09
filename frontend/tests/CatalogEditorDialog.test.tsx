/**
 * Tests for CatalogEditorDialog component
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CatalogEditorDialog } from '../src/components/CatalogEditorDialog';
import type { Catalog } from '../src/types';

const mockOnClose = vi.fn();
const mockOnSave = vi.fn();

const existingCatalog: Catalog = {
  catalogId: 'CAT~1',
  catalogName: '2025 Popcorn',
  isPublic: true,
  products: [
    { productId: 'PROD~1', productName: 'Caramel Corn', price: 20, description: 'Delicious caramel' },
    { productId: 'PROD~2', productName: 'Butter Popcorn', price: 15 },
  ],
};

describe('CatalogEditorDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOnSave.mockResolvedValue(undefined);
  });

  describe('create mode', () => {
    test('renders create dialog with empty form', () => {
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      expect(screen.getByText('Create Catalog')).toBeInTheDocument();
      expect(screen.getByLabelText(/Catalog Name/i)).toHaveValue('');
      // Should have one default empty product row
      expect(screen.getByText('Product 1')).toBeInTheDocument();
    });

    test('does not render when closed', () => {
      render(<CatalogEditorDialog open={false} onClose={mockOnClose} onSave={mockOnSave} />);
      expect(screen.queryByText('Create Catalog')).not.toBeInTheDocument();
    });

    test('validates empty catalog name', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      await user.click(screen.getByRole('button', { name: /save catalog/i }));
      expect(screen.getByText('Catalog name is required')).toBeInTheDocument();
      expect(mockOnSave).not.toHaveBeenCalled();
    });

    test('validates empty product name', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      // Fill catalog name but leave product name empty
      await user.type(screen.getByLabelText(/Catalog Name/i), 'Test Catalog');
      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      expect(screen.getByText('Product 1 name is required')).toBeInTheDocument();
      expect(mockOnSave).not.toHaveBeenCalled();
    });

    test('validates product price must be > 0', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      fireEvent.change(screen.getByLabelText(/Catalog Name/i), { target: { value: 'Test Catalog' } });
      fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Good Product' } });
      // Price defaults to 0
      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      expect(screen.getByText('Product 1 price must be greater than 0')).toBeInTheDocument();
    });

    test('saves catalog with valid data', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      fireEvent.change(screen.getByLabelText(/Catalog Name/i), { target: { value: 'New Catalog' } });
      fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Caramel Corn' } });

      // Set the price
      const priceInput = screen.getByLabelText(/Price/i);
      fireEvent.change(priceInput, { target: { value: '20' } });

      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalledWith({
          catalogName: 'New Catalog',
          isPublic: true,
          products: [
            {
              productName: 'Caramel Corn',
              description: undefined,
              price: 20,
              sortOrder: 0,
            },
          ],
        });
      });
      expect(mockOnClose).toHaveBeenCalled();
    });

    test('adds new product row', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      await user.click(screen.getByRole('button', { name: /add product/i }));

      expect(screen.getByText('Product 1')).toBeInTheDocument();
      expect(screen.getByText('Product 2')).toBeInTheDocument();
    });

    test('removes product row when more than one exists', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      // Add a second product
      await user.click(screen.getByRole('button', { name: /add product/i }));
      expect(screen.getByText('Product 2')).toBeInTheDocument();

      // Delete buttons should now be visible (since 2 products exist)
      // MUI IconButton with DeleteIcon doesn't have aria-label, find by test approach
      const deleteButtons = document.querySelectorAll('button[aria-label="delete"], svg[data-testid="DeleteIcon"]');
      // Use closest button for the SVG icon approach
      const deleteBtn = deleteButtons.length > 0
        ? (deleteButtons[0].closest('button') ?? deleteButtons[0] as HTMLElement)
        : null;
      expect(deleteBtn).not.toBeNull();
      await user.click(deleteBtn!);

      // Should be back to one product
      expect(screen.queryByText('Product 2')).not.toBeInTheDocument();
    });

    test('does not show delete button with only one product', () => {
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);
      // With only one product, delete icons should not appear
      const deleteIcons = document.querySelectorAll('svg[data-testid="DeleteIcon"]');
      expect(deleteIcons.length).toBe(0);
    });

    test('handles product field changes', async () => {
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      // Use fireEvent for speed - userEvent.type is too slow for MUI TextFields
      fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Butter Popcorn' } });
      expect(screen.getByLabelText(/Product Name/i)).toHaveValue('Butter Popcorn');

      fireEvent.change(screen.getByPlaceholderText(/Brief description/i), { target: { value: 'Tasty butter' } });
      expect(screen.getByPlaceholderText(/Brief description/i)).toHaveValue('Tasty butter');
    });

    test('cancel calls onClose', async () => {
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      await user.click(screen.getByRole('button', { name: /cancel/i }));
      expect(mockOnClose).toHaveBeenCalled();
    });

    test('shows error when onSave rejects', async () => {
      mockOnSave.mockRejectedValue(new Error('Network error'));
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      fireEvent.change(screen.getByLabelText(/Catalog Name/i), { target: { value: 'Test' } });
      fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Prod' } });
      const priceInput = screen.getByLabelText(/Price/i);
      fireEvent.change(priceInput, { target: { value: '10' } });

      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
      expect(mockOnClose).not.toHaveBeenCalled();
    });

    test('shows generic error when onSave rejects with non-Error', async () => {
      mockOnSave.mockRejectedValue('plain string error');
      const user = userEvent.setup();
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);

      fireEvent.change(screen.getByLabelText(/Catalog Name/i), { target: { value: 'Test' } });
      fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Prod' } });
      const priceInput = screen.getByLabelText(/Price/i);
      fireEvent.change(priceInput, { target: { value: '10' } });

      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      await waitFor(() => {
        expect(screen.getByText('Failed to save catalog')).toBeInTheDocument();
      });
    });

    test('shows Privacy Notice info box', () => {
      render(<CatalogEditorDialog open={true} onClose={mockOnClose} onSave={mockOnSave} />);
      expect(screen.getByText('Privacy Notice')).toBeInTheDocument();
    });
  });

  describe('edit mode', () => {
    test('renders edit dialog with existing catalog data', () => {
      render(
        <CatalogEditorDialog
          open={true}
          onClose={mockOnClose}
          onSave={mockOnSave}
          initialCatalog={existingCatalog}
        />,
      );

      expect(screen.getByText('Edit Catalog')).toBeInTheDocument();
      expect(screen.getByLabelText(/Catalog Name/i)).toHaveValue('2025 Popcorn');
      expect(screen.getByText('Product 1')).toBeInTheDocument();
      expect(screen.getByText('Product 2')).toBeInTheDocument();
    });

    test('saves updated catalog', async () => {
      const user = userEvent.setup();
      render(
        <CatalogEditorDialog
          open={true}
          onClose={mockOnClose}
          onSave={mockOnSave}
          initialCatalog={existingCatalog}
        />,
      );

      // Change catalog name
      const nameInput = screen.getByLabelText(/Catalog Name/i);
      fireEvent.change(nameInput, { target: { value: 'Updated Catalog' } });

      await user.click(screen.getByRole('button', { name: /save catalog/i }));

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalled();
        const savedData = mockOnSave.mock.calls[0][0];
        expect(savedData.catalogName).toBe('Updated Catalog');
        expect(savedData.products).toHaveLength(2);
      });
    });
  });
});
