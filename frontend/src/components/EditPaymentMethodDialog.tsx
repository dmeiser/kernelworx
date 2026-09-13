/**
 * EditPaymentMethodDialog - Dialog for renaming an existing custom payment method
 *
 * Thin wrapper over the shared PaymentMethodDialog (mode="edit").
 *
 * Features:
 * - Pre-filled name input
 * - Validation against reserved and existing names
 * - Loading state during update
 */

import React from 'react';
import { PaymentMethodDialog } from './PaymentMethodDialog';

interface EditPaymentMethodDialogProps {
  open: boolean;
  onClose: () => void;
  onUpdate: (oldName: string, newName: string) => Promise<void>;
  currentName: string;
  existingNames: string[];
  isLoading?: boolean;
}

export const EditPaymentMethodDialog: React.FC<EditPaymentMethodDialogProps> = ({
  open,
  onClose,
  onUpdate,
  currentName,
  existingNames,
  isLoading = false,
}) => (
  <PaymentMethodDialog
    mode="edit"
    open={open}
    onClose={onClose}
    onSubmit={(newName) => onUpdate(currentName, newName)}
    existingNames={existingNames}
    currentName={currentName}
    isLoading={isLoading}
  />
);
