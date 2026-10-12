import { util } from '@aws-appsync/utils';

// Root resolver of the publicCreateOrder pipeline (#679 write slice). Pipeline
// order (spec §5.3, with the email step deferred to the SES slice):
//
//   validate_public_token              (ProfilesDS, profileId-index locator)
//   validate_public_token_step2        (ProfilesDS, consistent read + the token,
//                                       campaign echo, allowlist, ack, bounds)
//   get_campaign_for_public_order      (CampaignsDS, anchor + cap pre-check)
//   get_catalog                        (CatalogsDS, reused as-is)
//   validate_payment_method_public     (AccountsDS, clone: no name oracle)
//   increment_public_order_count       (CampaignsDS, the cap CONDITION)
//   create_public_order                (OrdersDS, the PutItem + receipt mint)
//
// The root passes the write step's composed receipt through. It is a pass-
// through rather than an empty resolver because the mutation's return type is
// PublicOrderReceipt!, and the write step is the only function that has the
// stored row (PutItem returns what it wrote) - so the receipt, the minted
// receipt token, and the honest email flags are composed there and surfaced
// here.
//
// The SES slice inserts its best-effort send step between the write and this
// root; that step will return the same receipt with confirmationEmailSent
// updated, and this root's pass-through shape is what makes that insertion a
// one-line pipeline change rather than a reshaping.
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
