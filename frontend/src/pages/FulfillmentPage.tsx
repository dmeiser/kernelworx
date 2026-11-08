import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, TextField, Button, Table, TableBody, TableCell, TableHead, TableRow } from '@mui/material';

interface Line {
  id: string;
  fulfilled: number;
  unfulfilled: number;
}

export const FulfillmentPage: React.FC = () => {
  const [mode, setMode] = useState('NONE');
  const [lines, setLines] = useState<Line[]>([{ id: 'L1', fulfilled: 0, unfulfilled: 5 }]);
  const [version, setVersion] = useState(1);

  const fulfill = (id: string) => {
    setLines((ls) =>
      ls.map((l) =>
        l.id === id ? { ...l, fulfilled: l.fulfilled + 1, unfulfilled: Math.max(0, l.unfulfilled - 1) } : l,
      ),
    );
  };
  const reverse = (id: string) => {
    setLines((ls) =>
      ls.map((l) =>
        l.id === id ? { ...l, fulfilled: Math.max(0, l.fulfilled - 1), unfulfilled: l.unfulfilled + 1 } : l,
      ),
    );
  };

  return (
    <Box>
      <PageHeader title="Fulfillment" />
      <Box sx={{ my: 2 }}>
        <TextField label="fulfillmentMode" value={mode} onChange={(e) => setMode(e.target.value)} />
        <TextField
          label="version"
          value={version}
          onChange={(e) => setVersion(Number(e.target.value))}
          sx={{ ml: 2 }}
        />
      </Box>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Line</TableCell>
            <TableCell>Fulfilled</TableCell>
            <TableCell>Unfulfilled</TableCell>
            <TableCell>Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {lines.map((l) => (
            <TableRow key={l.id}>
              <TableCell>{l.id}</TableCell>
              <TableCell>{l.fulfilled}</TableCell>
              <TableCell>{l.unfulfilled}</TableCell>
              <TableCell>
                <Button onClick={() => fulfill(l.id)}>Fulfill</Button>
                <Button onClick={() => reverse(l.id)}>Reverse</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
};
export default FulfillmentPage;
