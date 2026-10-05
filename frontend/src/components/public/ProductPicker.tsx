/**
 * Product picker for the public order page.
 *
 * The offer carries the anchor catalog's products in catalog order, unpaginated
 * (v1). Prices shown here are display only — the server re-reads the catalog and
 * prices the order itself, so a stale price on screen cannot set the total.
 */

import { Box, Stack, TextField, Typography, Alert } from '@mui/material';
import { formatCurrency } from '../../lib/api-utils';
import { MAX_PUBLIC_QUANTITY } from '../../lib/publicOrderValidation';
import type { PublicProductView } from './publicOrderTypes';

interface ProductPickerProps {
  products: PublicProductView[];
  quantities: Record<string, number>;
  onQuantityChange: (productId: string, quantity: number) => void;
  errorText?: string;
}

export const ProductPicker: React.FC<ProductPickerProps> = ({ products, quantities, onQuantityChange, errorText }) => (
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
          <Stack
            key={product.productId}
            direction="row"
            spacing={2}
            alignItems="center"
            data-testid={`product-row-${product.productId}`}
          >
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
              value={quantities[product.productId] ?? 0}
              onChange={(event) => onQuantityChange(product.productId, Number.parseInt(event.target.value, 10) || 0)}
              sx={{ width: 90 }}
            />
          </Stack>
        ))}
      </Stack>
    )}
    {errorText ? (
      <Typography variant="body2" color="error">
        {errorText}
      </Typography>
    ) : null}
  </Box>
);

export default ProductPicker;
