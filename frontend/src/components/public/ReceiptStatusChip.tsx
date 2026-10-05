/**
 * Order status chip for the buyer receipt view.
 *
 * Public orders are created NEW and stay NEW until the seller records that
 * payment arrived off-platform; there is no path back from CONFIRMED in v1, so
 * the copy describes a state the seller set, not a payment KernelWorx verified.
 */

import { Chip } from '@mui/material';
import type { GqlOrderStatus } from '../../types/graphql-generated';

const STATUS_LABELS: Record<GqlOrderStatus, string> = {
  NEW: 'Awaiting payment confirmation',
  CONFIRMED: 'Payment confirmed',
};

export const ReceiptStatusChip: React.FC<{ status: GqlOrderStatus }> = ({ status }) => (
  <Chip
    size="small"
    color={status === 'CONFIRMED' ? 'success' : 'warning'}
    label={STATUS_LABELS[status] ?? status}
    data-testid="receipt-status-chip"
  />
);

export default ReceiptStatusChip;
