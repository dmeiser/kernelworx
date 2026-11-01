<html>
<body>
<p>Hi {{firstName}},</p>
<p>Your order was placed with <strong>{{sellerName}}</strong> ({{campaignName}}).</p>
<p>Order: {{orderId}}</p>
<ul>
{{#each lineItems}}
<li>{{productName}} &times;{{quantity}}: ${{subtotal}}</li>
{{/each}}
</ul>
<p>Total: ${{totalAmount}}<br>Payment method: {{paymentMethod}}</p>
<p>The seller must confirm your payment before the order is fulfilled.</p>
<p><a href="{{receiptUrl}}">View your receipt</a></p>
</body>
</html>
