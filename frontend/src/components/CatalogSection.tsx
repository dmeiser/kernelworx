import React from 'react';
import {
  Box,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material';
import type { Catalog } from '../types';

interface CatalogSectionProps {
  catalogId: string;
  onCatalogChange: (value: string) => void;
  catalogsLoading: boolean;
  filteredPublicCatalogs: Catalog[];
  myCatalogs: Catalog[];
  label?: string;
  required?: boolean;
}

export const CatalogSection: React.FC<CatalogSectionProps> = ({
  catalogId,
  onCatalogChange,
  catalogsLoading,
  filteredPublicCatalogs,
  myCatalogs,
  label = 'Product Catalog',
  required = true,
}) => {
  const handleChange = (e: SelectChangeEvent<string>) => onCatalogChange(e.target.value);
  const noCatalogs = !catalogsLoading && filteredPublicCatalogs.length === 0 && myCatalogs.length === 0;

  // Combine for renderValue lookup
  const allCatalogs = [...filteredPublicCatalogs, ...myCatalogs];

  // Force removal of aria-hidden if it gets stuck (extra safety)
  const handleOpen = () => {
    const root = document.getElementById('root');
    if (root && root.getAttribute('aria-hidden') === 'true') {
      root.removeAttribute('aria-hidden');
    }
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        {label}
      </Typography>
      <FormControl fullWidth required={required} disabled={catalogsLoading}>
        <InputLabel id="catalog-section-label">Select Catalog</InputLabel>
        <Select
          labelId="catalog-section-label"
          value={catalogId}
          onChange={handleChange}
          onOpen={handleOpen}
          label="Select Catalog"
          renderValue={(value) => {
            if (!value) return '';
            const catalog = allCatalogs.find((c) => c.catalogId === value);
            return catalog ? catalog.catalogName : '';
          }}
          MenuProps={{
            slotProps: {
              paper: {
                sx: { maxHeight: 300 },
              },
            },
          }}
        >
          {catalogsLoading && (
            <MenuItem disabled>
              <CircularProgress size={20} sx={{ mr: 1 }} />
              Loading catalogs...
            </MenuItem>
          )}
          {noCatalogs && <MenuItem disabled>No catalogs available</MenuItem>}

          {filteredPublicCatalogs.length > 0 && (
            <MenuItem disabled sx={{ fontWeight: 'bold', py: 1, opacity: 1, bgcolor: 'action.hover' }}>
              Public Catalogs
            </MenuItem>
          )}
          {filteredPublicCatalogs.map((catalog) => (
            <MenuItem key={`public-${catalog.catalogId}`} value={catalog.catalogId} sx={{ pl: 4 }}>
              {catalog.catalogName}
            </MenuItem>
          ))}

          {myCatalogs.length > 0 && (
            <MenuItem disabled sx={{ fontWeight: 'bold', py: 1, opacity: 1, bgcolor: 'action.hover' }}>
              My Catalogs
            </MenuItem>
          )}
          {myCatalogs.map((catalog) => (
            <MenuItem key={`my-${catalog.catalogId}`} value={catalog.catalogId} sx={{ pl: 4 }}>
              {catalog.catalogName}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
};
