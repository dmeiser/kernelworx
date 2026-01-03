import React, { useEffect, useState } from 'react';
import Snackbar from '@mui/material/Snackbar';
import Alert from '@mui/material/Alert';
import { setupGraphQLErrorListener } from '../lib/graphql-error-handler';
import type { GraphQLErrorEvent } from '../lib/graphql-error-handler';

export const Toast: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [severity, setSeverity] = useState<'info' | 'warning' | 'error' | 'success'>('error');

  useEffect(() => {
    const dispose = setupGraphQLErrorListener((err: GraphQLErrorEvent) => {
      setMessage(err.message || 'An error occurred');
      setSeverity('error');
      setOpen(true);
    });

    return dispose;
  }, []);

  return (
    <Snackbar open={open} autoHideDuration={6000} onClose={() => setOpen(false)}>
      <Alert onClose={() => setOpen(false)} severity={severity} sx={{ width: '100%' }}>
        {message}
      </Alert>
    </Snackbar>
  );
};
