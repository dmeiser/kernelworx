/**
 * RouteErrorBoundary tests
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouteErrorBoundary } from './RouteErrorBoundary';

const ThrowingChild: React.FC = () => {
  throw new Error('Test route error');
};

describe('RouteErrorBoundary', () => {
  it('renders children when no error is thrown', () => {
    render(
      <RouteErrorBoundary>
        <div data-testid="child">Hello</div>
      </RouteErrorBoundary>,
    );

    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('renders an error message and reload button when a child throws', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <RouteErrorBoundary>
        <ThrowingChild />
      </RouteErrorBoundary>,
    );

    expect(screen.getByText(/This page failed to load/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload page/i })).toBeInTheDocument();
    expect(screen.getByText('Test route error')).toBeInTheDocument();

    consoleError.mockRestore();
  });

  it('reloads the page when the reload button is clicked', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const reloadMock = vi.fn();
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...window.location, reload: reloadMock },
    });

    render(
      <RouteErrorBoundary>
        <ThrowingChild />
      </RouteErrorBoundary>,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /reload page/i }));
    expect(reloadMock).toHaveBeenCalled();

    consoleError.mockRestore();
  });
});
