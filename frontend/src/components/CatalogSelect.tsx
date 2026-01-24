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

/**
 * Renders a catalog item as a MenuItem
 */
const CatalogMenuItem: React.FC<{ catalog: Catalog; keyPrefix: string }> = ({ catalog, keyPrefix }) => (
  <MenuItem key={`${keyPrefix}-${catalog.catalogId}`} value={catalog.catalogId}>
    {catalog.catalogName}
    {catalog.catalogType === 'ADMIN_MANAGED' && ' (Official)'}
  </MenuItem>
);

/**
 * Renders a group header MenuItem
 */
const GroupHeader: React.FC<{ label: string; keyValue: string }> = ({ label, keyValue }) => (
  <MenuItem key={keyValue} disabled sx={{ fontWeight: 600, backgroundColor: '#f5f5f5', opacity: 1 }}>
    {label}
  </MenuItem>
);

/**
 * Builds menu items for the catalog select dropdown
 */
function buildCatalogMenuItems(
  loading: boolean,
  hasNoCatalogs: boolean,
  myCatalogs: Catalog[],
  publicCatalogs: Catalog[],
): React.ReactNode[] {
  if (loading) {
    return [
      <MenuItem key="loading" disabled>
        <CircularProgress size={20} sx={{ mr: 1 }} />
        Loading catalogs...
      </MenuItem>,
    ];
  }

  if (hasNoCatalogs) {
    return [
      <MenuItem key="empty" disabled>
        No catalogs available
      </MenuItem>,
    ];
  }

  const items: React.ReactNode[] = [];

  if (myCatalogs.length > 0) {
    items.push(<GroupHeader key="my-header" label="My Catalogs" keyValue="my-header" />);
    myCatalogs.forEach((catalog) => {
      items.push(<CatalogMenuItem key={`my-${catalog.catalogId}`} catalog={catalog} keyPrefix="my" />);
    });
  }

  if (publicCatalogs.length > 0) {
    items.push(<GroupHeader key="public-header" label="Public Catalogs" keyValue="public-header" />);
    publicCatalogs.forEach((catalog) => {
      items.push(<CatalogMenuItem key={`public-${catalog.catalogId}`} catalog={catalog} keyPrefix="public" />);
    });
  }

  return items;
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
  // eslint-disable-next-line complexity -- Many optional props with defaults inflate complexity count
}) => {
  const selectId = useId();
  const hasNoCatalogs = !loading && myCatalogs.length === 0 && publicCatalogs.length === 0;
  // CRITICAL: Don't disable during loading - MUI Select has issues with toggling disabled state during interaction
  const selectDisabled = disabled && !loading;
  const labelText = required ? `${label} *` : label;

  // Memoize the menu items to prevent re-renders from causing selection issues
  const menuItems = useMemo(
    () => buildCatalogMenuItems(loading, hasNoCatalogs, myCatalogs, publicCatalogs),
    [loading, hasNoCatalogs, myCatalogs, publicCatalogs],
  );

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
