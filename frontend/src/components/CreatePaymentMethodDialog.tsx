/**
 * CreatePaymentMethodDialog - Dialog for creating a new custom payment method
 *
 * Thin wrapper over the shared PaymentMethodDialog (mode="create").
 *
 * Features:
 * - Name input with validation
 * - Reserved name checking (cash, check)
 * - Duplicate name prevention
 * - Loading state during creation
 */

import React from 'react';
import { PaymentMethodDialog } from './PaymentMethodDialog';

interface CreatePaymentMethodDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
  existingNames: string[];
  isLoading?: boolean;
}

export const CreatePaymentMethodDialog: React.FC<CreatePaymentMethodDialogProps> = ({
  open,
  onClose,
  onCreate,
  existingNames,
  isLoading = false,
}) => (
  <PaymentMethodDialog
    mode="create"
    open={open}
    onClose={onClose}
    onSubmit={onCreate}
    existingNames={existingNames}
    isLoading={isLoading}
  />
);
