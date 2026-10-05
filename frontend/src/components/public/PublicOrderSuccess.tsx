/**
 * Success screen for a submitted public order.
 *
 * Three things must be honest here: the full order reference (the buyer needs it
 * for support, and it is the only identifier they will be asked for), what was
 * actually submitted, and whether a confirmation email went out — distinguishing
 * "no email was given" from "the send failed" rather than collapsing both into a
 * generic message. The receipt link is rendered only through `resolveReceiptUrl`;
 * a raw order id contains '#', which a browser would truncate at the fragment
 * delimiter, so a link carrying one is never rendered.
 */

import { Alert, Box, Divider, Link, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import { formatCurrency } from '../../lib/api-utils';
import { resolveReceiptUrl } from '../../lib/publicOrders';

export interface PublicOrderReceiptView {
  orderId: string;
  receiptUrl?: string | null;
  totalAmount: number;
  buyerEmailProvided: boolean;
  confirmationEmailSent: boolean;
}

export interface PublicOrderSubmittedSummary {
  firstName: string;
  lastName: string;
  paymentMethod: string;
  phone?: string;
  email?: string;
  lineItems: { productName: string; quantity: number; subtotal: number }[];
}

interface PublicOrderSuccessProps {
  receipt: PublicOrderReceiptView;
  summary: PublicOrderSubmittedSummary;
}

const confirmationCopy = (receipt: PublicOrderReceiptView, email: string | undefined): string => {
  if (!receipt.buyerEmailProvided) return 'No confirmation email was sent, because no email address was given.';
  if (receipt.confirmationEmailSent) return `A confirmation email was sent${email ? ` to ${email}` : ''}.`;
  return 'We could not send the confirmation email. Your order was still placed — keep the order reference below.';
};

export const PublicOrderSuccess: React.FC<PublicOrderSuccessProps> = ({ receipt, summary }) => (
  <Box data-testid="public-order-success">
    <Alert severity="success" sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight="medium">
        Your order was placed.
      </Typography>
      <Typography variant="body2">{confirmationCopy(receipt, summary.email)}</Typography>
    </Alert>

    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2">Order reference</Typography>
      <Typography variant="body2" component="code" data-testid="order-reference">
        {receipt.orderId}
      </Typography>
    </Box>

    {receipt.buyerEmailProvided && resolveReceiptUrl(receipt.receiptUrl) ? (
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2">Your receipt link</Typography>
        <Typography variant="body2">
          <Link href={resolveReceiptUrl(receipt.receiptUrl)!} data-testid="receipt-link" rel="noreferrer">
            {resolveReceiptUrl(receipt.receiptUrl)}
          </Link>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Keep this link — it is the only way to view this order later.
        </Typography>
      </Box>
    ) : null}

    <Divider sx={{ my: 2 }} />

    <Typography variant="subtitle2" gutterBottom>
      What you submitted
    </Typography>
    <Table size="small" sx={{ mb: 2 }}>
      <TableHead>
        <TableRow>
          <TableCell>Item</TableCell>
          <TableCell align="right">Qty</TableCell>
          <TableCell align="right">Subtotal</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {summary.lineItems.map((item) => (
          <TableRow key={`${item.productName}-${item.quantity}`}>
            <TableCell>{item.productName}</TableCell>
            <TableCell align="right">{item.quantity}</TableCell>
            <TableCell align="right">{formatCurrency(item.subtotal)}</TableCell>
          </TableRow>
        ))}
        <TableRow>
          <TableCell align="left" sx={{ fontWeight: 500 }}>
            Total ({summary.paymentMethod})
          </TableCell>
          <TableCell />
          <TableCell align="right" sx={{ fontWeight: 500 }}>
            {formatCurrency(receipt.totalAmount)}
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>

    <Stack spacing={0.25}>
      <Typography variant="body2" color="text.secondary">
        Buyer: {summary.firstName} {summary.lastName}
      </Typography>
      {summary.phone ? (
        <Typography variant="body2" color="text.secondary">
          Phone: {summary.phone}
        </Typography>
      ) : null}
      {summary.email ? (
        <Typography variant="body2" color="text.secondary">
          Email: {summary.email}
        </Typography>
      ) : null}
    </Stack>
  </Box>
);

export default PublicOrderSuccess;
