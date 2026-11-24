/**
 * The line rows a sale is built from — the create form and the correction form
 * both use them (Show & Sell §4.5.1, on the §7.1 line contract).
 *
 * A line is one product with two quantities: what the buyer takes at the table and
 * what the Unit owes them later. Those are the only two numbers the API accepts per
 * line — price, name and subtotal are read by the server from the campaign's catalog,
 * so a screen that let an admin type a price would offer a number the write ignores
 * (§7.1). Mixed lines are the normal case: one sale can carry several products and
 * split each of them between the two quantities.
 *
 * In a correction these rows carry one more thing: the stable `lineItemId` of the
 * line they came from. That id is what makes "change this line" and "drop this line"
 * different acts — a removed row is a line the correction leaves out, which the
 * server reads as a voided line.
 */

import React from 'react';
import {
  Button,
  IconButton,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GqlGetUnitCampaignCatalogQuery, GqlShowAndSellSaleFieldsFragment } from '../../types/graphql-generated';

export type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];

/** One row as the editor holds it: the id it corrects, and the two typed quantities. */
export interface LineRowDraft {
  /** Set for a row that replaces an existing line; null for a new or supplemental line. */
  lineItemId: string | null;
  productId: string;
  immediateQty: string;
  weOweQty: string;
}

/** A blank row, for the line the admin has not chosen a product for yet. */
export const emptyLineRow = (): LineRowDraft => ({ lineItemId: null, productId: '', immediateQty: '', weOweQty: '' });

/** The sale's own lines, in the shape the correction editor edits. */
export function linesOf(sale: GqlShowAndSellSaleFieldsFragment): LineRowDraft[] {
  return sale.lineItems.map((line) => ({
    lineItemId: line.lineItemId,
    productId: line.productId,
    immediateQty: String(line.immediateQty),
    weOweQty: String(line.weOweQty),
  }));
}

/**
 * The products a picker offers: the catalog's, plus any product already on the sale
 * that the catalog no longer lists. A product the admin cannot select is a line they
 * cannot keep, and a correction that silently drops it cancels an obligation nobody
 * decided to cancel.
 */
export function lineProductOptions(
  products: readonly CatalogProduct[],
  rows: readonly LineRowDraft[],
): { productId: string; productName: string }[] {
  const options = products.map((product) => ({ productId: product.productId, productName: product.productName }));
  for (const row of rows) {
    if (row.productId !== '' && !options.some((option) => option.productId === row.productId)) {
      options.push({ productId: row.productId, productName: row.productId });
    }
  }
  return options;
}

export const SaleLineTable: React.FC<{
  rows: readonly LineRowDraft[];
  products: readonly CatalogProduct[];
  idPrefix: string;
  weOweAllowed: boolean;
  disabled: boolean;
  onRow: (index: number, patch: Partial<LineRowDraft>) => void;
  onRemove: (index: number) => void;
  onAdd: () => void;
}> = ({ rows, products, idPrefix, weOweAllowed, disabled, onRow, onRemove, onAdd }) => {
  const options = lineProductOptions(products, rows);
  return (
    <>
      <Table size="small" aria-label="Sale lines">
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell>Taken at the table</TableCell>
            <TableCell>Owed later</TableCell>
            <TableCell aria-label="Remove line" />
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, index) => (
            <SaleLineRow
              key={row.lineItemId ?? `new-${index}`}
              row={row}
              index={index}
              options={options}
              idPrefix={idPrefix}
              weOweAllowed={weOweAllowed}
              disabled={disabled}
              onRow={onRow}
              onRemove={onRemove}
            />
          ))}
        </TableBody>
      </Table>
      <Button size="small" onClick={onAdd} disabled={disabled} data-testid={`${idPrefix}-add-line`} sx={{ mt: 1 }}>
        Add another line
      </Button>
    </>
  );
};

const SaleLineRow: React.FC<{
  row: LineRowDraft;
  index: number;
  options: readonly { productId: string; productName: string }[];
  idPrefix: string;
  weOweAllowed: boolean;
  disabled: boolean;
  onRow: (index: number, patch: Partial<LineRowDraft>) => void;
  onRemove: (index: number) => void;
}> = ({ row, index, options, idPrefix, weOweAllowed, disabled, onRow, onRemove }) => (
  <TableRow data-testid={`${idPrefix}-line-${index}`}>
    <TableCell>
      <Select
        size="small"
        value={row.productId}
        onChange={(change) => onRow(index, { productId: change.target.value })}
        disabled={disabled}
        displayEmpty
        data-testid={`${idPrefix}-product-${index}`}
        inputProps={{ 'aria-label': `Product for sale line ${index + 1}` }}
      >
        <MenuItem value="">Choose a product</MenuItem>
        {options.map((option) => (
          <MenuItem key={option.productId} value={option.productId}>
            {option.productName}
          </MenuItem>
        ))}
      </Select>
    </TableCell>
    <TableCell>
      <TextField
        size="small"
        inputMode="numeric"
        value={row.immediateQty}
        onChange={(change) => onRow(index, { immediateQty: change.target.value })}
        disabled={disabled}
        inputProps={{
          'aria-label': `Kernels taken at the table on line ${index + 1}`,
          'data-testid': `${idPrefix}-immediate-${index}`,
        }}
        sx={{ width: 110 }}
      />
    </TableCell>
    <TableCell>
      <TextField
        size="small"
        inputMode="numeric"
        value={row.weOweQty}
        onChange={(change) => onRow(index, { weOweQty: change.target.value })}
        disabled={disabled || !weOweAllowed}
        inputProps={{
          'aria-label': `Kernels owed later on line ${index + 1}`,
          'data-testid': `${idPrefix}-weowe-${index}`,
        }}
        sx={{ width: 110 }}
      />
    </TableCell>
    <TableCell>
      <IconButton
        size="small"
        onClick={() => onRemove(index)}
        disabled={disabled}
        aria-label={`Remove line ${index + 1}`}
        data-testid={`${idPrefix}-remove-line-${index}`}
      >
        <DeleteIcon fontSize="small" />
      </IconButton>
      {row.lineItemId === null ? null : (
        <Typography variant="caption" data-testid={`${idPrefix}-correcting-${index}`}>
          Correcting this line
        </Typography>
      )}
    </TableCell>
  </TableRow>
);
