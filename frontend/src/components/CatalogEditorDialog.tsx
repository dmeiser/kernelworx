/**
 * CatalogEditorDialog - Create or edit a product catalog
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Stack,
  IconButton,
  Typography,
  Divider,
  Alert,
  AlertTitle,
} from '@mui/material';
import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import type { ProductInput, Catalog, Product } from '../types';
import { useFormState } from '../hooks/useFormState';

// Local Catalog type for editing (products may not have IDs yet)
interface CatalogInput {
  catalogId?: string;
  catalogName: string;
  isPublic: boolean;
  products: ProductInput[];
  isDeleted?: boolean;
}

interface CatalogEditorDialogProps {
  open: boolean;
  onClose: () => void;
  onSave: (catalog: Omit<CatalogInput, 'catalogId'>) => Promise<void>;
  initialCatalog?: Catalog | null;
}

interface CatalogFormValues {
  catalogName: string;
  isPublic: boolean;
}

export const CatalogEditorDialog: React.FC<CatalogEditorDialogProps> = ({ open, onClose, onSave, initialCatalog }) => {
  const form = useFormState<CatalogFormValues>({
    initialValues: { catalogName: '', isPublic: false },
  });
  const [products, setProducts] = useState<ProductInput[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initializedRef = useRef(false);

  const resetForm = useCallback(() => {
    form.resetTo({ catalogName: '', isPublic: false });
    setProducts([{ productName: '', description: '', price: 0 }]);
    setError(null);
  }, [form]);

  const initFromCatalog = useCallback(
    (catalog: Catalog) => {
      form.resetTo({ catalogName: catalog.catalogName, isPublic: catalog.isPublic ?? false });
      setProducts([...(catalog.products ?? [])]);
      setError(null);
    },
    [form],
  );

  useEffect(() => {
    if (open && !initializedRef.current) {
      initializedRef.current = true;
      if (initialCatalog) {
        initFromCatalog(initialCatalog);
      } else {
        resetForm();
      }
    } else if (!open) {
      initializedRef.current = false;
    }
  }, [open, initialCatalog, initFromCatalog, resetForm]);

  const handleAddProduct = () => {
    setProducts([...products, { productName: '', description: '', price: 0 }]);
  };

  const handleRemoveProduct = (index: number) => {
    if (products.length > 1) {
      setProducts(products.filter((_, i) => i !== index));
    }
  };

  const handleProductChange = (index: number, field: keyof Product, value: string | number) => {
    const updated = [...products];
    updated[index] = { ...updated[index], [field]: value };
    setProducts(updated);
  };

  const validateProducts = (): string | null => {
    if (products.length === 0) {
      return 'At least one product is required';
    }
    for (let i = 0; i < products.length; i++) {
      if (!products[i].productName.trim()) {
        return `Product ${i + 1} name is required`;
      }
      if (products[i].price <= 0) {
        return `Product ${i + 1} price must be greater than 0`;
      }
    }
    return null;
  };

  const validate = (): string | null => {
    if (!form.values.catalogName.trim()) return 'Catalog name is required';
    return validateProducts();
  };

  const buildCatalogPayload = () => ({
    catalogName: form.values.catalogName.trim(),
    isPublic: form.values.isPublic,
    products: products.map((p, index) => ({
      productName: p.productName.trim(),
      description: p.description?.trim() || undefined,
      price: p.price,
      sortOrder: index,
    })),
  });

  const handleSave = async () => {
    setError(null);

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    try {
      await onSave(buildCatalogPayload());
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save catalog';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{initialCatalog ? 'Edit Catalog' : 'Create Catalog'}</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          {/* Catalog Name */}
          <TextField
            label="Catalog Name"
            value={form.values.catalogName}
            onChange={(e) => form.setValue('catalogName', e.target.value)}
            fullWidth
            required
            placeholder="e.g., 2025 Popcorn Catalog"
          />

          <Divider />

          {/* Products */}
          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="h6">Products</Typography>
              <Button startIcon={<AddIcon />} onClick={handleAddProduct} size="small" variant="outlined">
                Add Product
              </Button>
            </Stack>

            <Stack spacing={2}>
              {products.map((product, index) => (
                <Box
                  key={index}
                  sx={{
                    p: 2,
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                  }}
                >
                  <Stack spacing={2}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Typography variant="subtitle2" color="text.secondary">
                        Product {index + 1}
                      </Typography>
                      {products.length > 1 && (
                        <IconButton size="small" onClick={() => handleRemoveProduct(index)} color="error">
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      )}
                    </Stack>

                    <TextField
                      label="Product Name"
                      value={product.productName}
                      onChange={(e) => handleProductChange(index, 'productName', e.target.value)}
                      fullWidth
                      required
                      size="small"
                      placeholder="e.g., Caramel Popcorn"
                    />

                    <TextField
                      label="Description (optional)"
                      value={product.description || ''}
                      onChange={(e) => handleProductChange(index, 'description', e.target.value)}
                      fullWidth
                      size="small"
                      multiline
                      rows={2}
                      placeholder="Brief description of the product"
                    />

                    <TextField
                      label="Price"
                      type="number"
                      value={product.price}
                      onChange={(e) => handleProductChange(index, 'price', parseFloat(e.target.value) || 0)}
                      fullWidth
                      required
                      size="small"
                      inputProps={{ min: 0, step: 0.01 }}
                    />
                  </Stack>
                </Box>
              ))}
            </Stack>
          </Box>

          {/* Privacy Notice */}
          <Alert severity="info">
            <AlertTitle>Privacy Notice</AlertTitle>
            Catalogs are not searchable, but anyone with the catalog ID can view products and prices. When you use
            this catalog in a shared campaign, campaign participants will see it.
          </Alert>

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleCancel} disabled={saving}>
          Cancel
        </Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}>
          {saving ? 'Saving...' : 'Save Catalog'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
