A new public order was placed for {{campaignName}}.

Order: {{orderId}}
Buyer: {{buyerFirstName}} {{buyerLastName}}
{{#if buyerEmail}}Email: {{buyerEmail}}
{{/if}}{{#if buyerPhone}}Phone: {{buyerPhone}}
{{/if}}{{#if buyerAddress}}Address: {{buyerAddress}}
{{/if}}
{{#each lineItems}}
- {{productName}} x{{quantity}}: ${{subtotal}}
{{/each}}
Total: ${{totalAmount}}
Payment method: {{paymentMethod}}

Mark the order CONFIRMED in KernelWorx once you have verified payment off-platform.
