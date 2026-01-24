import { util } from '@aws-appsync/utils';

/**
 * Creates a new catalog with products.
 * Validates products array is not empty and generates IDs for catalog and products.
 */
export function request(ctx) {
    const input = ctx.args.input;
    
    // Validate products array is not empty
    if (!input.products || input.products.length === 0) {
        util.error("Products array cannot be empty", "ValidationException");
    }
    
    const catalogId = `CATALOG#${util.autoId()}`;
    const now = util.time.nowISO8601();
    
    // Add productId to each product
    const productsWithIds = input.products.map(product => {
        const productWithId = {
            productId: `PRODUCT#${util.autoId()}`,
            productName: product.productName,
            price: product.price,
            sortOrder: product.sortOrder
        };
        if (product.description) {
            productWithId.description = product.description;
        }
        return productWithId;
    });
    
    // Convert isPublic boolean to string for GSI
    const isPublicStr = input.isPublic ? "true" : "false";
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({
            catalogId: catalogId
        }),
        attributeValues: util.dynamodb.toMapValues({
            catalogName: input.catalogName,
            catalogType: "USER_CREATED",
            ownerAccountId: `ACCOUNT#${ctx.identity.sub}`,
            isPublic: input.isPublic,
            isPublicStr: isPublicStr,
            products: productsWithIds,
            createdAt: now,
            updatedAt: now
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
