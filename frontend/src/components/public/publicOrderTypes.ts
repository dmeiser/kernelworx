/**
 * View shapes shared by the public order page's components.
 *
 * They are structural subsets of the generated operation types, so the page can
 * pass query results straight in while the components stay independently
 * testable.
 */

export interface PublicProductView {
  productId: string;
  productName: string;
  price: number;
  description?: string | null;
}

export interface PublicPaymentMethodView {
  name: string;
  qrCodeUrl?: string | null;
}

export interface PublicOfferView {
  sellerName: string;
  campaignId: string;
  campaignName: string;
  products: PublicProductView[];
  paymentMethods: PublicPaymentMethodView[];
}
