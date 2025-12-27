import { util } from '@aws-appsync/utils';

/**
 * Updates an existing catalog with new data.
 * Preserves existing productIds or generates new ones.
 * Only allows the owner to update the catalog.
 */
export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Normalize catalogId to ensure CATALOG# prefix
    const dbCatalogId = catalogId && catalogId.startsWith('CATALOG#') ? catalogId : `CATALOG#${catalogId}`;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    
    // Add productId to each product if not present
    const productsWithIds = input.products.map(product => {
        const productWithId = {
            productName: product.productName,
            price: product.price,
            sortOrder: product.sortOrder
        };
        // Preserve existing productId or generate new one
        if (product.productId) {
            productWithId.productId = product.productId;
        } else {
            productWithId.productId = `PRODUCT#${util.autoId()}`;
        }
        if (product.description) {
            productWithId.description = product.description;
        }
        return productWithId;
    });
    
    // Convert isPublic boolean to string for GSI
    const isPublicStr = input.isPublic ? "true" : "false";
    const ownerWithPrefix = `ACCOUNT#${ctx.identity.sub}`;
    
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({
            catalogId: dbCatalogId
        }),
        update: {
            expression: "SET catalogName = :catalogName, isPublic = :isPublic, isPublicStr = :isPublicStr, products = :products, updatedAt = :updatedAt",
            expressionValues: util.dynamodb.toMapValues({
                ":catalogName": input.catalogName,
                ":isPublic": isPublicStr,
                ":isPublicStr": isPublicStr,
                ":products": productsWithIds,
                ":updatedAt": now
            })
        },
        condition: {
            expression: "attribute_exists(catalogId) AND ownerAccountId = :ownerId",
            expressionValues: util.dynamodb.toMapValues({
                ":ownerId": ownerWithPrefix
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
            util.error("Catalog not found or access denied", "Forbidden");
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
