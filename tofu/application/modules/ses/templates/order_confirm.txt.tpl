Hi {{firstName}},

Your order was placed with {{sellerName}} ({{campaignName}}).

Order: {{orderId}}
{{#each lineItems}}
- {{productName}} x{{quantity}}: ${{subtotal}}
{{/each}}
Total: ${{totalAmount}}
Payment method: {{paymentMethod}}

The seller must confirm your payment before the order is fulfilled.

View your receipt: {{receiptUrl}}
