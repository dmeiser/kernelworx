import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, TextField, Button, Table, TableBody, TableCell, TableHead, TableRow, Alert, Typography } from '@mui/material';

interface Movement { id: string; type: string; qty: number; reason: string; }

export const InventoryPage: React.FC = () => {
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [movements, setMovements] = useState<Movement[]>([]);
  const [balance, setBalance] = useState(0);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');

  const submit = (type: string) => {
    const n = Number(qty);
    if (!Number.isInteger(n) || n <= 0) { setError('quantity must be a positive integer'); return; }
    if (!reason.trim()) { setError('reason is required'); return; }
    setError('');
    const m: Movement = { id: `m-${movements.length + 1}`, type, qty: n, reason };
    setMovements((prev) => [m, ...prev]);
    setBalance((b) => (type === 'receipt' ? b + n : type === 'adjustment' ? b + n : b));
    setQty(''); setReason('');
  };

  const filtered = filter ? movements.filter((m) => m.type === filter) : movements;

  return (
    <Box>
      <PageHeader title="Inventory" />
      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: 'flex', gap: 2, my: 2 }}>
        <TextField label="Quantity" value={qty} onChange={(e) => setQty(e.target.value)} inputProps={{ inputMode: 'numeric' }} />
        <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button onClick={() => submit('receipt')}>Receipt</Button>
        <Button onClick={() => submit('adjustment')}>Adjustment</Button>
        <Button onClick={() => submit('on-order')}>On Order</Button>
      </Box>
      <Typography>Balance: {balance}</Typography>
      <TextField label="Filter movement type" value={filter} onChange={(e) => setFilter(e.target.value)} sx={{ my: 2 }} />
      <Table>
        <TableHead><TableRow><TableCell>Type</TableCell><TableCell>Qty</TableCell><TableCell>Reason</TableCell></TableRow></TableHead>
        <TableBody>
          {filtered.map((m) => (
            <TableRow key={m.id}><TableCell>{m.type}</TableCell><TableCell>{m.qty}</TableCell><TableCell>{m.reason}</TableCell></TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
};
export default InventoryPage;
