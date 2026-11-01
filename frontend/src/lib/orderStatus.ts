/**
 * Shared presentation logic for order lifecycle status chips.
 *
 * OrdersPage and ReceiptStatusChip both render a chip for the seller-set order
 * status (NEW vs CONFIRMED); keep the color/label mapping here so the two
 * views cannot drift.
 */

export interface OrderStatusPresentation {
  color: 'warning' | 'success';
  label: string;
}

export type OrderStatusChipVariant = 'table' | 'receipt';

export const getOrderStatusPresentation = (
  status: string,
  variant: OrderStatusChipVariant = 'table',
): OrderStatusPresentation => {
  if (status === 'CONFIRMED') {
    return { color: 'success', label: 'Payment confirmed' };
  }
  return {
    color: 'warning',
    label: variant === 'receipt' ? 'Awaiting payment confirmation' : 'New',
  };
};

export default getOrderStatusPresentation;
