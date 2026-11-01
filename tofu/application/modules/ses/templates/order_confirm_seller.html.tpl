<html>
<body>
<p>A new public order was placed for <strong>{{campaignName}}</strong>.</p>
<p>Order: {{orderId}}<br>Buyer: {{buyerFirstName}} {{buyerLastName}}</p>
<p>
{{#if buyerEmail}}Email: {{buyerEmail}}<br>{{/if}}
{{#if buyerPhone}}Phone: {{buyerPhone}}<br>{{/if}}
{{#if buyerAddress}}Address: {{buyerAddress}}<br>{{/if}}
</p>
<ul>
{{#each lineItems}}
<li>{{productName}} &times;{{quantity}}: ${{subtotal}}</li>
{{/each}}
</ul>
<p>Total: ${{totalAmount}}<br>Payment method: {{paymentMethod}}</p>
<p>Mark the order CONFIRMED in KernelWorx once you have verified payment off-platform.</p>
</body>
</html>
