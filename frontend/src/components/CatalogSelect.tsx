/**
 * CatalogSelect - Shared catalog selection component with grouped options
 * Used by campaign creation forms to display public and user catalogs
 */

import React, { useMemo, useId } from 'react';
import { FormControl, InputLabel, Select, MenuItem, CircularProgress } from '@mui/material';
import type { Catalog } from '../types';

interface CatalogSelectProps {
  value: string;
  onChange: (value: string) => void;
  myCatalogs: Catalog[];
  publicCatalogs: Catalog[];
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  required?: boolean;
  label?: string;
  maxMenuHeight?: number;
}

export const CatalogSelect: React.FC<CatalogSelectProps> = ({
  value,
  onChange,
  myCatalogs,
  publicCatalogs,
  loading = false,
  disabled = false,
  fullWidth = true,
  required = false,
  label = 'Product Catalog',
  maxMenuHeight = 300,
}) => {
  const selectId = useId();
  const hasNoCatalogs = !loading && myCatalogs.length === 0 && publicCatalogs.length === 0;
  // CRITICAL: Don't disable during loading - MUI Select has issues with toggling disabled state during interaction
  const selectDisabled = disabled && !loading;
  const labelText = required ? `${label} *` : label;

  // Memoize the menu items to prevent re-renders from causing selection issues
  const menuItems = useMemo(() => {
    const items: React.ReactNode[] = [];

    if (loading) {
      items.push(
        <MenuItem key="loading" disabled>
          <CircularProgress size={20} sx={{ mr: 1 }} />
          Loading catalogs...
        </MenuItem>
      );
    } else if (hasNoCatalogs) {
      items.push(
        <MenuItem key="empty" disabled>
          No catalogs available
        </MenuItem>
      );
    } else {
      // My Catalogs group
      if (myCatalogs.length > 0) {
        items.push(
          <MenuItem key="my-header" disabled sx={{ fontWeight: 600, backgroundColor: '#f5f5f5', opacity: 1 }}>
            My Catalogs
          </MenuItem>
        );
        myCatalogs.forEach((catalog) => {
          items.push(
            <MenuItem key={`my-${catalog.catalogId}`} value={catalog.catalogId}>
              {catalog.catalogName}
              {catalog.catalogType === 'ADMIN_MANAGED' && ' (Official)'}
            </MenuItem>
          );
        });
      }

      // Public Catalogs group
      if (publicCatalogs.length > 0) {
        items.push(
          <MenuItem key="public-header" disabled sx={{ fontWeight: 600, backgroundColor: '#f5f5f5', opacity: 1 }}>
            Public Catalogs
          </MenuItem>
        );
        publicCatalogs.forEach((catalog) => {
          items.push(
            <MenuItem key={`public-${catalog.catalogId}`} value={catalog.catalogId}>
              {catalog.catalogName}
              {catalog.catalogType === 'ADMIN_MANAGED' && ' (Official)'}
            </MenuItem>
          );
        });
      }
    }

    return items;
  }, [loading, hasNoCatalogs, myCatalogs, publicCatalogs]);

  return (
    <FormControl fullWidth={fullWidth}>
      <InputLabel htmlFor={selectId}>{labelText}</InputLabel>
      <Select
        id={selectId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        label={labelText}
        disabled={selectDisabled}
        MenuProps={{
          slotProps: {
            paper: {
              sx: { maxHeight: maxMenuHeight },
            },
          },
        }}
      >
        {menuItems}
      </Select>
    </FormControl>
  );
};
