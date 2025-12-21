/**
 * CatalogEditorDialog - Create or edit a product catalog
 */

import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  FormControlLabel,
  Checkbox,
  Stack,
  IconButton,
  Typography,
  Divider,
  Alert,
} from "@mui/material";
import { Add as AddIcon, Delete as DeleteIcon } from "@mui/icons-material";

interface Product {
  productName: string;
  description?: string;
  price: number;
}

interface Catalog {
  catalogId?: string;
  catalogName: string;
  isPublic: boolean;
  products: Product[];
  isDeleted?: boolean;
}

interface CatalogEditorDialogProps {
  open: boolean;
  onClose: () => void;
  onSave: (catalog: Omit<Catalog, "catalogId">) => Promise<void>;
  initialCatalog?: Catalog | null;
}

export const CatalogEditorDialog: React.FC<CatalogEditorDialogProps> = ({
  open,
  onClose,
  onSave,
  initialCatalog,
}) => {
  const [catalogName, setCatalogName] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      if (initialCatalog) {
        setCatalogName(initialCatalog.catalogName);
        setIsPublic(initialCatalog.isPublic);
        setProducts([...initialCatalog.products]);
      } else {
        // New catalog
        setCatalogName("");
        setIsPublic(false);
        setProducts([{ productName: "", description: "", price: 0 }]);
      }
      setError(null);
    }
  }, [open, initialCatalog]);

  const handleAddProduct = () => {
    setProducts([...products, { productName: "", description: "", price: 0 }]);
  };

  const handleRemoveProduct = (index: number) => {
    if (products.length > 1) {
      setProducts(products.filter((_, i) => i !== index));
    }
  };

  const handleProductChange = (
    index: number,
    field: keyof Product,
    value: string | number,
  ) => {
    const updated = [...products];
    updated[index] = { ...updated[index], [field]: value };
    setProducts(updated);
  };

  const handleSave = async () => {
    setError(null);

    // Validation
    if (!catalogName.trim()) {
      setError("Catalog name is required");
      return;
    }

    if (products.length === 0) {
      setError("At least one product is required");
      return;
    }

    for (let i = 0; i < products.length; i++) {
      if (!products[i].productName.trim()) {
        setError(`Product ${i + 1} name is required`);
        return;
      }
      if (products[i].price <= 0) {
        setError(`Product ${i + 1} price must be greater than 0`);
        return;
      }
    }

    setSaving(true);
    try {
      await onSave({
        catalogName: catalogName.trim(),
        isPublic,
        products: products.map((p, index) => ({
          productName: p.productName.trim(),
          description: p.description?.trim() || undefined,
          price: p.price,
          sortOrder: index,
        })),
      });
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to save catalog";
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
      <DialogTitle>
        {initialCatalog ? "Edit Catalog" : "Create Catalog"}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          {/* Catalog Name */}
          <TextField
            label="Catalog Name"
            value={catalogName}
            onChange={(e) => setCatalogName(e.target.value)}
            fullWidth
            required
            placeholder="e.g., 2025 Popcorn Catalog"
          />

          {/* Public Checkbox */}
          <FormControlLabel
            control={
              <Checkbox
                checked={isPublic}
                onChange={(e) => setIsPublic(e.target.checked)}
              />
            }
            label="Make this catalog public (visible to all users)"
          />

          <Divider />

          {/* Products */}
          <Box>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              mb={2}
            >
              <Typography variant="h6">Products</Typography>
              <Button
                startIcon={<AddIcon />}
                onClick={handleAddProduct}
                size="small"
                variant="outlined"
              >
                Add Product
              </Button>
            </Stack>

            <Stack spacing={2}>
              {products.map((product, index) => (
                <Box
                  key={index}
                  sx={{
                    p: 2,
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 1,
                  }}
                >
                  <Stack spacing={2}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                    >
                      <Typography variant="subtitle2" color="text.secondary">
                        Product {index + 1}
                      </Typography>
                      {products.length > 1 && (
                        <IconButton
                          size="small"
                          onClick={() => handleRemoveProduct(index)}
                          color="error"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      )}
                    </Stack>

                    <TextField
                      label="Product Name"
                      value={product.productName}
                      onChange={(e) =>
                        handleProductChange(
                          index,
                          "productName",
                          e.target.value,
                        )
                      }
                      fullWidth
                      required
                      size="small"
                      placeholder="e.g., Caramel Popcorn"
                    />

                    <TextField
                      label="Description (optional)"
                      value={product.description || ""}
                      onChange={(e) =>
                        handleProductChange(
                          index,
                          "description",
                          e.target.value,
                        )
                      }
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
                      onChange={(e) =>
                        handleProductChange(
                          index,
                          "price",
                          parseFloat(e.target.value) || 0,
                        )
                      }
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

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleCancel} disabled={saving}>
          Cancel
        </Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}>
          {saving ? "Saving..." : "Save Catalog"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
