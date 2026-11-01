/**
 * The buyer's receipt page: /r/:campaignId/:orderSuffix/:receiptToken
 *
 * Reached from the confirmation email (or the success screen's link). The order
 * id is split across two path segments because the raw id contains '#', which a
 * browser treats as the fragment delimiter; the page passes the two segments
 * through untouched and the server re-prefixes them into the
 * `ORDER#<campaignId>#<orderSuffix>` PK/SK. The per-order receipt token in the
 * third segment is the capability: it discloses exactly this one order and is
 * never echoed back by the API.
 */

import { useParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Box, Button, Divider, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import { LoadingState } from '../components/LoadingState';
import { NoIndexMeta } from '../components/NoIndexMeta';
import { PublicPageUnavailable } from '../components/public/PublicPageUnavailable';
import { ReceiptStatusChip } from '../components/public/ReceiptStatusChip';
import { PUBLIC_GET_ORDER_RECEIPT } from '../lib/publicOrderGraphQL';
import { formatCurrency, isNotFoundError } from '../lib/api-utils';
import { formatDisplayDate } from '../lib/date-utils';
import type { ApolloLikeError } from '../lib/api-utils';
import type { GqlPublicGetOrderReceiptQuery, GqlPublicGetOrderReceiptQueryVariables } from '../types/graphql-generated';

type ReceiptView = GqlPublicGetOrderReceiptQuery['publicGetOrderReceipt'];

const ReceiptBody: React.FC<{ receipt: ReceiptView }> = ({ receipt }) => (
  <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
    <Typography variant="h4" gutterBottom>
      Your order
    </Typography>
    <Stack spacing={0.25} sx={{ mb: 2 }}>
      <Typography variant="body2">Seller: {receipt.sellerName}</Typography>
      <Typography variant="body2">
        Buyer: {receipt.buyerFirstName} {receipt.buyerLastName}
      </Typography>
      <Typography variant="body2">
        Placed: {formatDisplayDate(receipt.orderDate, { year: 'numeric', month: 'long', day: 'numeric' })}
      </Typography>
      <Typography variant="body2" component="code">
        Order reference: {receipt.orderId}
      </Typography>
      <Box mt={0.5}>
        <ReceiptStatusChip status={receipt.status} />
      </Box>
    </Stack>

    <TableContainer sx={{ mb: 2 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Item</TableCell>
            <TableCell align="right">Qty</TableCell>
            <TableCell align="right">Each</TableCell>
            <TableCell align="right">Subtotal</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {receipt.lineItems.map((item) => (
            <TableRow key={item.productId}>
              <TableCell>{item.productName}</TableCell>
              <TableCell align="right">{item.quantity}</TableCell>
              <TableCell align="right">{formatCurrency(item.pricePerUnit)}</TableCell>
              <TableCell align="right">{formatCurrency(item.subtotal)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>

    <Divider sx={{ mb: 1 }} />
    <Stack direction="row" justifyContent="space-between">
      <Typography variant="body1" sx={{ fontWeight: 500 }}>
        Total ({receipt.paymentMethodName})
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 500 }}>
        {formatCurrency(receipt.totalAmount)}
      </Typography>
    </Stack>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
      The seller confirms payment separately — this page shows the order as the seller recorded it.
    </Typography>
  </Paper>
);

/**
 * A receipt read that failed for a reason other than the link being dead.
 *
 * Telling a buyer the link is unavailable when the network merely blipped sends
 * them to support over an order that exists and a link that still works, so a
 * transient failure gets its own retryable state instead.
 */
const ReceiptLoadError: React.FC<{ onRetry: () => void }> = ({ onRetry }) => (
  <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }} data-testid="receipt-load-error">
    <Typography variant="h4" gutterBottom>
      We could not load your receipt
    </Typography>
    <Typography variant="body2" color="text.secondary">
      That is usually a connection problem rather than a problem with your link — your order is still placed.
    </Typography>
    <Button variant="contained" onClick={onRetry} sx={{ mt: 2 }} data-testid="receipt-retry">
      Try again
    </Button>
  </Paper>
);

interface PageBodyProps {
  loading: boolean;
  receipt: ReceiptView | null;
  error?: ApolloLikeError | undefined;
  onRetry: () => void;
}

/**
 * A skipped query (malformed link) leaves no loading flag and no error, so it
 * falls through to the unavailable screen; a failed read that is not a NOT_FOUND
 * gets the retryable screen instead of that same dead-link message.
 */
const PageBody: React.FC<PageBodyProps> = ({ loading, receipt, error, onRetry }) => {
  if (receipt) return <ReceiptBody receipt={receipt} />;
  if (loading) return <LoadingState />;
  if (error && !isNotFoundError(error)) return <ReceiptLoadError onRetry={onRetry} />;
  return <PublicPageUnavailable />;
};

interface ReceiptSegments {
  campaignId: string;
  orderSuffix: string;
  receiptToken: string;
}

/** The three path segments, defaulted to empty when the URL is malformed. */
function receiptSegments(params: Partial<ReceiptSegments> | undefined): ReceiptSegments {
  const source = params ?? {};
  return {
    campaignId: source.campaignId || '',
    orderSuffix: source.orderSuffix || '',
    receiptToken: source.receiptToken || '',
  };
}

function segmentsAreComplete(segments: ReceiptSegments): boolean {
  return Boolean(segments.campaignId && segments.orderSuffix && segments.receiptToken);
}

export const PublicReceiptPage: React.FC = () => {
  const params = useParams<{ campaignId: string; orderSuffix: string; receiptToken: string }>();
  const segments = receiptSegments(params);
  const complete = segmentsAreComplete(segments);

  const { data, loading, error, refetch } = useQuery<GqlPublicGetOrderReceiptQuery, GqlPublicGetOrderReceiptQueryVariables>(
    PUBLIC_GET_ORDER_RECEIPT,
    {
      // The two id segments are passed through as-is: the server re-prefixes
      // them into the PK/SK and rejects legacy two-part order ids.
      variables: segments,
      skip: !complete,
    },
  );

  return (
    <Box sx={{ p: { xs: 2, sm: 3 }, maxWidth: 700, mx: 'auto' }}>
      <NoIndexMeta />
      <PageBody
        loading={loading}
        receipt={data?.publicGetOrderReceipt ?? null}
        error={error as ApolloLikeError | undefined}
        onRetry={() => void refetch()}
      />
    </Box>
  );
};

export default PublicReceiptPage;
