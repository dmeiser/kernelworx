/**
 * RouteErrorBoundary tests
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouteErrorBoundary, isChunkLoadError } from './RouteErrorBoundary';

const ThrowingChild: React.FC = () => {
  throw new Error('Failed to fetch dynamically imported module');
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

import { ErrorBoundary } from './ErrorBoundary';

describe('RouteErrorBoundary non-chunk errors', () => {
  it('lets non-chunk runtime errors fall through to the outer ErrorBoundary without exposing raw text', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const NonChunkThrowingChild: React.FC = () => {
      throw new Error('Sensitive internal details');
    };

    render(
      <ErrorBoundary>
        <RouteErrorBoundary>
          <NonChunkThrowingChild />
        </RouteErrorBoundary>
      </ErrorBoundary>,
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.queryByText(/This page failed to load/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Sensitive internal details')).not.toBeInTheDocument();

    consoleError.mockRestore();
  });
});


describe('isChunkLoadError', () => {
  it('returns false for non-Error values', () => {
    expect(isChunkLoadError(null)).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });

  it('returns true when the error name is ChunkLoadError', () => {
    const error = new Error('something else');
    error.name = 'ChunkLoadError';
    expect(isChunkLoadError(error)).toBe(true);
  });

  it('returns true for chunk-load messages', () => {
    expect(isChunkLoadError(new Error('Failed to fetch dynamically imported module'))).toBe(true);
    expect(isChunkLoadError(new Error('Loading chunk 123 failed'))).toBe(true);
  });

  it('returns false for ordinary runtime errors', () => {
    expect(isChunkLoadError(new Error('Test route error'))).toBe(false);
  });
});
