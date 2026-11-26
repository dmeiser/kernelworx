/**
 * The line-row shapes and pure helpers the sale and correction screens share.
 *
 * They live apart from `SaleLineEditor` because the table itself is the only
 * component in that file — the react-refresh rule keeps component modules free of
 * non-component exports, and the two screens read the same row shape from the
 * catalog and from a sale's own lines (§4.5.1).
 */

import type { GqlGetUnitCampaignCatalogQuery, GqlShowAndSellSaleFieldsFragment } from '../../types/graphql-generated';

export type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];

/** One row as the editor holds it: the id it corrects, and the two typed quantities. */
export interface LineRowDraft {
  /** Set for a row that replaces an existing line; null for a new or supplemental line. */
  lineItemId: string | null;
  productId: string;
  immediateQty: string;
  weOweQty: string;
}

/** A blank row, for the line the admin has not chosen a product for yet. */
export const emptyLineRow = (): LineRowDraft => ({ lineItemId: null, productId: '', immediateQty: '', weOweQty: '' });

/** The sale's own lines, in the shape the correction editor edits. */
export function linesOf(sale: GqlShowAndSellSaleFieldsFragment): LineRowDraft[] {
  return sale.lineItems.map((line) => ({
    lineItemId: line.lineItemId,
    productId: line.productId,
    immediateQty: String(line.immediateQty),
    weOweQty: String(line.weOweQty),
  }));
}

/**
 * The products a picker offers: the catalog's, plus any product already on the sale
 * that the catalog no longer lists. A product the admin cannot select is a line they
 * cannot keep, and a correction that silently drops it cancels an obligation nobody
 * decided to cancel.
 */
export function lineProductOptions(
  products: readonly CatalogProduct[],
  rows: readonly LineRowDraft[],
): { productId: string; productName: string }[] {
  const options = products.map((product) => ({ productId: product.productId, productName: product.productName }));
  for (const row of rows) {
    if (row.productId !== '' && !options.some((option) => option.productId === row.productId)) {
      options.push({ productId: row.productId, productName: row.productId });
    }
  }
  return options;
}
