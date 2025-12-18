/**
 * Tests for Toast component
 * 
 * Tests toast notifications from GraphQL error events
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Toast } from '../src/components/Toast';

describe('Toast', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders without errors', () => {
    render(<Toast />);
    // Toast starts hidden
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('displays error message when graphql-error event is dispatched', async () => {
    render(<Toast />);

    // Dispatch a graphql-error event
    const errorEvent = new CustomEvent('graphql-error', {
      detail: {
        errorCode: 'UNAUTHORIZED',
        message: 'You are not authorized to perform this action',
        operation: 'createProfile',
      },
    });
    window.dispatchEvent(errorEvent);

    // Wait for toast to appear
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    expect(screen.getByText('You are not authorized to perform this action')).toBeInTheDocument();
  });

  it('displays default error message when no message provided', async () => {
    render(<Toast />);

    // Dispatch event with no message
    const errorEvent = new CustomEvent('graphql-error', {
      detail: {
        errorCode: 'UNKNOWN',
        message: '',
        operation: 'someOperation',
      },
    });
    window.dispatchEvent(errorEvent);

    await waitFor(() => {
      expect(screen.getByText('An error occurred')).toBeInTheDocument();
    });
  });

  it('displays error severity alert', async () => {
    render(<Toast />);

    const errorEvent = new CustomEvent('graphql-error', {
      detail: {
        errorCode: 'SERVER_ERROR',
        message: 'Server error occurred',
        operation: 'query',
      },
    });
    window.dispatchEvent(errorEvent);

    await waitFor(() => {
      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      // MUI Alert with severity="error" has class MuiAlert-standardError
      expect(alert.className).toContain('MuiAlert-standardError');
    });
  });

  it('closes toast when close button is clicked on alert', async () => {
    const { rerender } = render(<Toast />);

    const errorEvent = new CustomEvent('graphql-error', {
      detail: {
        errorCode: 'TEST_ERROR',
        message: 'Test error message',
        operation: 'test',
      },
    });
    window.dispatchEvent(errorEvent);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    // Find and click the close button on the Alert
    const closeButtons = screen.getAllByRole('button');
    const alertCloseButton = closeButtons.find(
      (btn) => btn.className && btn.className.includes('MuiAlert-action'),
    );

    if (alertCloseButton) {
      alertCloseButton.click();

      // Toast should be closed after clicking
      await waitFor(() => {
        expect(screen.queryByText('Test error message')).not.toBeInTheDocument();
      });
    }
  });

  it('cleans up event listener on unmount', () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');

    const { unmount } = render(<Toast />);

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('graphql-error', expect.any(Function));

    removeEventListenerSpy.mockRestore();
  });
});
