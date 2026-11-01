/**
 * Tests for ProductPicker.
 *
 * A buyer types quantities one keystroke at a time, and every keystroke replaces
 * the hook's `lineItems` object, so the picker re-renders constantly. Each row is
 * memoized on the primitives it depends on, and the render-count assertions below
 * are what prove it: a getter on `productName` counts how often a row's render
 * body actually ran, so a keystroke in one box that re-rendered the whole catalog
 * fails here rather than only showing up as jank on a phone at an event booth.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ProductPicker } from '../../../src/components/public/ProductPicker';
import { MAX_PUBLIC_QUANTITY } from '../../../src/lib/publicOrderValidation';
import type { PublicProductView } from '../../../src/components/public/publicOrderTypes';

/**
 * A product view whose name reads are counted. ProductRow touches
 * `productName` in its render body, so the counter is a direct proxy for
 * "did this row re-render".
 */
const trackedProduct = (productId: string, price: number, reads: Record<string, number>): PublicProductView => ({
  productId,
  price,
  description: null,
  get productName() {
    reads[productId] = (reads[productId] ?? 0) + 1;
    return `Product ${productId}`;
  },
});

describe('ProductPicker', () => {
  it('renders one row per product with its price', () => {
    const products: PublicProductView[] = [
      { productId: 'P1', productName: 'Cookie Box', price: 10, description: 'Twelve cookies' },
      { productId: 'P2', productName: 'Magazine', price: 4 },
    ];
    render(<ProductPicker products={products} quantities={{}} onQuantityChange={vi.fn()} />);
    expect(screen.getByTestId('product-row-P1')).toBeInTheDocument();
    expect(screen.getByTestId('product-row-P2')).toBeInTheDocument();
    expect(screen.getByText('Cookie Box')).toBeInTheDocument();
    expect(screen.getByText('$10.00')).toBeInTheDocument();
    expect(screen.getByText('Twelve cookies')).toBeInTheDocument();
  });

  it('explains an empty catalog instead of rendering an empty list', () => {
    render(<ProductPicker products={[]} quantities={{}} onQuantityChange={vi.fn()} />);
    expect(screen.getByText('This seller has no products listed right now.')).toBeInTheDocument();
  });

  it('shows the picker error text', () => {
    render(
      <ProductPicker
        products={[{ productId: 'P1', productName: 'Cookie Box', price: 10 }]}
        quantities={{}}
        onQuantityChange={vi.fn()}
        errorText="At least one product with quantity greater than zero is required"
      />,
    );
    expect(screen.getByText('At least one product with quantity greater than zero is required')).toBeInTheDocument();
  });

  it('reports a typed quantity for the right product', () => {
    const onQuantityChange = vi.fn();
    const products: PublicProductView[] = [
      { productId: 'P1', productName: 'Cookie Box', price: 10 },
      { productId: 'P2', productName: 'Magazine', price: 4 },
    ];
    render(<ProductPicker products={products} quantities={{}} onQuantityChange={onQuantityChange} />);
    fireEvent.change(screen.getByLabelText('Quantity for Magazine'), { target: { value: '3' } });
    expect(onQuantityChange).toHaveBeenCalledWith('P2', 3);
  });

  it('turns an empty input into a zero quantity rather than NaN', () => {
    const onQuantityChange = vi.fn();
    render(
      <ProductPicker
        products={[{ productId: 'P1', productName: 'Cookie Box', price: 10 }]}
        quantities={{}}
        onQuantityChange={onQuantityChange}
      />,
    );
    fireEvent.change(screen.getByLabelText('Quantity for Cookie Box'), { target: { value: '' } });
    expect(onQuantityChange).toHaveBeenCalledWith('P1', 0);
  });

  it('bounds the quantity input to the picker range', () => {
    render(
      <ProductPicker
        products={[{ productId: 'P1', productName: 'Cookie Box', price: 10 }]}
        quantities={{}}
        onQuantityChange={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('Quantity for Cookie Box');
    expect(input).toHaveAttribute('min', '0');
    expect(input).toHaveAttribute('max', String(MAX_PUBLIC_QUANTITY));
  });

  it('shows the quantity the form state carries for each product', () => {
    render(
      <ProductPicker
        products={[
          { productId: 'P1', productName: 'Cookie Box', price: 10 },
          { productId: 'P2', productName: 'Magazine', price: 4 },
        ]}
        quantities={{ P1: 5 }}
        onQuantityChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Quantity for Cookie Box')).toHaveValue(5);
    expect(screen.getByLabelText('Quantity for Magazine')).toHaveValue(0);
  });
});

describe('ProductPicker row memoization', () => {
  it('re-renders only the row whose quantity changed', () => {
    const reads: Record<string, number> = {};
    const products = [trackedProduct('P1', 10, reads), trackedProduct('P2', 4, reads), trackedProduct('P3', 7, reads)];
    const onQuantityChange = vi.fn();

    const view = render(
      <ProductPicker products={products} quantities={{ P1: 1, P2: 1, P3: 1 }} onQuantityChange={onQuantityChange} />,
    );
    const baseline = { ...reads };
    expect(baseline.P1).toBeGreaterThan(0);

    // One keystroke: the quantities object is replaced, but only P2's value moves.
    view.rerender(
      <ProductPicker products={products} quantities={{ P1: 1, P2: 2, P3: 1 }} onQuantityChange={onQuantityChange} />,
    );

    expect(reads.P2).toBeGreaterThan(baseline.P2);
    expect(reads.P1).toBe(baseline.P1);
    expect(reads.P3).toBe(baseline.P3);
  });

  it('does not re-render any row when only the callback identity is stable and nothing changed', () => {
    const reads: Record<string, number> = {};
    const products = [trackedProduct('P1', 10, reads), trackedProduct('P2', 4, reads)];
    const onQuantityChange = vi.fn();

    const view = render(<ProductPicker products={products} quantities={{ P1: 1 }} onQuantityChange={onQuantityChange} />);
    const baseline = { ...reads };

    view.rerender(<ProductPicker products={products} quantities={{ P1: 1 }} onQuantityChange={onQuantityChange} />);

    expect(reads.P1).toBe(baseline.P1);
    expect(reads.P2).toBe(baseline.P2);
  });
});
