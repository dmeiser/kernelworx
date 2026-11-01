/**
 * Product picker for the public order page.
 *
 * The offer carries the anchor catalog's products in catalog order, unpaginated
 * (v1). Prices shown here are display only — the server re-reads the catalog and
 * prices the order itself, so a stale price on screen cannot set the total.
 *
 * A buyer types quantities one keystroke at a time, and every keystroke changes
 * the hook's `lineItems` object, so the list re-renders constantly. Each row is
 * therefore memoized on the primitives it actually depends on (its own product
 * and its own quantity), which keeps a keystroke in one box from re-rendering
 * the whole catalog.
 */

import { memo } from 'react';
import { Alert, Box, Stack, TextField, Typography } from '@mui/material';
import { formatCurrency } from '../../lib/api-utils';
import { MAX_PUBLIC_QUANTITY } from '../../lib/publicOrderValidation';
import type { PublicProductView } from './publicOrderTypes';

interface ProductRowProps {
  product: PublicProductView;
  quantity: number;
  onQuantityChange: (productId: string, quantity: number) => void;
}

const ProductRow = memo<ProductRowProps>(({ product, quantity, onQuantityChange }) => (
  <Stack direction="row" spacing={2} alignItems="center" data-testid={`product-row-${product.productId}`}>
    <Box sx={{ flexGrow: 1, minWidth: 0 }}>
      <Typography variant="body2" fontWeight="medium">
        {product.productName}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {formatCurrency(product.price)}
      </Typography>
      {product.description ? (
        <Typography variant="body2" color="text.secondary">
          {product.description}
        </Typography>
      ) : null}
    </Box>
    <TextField
      type="number"
      size="small"
      inputProps={{ min: 0, max: MAX_PUBLIC_QUANTITY, 'aria-label': `Quantity for ${product.productName}` }}
      value={quantity}
      onChange={(event) => onQuantityChange(product.productId, Number.parseInt(event.target.value, 10) || 0)}
      sx={{ width: 90 }}
    />
  </Stack>
));

ProductRow.displayName = 'ProductRow';

interface ProductPickerProps {
  products: PublicProductView[];
  quantities: Record<string, number>;
  onQuantityChange: (productId: string, quantity: number) => void;
  errorText?: string;
}

export const ProductPicker = memo<ProductPickerProps>(
  ({ products, quantities, onQuantityChange, errorText }) => (
    <Box>
      <Typography variant="subtitle1" fontWeight="medium" gutterBottom>
        Products
      </Typography>
      {products.length === 0 ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          This seller has no products listed right now.
        </Alert>
      ) : (
        <Stack spacing={1.5} sx={{ mb: 1 }}>
          {products.map((product) => (
            <ProductRow
              key={product.productId}
              product={product}
              quantity={quantities[product.productId] ?? 0}
              onQuantityChange={onQuantityChange}
            />
          ))}
        </Stack>
      )}
      {errorText ? (
        <Typography variant="body2" color="error">
          {errorText}
        </Typography>
      ) : null}
    </Box>
  ),
);

ProductPicker.displayName = 'ProductPicker';

export default ProductPicker;
