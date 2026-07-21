import { useState, useCallback } from 'react';

interface UseSnackbarReturn {
  /** Current snackbar message, or null when hidden */
  message: string | null;
  /** Whether the snackbar is currently open */
  open: boolean;
  /** Show the snackbar with the given message */
  show: (message: string) => void;
  /** Close the snackbar */
  close: () => void;
}

/**
 * Reusable hook for showing a single-message snackbar.
 *
 * Use for short-lived success/error/info notifications that auto-hide.
 */
export const useSnackbar = (): UseSnackbarReturn => {
  const [message, setMessage] = useState<string | null>(null);

  const show = useCallback((newMessage: string) => {
    setMessage(newMessage);
  }, []);

  const close = useCallback(() => {
    setMessage(null);
  }, []);

  return {
    message,
    open: message !== null,
    show,
    close,
  };
};
