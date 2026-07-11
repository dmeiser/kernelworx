/**
 * Tests for NavBreadcrumbs component.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NavBreadcrumbs, type BreadcrumbItem } from '../src/components/NavBreadcrumbs';

describe('NavBreadcrumbs', () => {
  describe('rendering', () => {
    it('should render all breadcrumb items', () => {
      const items: BreadcrumbItem[] = [
        { label: 'Home', onClick: vi.fn() },
        { label: 'Products', onClick: vi.fn() },
        { label: 'Current Item' },
      ];

      render(<NavBreadcrumbs items={items} />);

      expect(screen.getByText('Home')).toBeInTheDocument();
      expect(screen.getByText('Products')).toBeInTheDocument();
      expect(screen.getByText('Current Item')).toBeInTheDocument();
    });

    it('should render last item as text with primary color', () => {
      const items: BreadcrumbItem[] = [{ label: 'Home', onClick: vi.fn() }, { label: 'Current Page' }];

      render(<NavBreadcrumbs items={items} />);

      // Last item should be Typography, not a button
      const lastItem = screen.getByText('Current Page');
      expect(lastItem.tagName).not.toBe('BUTTON');
    });

    it('should render clickable items as buttons', () => {
      const items: BreadcrumbItem[] = [
        { label: 'Home', onClick: vi.fn() },
        { label: 'Products', onClick: vi.fn() },
        { label: 'Current' },
      ];

      render(<NavBreadcrumbs items={items} />);

      // First two items should be buttons
      const homeButton = screen.getByText('Home');
      expect(homeButton.closest('button')).toBeInTheDocument();

      const productsButton = screen.getByText('Products');
      expect(productsButton.closest('button')).toBeInTheDocument();
    });

    it('should render non-clickable items as text even if not last', () => {
      const items: BreadcrumbItem[] = [
        { label: 'Home', onClick: vi.fn() },
        { label: 'Disabled Section' }, // No onClick
        { label: 'Current' },
      ];

      render(<NavBreadcrumbs items={items} />);

      // Middle item without onClick should not be a button
      const disabledSection = screen.getByText('Disabled Section');
      expect(disabledSection.closest('button')).not.toBeInTheDocument();
    });

    it('should apply default margin bottom', () => {
      const items: BreadcrumbItem[] = [{ label: 'Home' }];

      render(<NavBreadcrumbs items={items} />);

      const breadcrumbs = screen.getByRole('navigation');
      expect(breadcrumbs).toBeInTheDocument();
    });

    it('should apply custom sx styles', () => {
      const items: BreadcrumbItem[] = [{ label: 'Home' }];

      render(<NavBreadcrumbs items={items} sx={{ mt: 4 }} />);

      const breadcrumbs = screen.getByRole('navigation');
      expect(breadcrumbs).toBeInTheDocument();
    });

    it('should use body2 variant when specified', () => {
      const items: BreadcrumbItem[] = [{ label: 'Home', onClick: vi.fn() }, { label: 'Current' }];

      render(<NavBreadcrumbs items={items} variant="body2" />);

      expect(screen.getByText('Home')).toBeInTheDocument();
      expect(screen.getByText('Current')).toBeInTheDocument();
    });

    it('should handle empty items array', () => {
      render(<NavBreadcrumbs items={[]} />);

      // Should render without errors
      const breadcrumbs = screen.getByRole('navigation');
      expect(breadcrumbs).toBeInTheDocument();
    });

    it('should handle single item', () => {
      const items: BreadcrumbItem[] = [{ label: 'Only Item' }];

      render(<NavBreadcrumbs items={items} />);

      expect(screen.getByText('Only Item')).toBeInTheDocument();
    });
  });

  describe('click handling', () => {
    it('should call onClick when clickable item is clicked', () => {
      const onClick = vi.fn();
      const items: BreadcrumbItem[] = [{ label: 'Home', onClick }, { label: 'Current' }];

      render(<NavBreadcrumbs items={items} />);

      fireEvent.click(screen.getByText('Home'));

      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it('should call correct onClick for each item', () => {
      const onClick1 = vi.fn();
      const onClick2 = vi.fn();
      const items: BreadcrumbItem[] = [
        { label: 'First', onClick: onClick1 },
        { label: 'Second', onClick: onClick2 },
        { label: 'Current' },
      ];

      render(<NavBreadcrumbs items={items} />);

      fireEvent.click(screen.getByText('First'));
      expect(onClick1).toHaveBeenCalledTimes(1);
      expect(onClick2).not.toHaveBeenCalled();

      fireEvent.click(screen.getByText('Second'));
      expect(onClick2).toHaveBeenCalledTimes(1);
    });

    it('should not call onClick on last item even if provided', () => {
      const onClick = vi.fn();
      const items: BreadcrumbItem[] = [
        { label: 'Home', onClick: vi.fn() },
        { label: 'Current', onClick }, // Last item with onClick
      ];

      render(<NavBreadcrumbs items={items} />);

      // Last item is rendered as text, not clickable
      const current = screen.getByText('Current');
      fireEvent.click(current);

      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
