import { util } from '@aws-appsync/utils';

// Root resolver of the publicCreateOrder pipeline (#679 write slice, campaign-keyed
// rework). Pipeline order (spec §5.3 plus the SEC-4 ownership confirmation,
// the SEC-6 abuse throttle, and the SES slice's email step):
//
//   validate_public_token              (CampaignsDS, campaignId-index locator)
//   validate_public_token_step2        (CampaignsDS, consistent read + the token,
//                                       active, cap pre-check, allowlist, ack,
//                                       bounds; stashes campaign + catalogId)
//   throttle_public_order_create       (PublicOrderThrottlesDS, per-token
//                                       fixed-window abuse guard, SEC-6)
//   get_profile_for_public_order       (ProfilesDS, profileId-index LOCATOR only)
//   get_profile_for_public_order_step2 (ProfilesDS, strongly consistent base-table
//                                       ownership confirmation; SEC-4)
//   get_catalog                       (CatalogsDS, reused as-is)
//   validate_payment_method_public    (AccountsDS, clone: no name oracle)
//   increment_public_order_count      (CampaignsDS, the cap CONDITION)
//   create_public_order               (OrdersDS, the PutItem + receipt mint)
//   send_public_order_emails          (PublicOrdersDS, best-effort SES send)
// The root passes the write step's composed receipt through. It is a pass-
// through rather than an empty resolver because the mutation's return type is
// PublicOrderReceipt!, and the write step is the only function that has the
// stored row (PutItem returns what it wrote) - so the receipt, the minted
// receipt token, and the honest email flags are composed there and surfaced
// here.
//
// The SES slice's best-effort send step sits between the write and this root
// (KW-PUBLIC-ORDERS-SES-1): it returns the same receipt with
// confirmationEmailSent updated and swallows every email failure, and this
// root's pass-through shape keeps that insertion invisible here.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const receipt = ctx.prev ? ctx.prev.result : null;
    if (!receipt || typeof receipt.orderId !== 'string') {
        // The write step is the last function; a null here means it produced no
        // row. Failing loudly is correct: the schema promises a non-null receipt,
        // and returning null would surface as the resolver-missing error shape
        // the buyer page cannot distinguish from a dead link.
        util.error('Order could not be placed', 'INTERNAL_ERROR');
        return null;
    }

    return receipt;
}
