/**
 * Order status chip for the buyer receipt view.
 *
 * Public orders are created NEW and stay NEW until the seller records that
 * payment arrived off-platform; there is no path back from CONFIRMED in v1, so
 * the copy describes a state the seller set, not a payment KernelWorx verified.
 */

import { Chip } from '@mui/material';
import type { GqlOrderStatus } from '../../types/graphql-generated';
import { getOrderStatusPresentation } from '../../lib/orderStatus';

export const ReceiptStatusChip: React.FC<{ status: GqlOrderStatus }> = ({ status }) => {
  const presentation = getOrderStatusPresentation(status, 'receipt');
  return (
    <Chip
      size="small"
      color={presentation.color}
      label={presentation.label ?? status}
      data-testid="receipt-status-chip"
    />
  );
};

export default ReceiptStatusChip;