import React from 'react';
import { PageHeader } from '../components/PageHeader';
import { LoadingState } from '../components/LoadingState';

export const InventoryPage: React.FC = () => {
  return (
    <div>
      <PageHeader title="Inventory" />
      <LoadingState />
    </div>
  );
};

export default InventoryPage;
