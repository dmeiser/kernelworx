/**
 * The catalog a Unit Campaign sells from, read-only (Show & Sell §1.6.3).
 *
 * Products appear in the catalog's own display order — the order the admin arranged
 * is the order a Scout sees at the table, so re-sorting it here would make the
 * printed sheet and the screen disagree.
 *
 * There is no editing affordance in this table on purpose. The campaign's catalog is
 * chosen once, and inventory, Order origin, and event product identity all key on it;
 * a control that looked editable would promise a re-pointing of history that the
 * backend refuses.
 */

import React from 'react';
import { Card, Table, TableBody, TableCell, TableHead, TableRow, Box, Typography } from '@mui/material';
import type { GqlProduct, GqlUnitCampaignCatalog } from '../types/graphql-generated';

const formatPrice = (price: number): string => `$${Number(price).toFixed(2)}`;

const CatalogProductRow: React.FC<{ product: GqlProduct }> = ({ product }) => (
  <TableRow data-testid={`catalog-product-${product.productId}`}>
    <TableCell>{product.productName}</TableCell>
    <TableCell>{product.description ?? ''}</TableCell>
    <TableCell align="right">{formatPrice(product.price)}</TableCell>
  </TableRow>
);

export const CampaignCatalogTable: React.FC<{ catalog: GqlUnitCampaignCatalog }> = ({ catalog }) => (
  <Box sx={{ pt: 2 }}>
    <Typography color="text.secondary" sx={{ mb: 1 }} data-testid="catalog-name">
      {catalog.catalogName} · fixed at creation
    </Typography>
    <Card variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell>Description</TableCell>
            <TableCell align="right">Price</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {catalog.products.map((product) => (
            <CatalogProductRow key={product.productId} product={product} />
          ))}
          {catalog.products.length === 0 && (
            <TableRow>
              <TableCell colSpan={3}>
                <Box sx={{ p: 2 }}>
                  <Typography color="text.secondary">This catalog has no products yet.</Typography>
                </Box>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Card>
  </Box>
);
