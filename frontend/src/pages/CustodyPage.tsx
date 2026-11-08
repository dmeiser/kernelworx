import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import {
  Box,
  TextField,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Alert,
  Typography,
} from '@mui/material';

export const CustodyPage: React.FC = () => {
  const [scout, setScout] = useState('');
  const [product, setProduct] = useState('');
  const [qty, setQty] = useState('');
  const [balances, setBalances] = useState<Record<string, number>>({});
  const [error, setError] = useState('');

  const issue = () => {
    const n = Number(qty);
    if (!scout || !product || !Number.isInteger(n) || n <= 0) {
      setError('invalid selection or quantity');
      return;
    }
    setError('');
    const key = `${scout}:${product}`;
    setBalances((b) => ({ ...b, [key]: (b[key] || 0) + n }));
  };

  const returnOne = () => {
    const key = `${scout}:${product}`;
    const cur = balances[key] || 0;
    if (cur <= 0) {
      setError('nothing to return');
      return;
    }
    setError('');
    setBalances((b) => ({ ...b, [key]: cur - 1 }));
  };

  const aggregate = Object.values(balances).reduce((a, b) => a + b, 0);

  return (
    <Box>
      <PageHeader title="Custody" />
      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: 'flex', gap: 2, my: 2 }}>
        <TextField label="Scout" value={scout} onChange={(e) => setScout(e.target.value)} />
        <TextField label="Product" value={product} onChange={(e) => setProduct(e.target.value)} />
        <TextField label="Qty" value={qty} onChange={(e) => setQty(e.target.value)} />
        <Button onClick={issue}>Issue</Button>
        <Button onClick={returnOne}>One-click return</Button>
      </Box>
      <Typography>Aggregate balance: {aggregate}</Typography>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Scout:Product</TableCell>
            <TableCell>Balance</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {Object.entries(balances).map(([k, v]) => (
            <TableRow key={k}>
              <TableCell>{k}</TableCell>
              <TableCell>{v}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
};
export default CustodyPage;
