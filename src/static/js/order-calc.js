/**
 * KernelWorx Order Price Calculation Script
 * Computes dynamic line item subtotals and grand total client-side.
 */

function calculateOrderTotal() {
  const rows = document.querySelectorAll('.line-item-row');
  let grandTotal = 0;

  rows.forEach(row => {
    const qtyInput = row.querySelector('.item-qty');
    const priceInput = row.querySelector('.item-price');
    const subtotalEl = row.querySelector('.item-subtotal');

    const qty = parseFloat(qtyInput?.value || 0);
    const price = parseFloat(priceInput?.value || 0);
    const subtotal = qty * price;

    if (subtotalEl) {
      subtotalEl.textContent = '$' + subtotal.toFixed(2);
    }
    grandTotal += subtotal;
  });

  const grandTotalEl = document.getElementById('grand-total-display');
  if (grandTotalEl) {
    grandTotalEl.textContent = '$' + grandTotal.toFixed(2);
  }
}

function addLineItemRow() {
  const container = document.getElementById('line-items-container');
  if (!container) return;
  const index = container.querySelectorAll('.line-item-row').length;
  const template = `
    <tr class="line-item-row">
      <td><input type="text" name="items[${index}][name]" class="form-control item-name" placeholder="Item Name" required></td>
      <td><input type="number" name="items[${index}][quantity]" class="form-control item-qty" value="1" min="1" oninput="calculateOrderTotal()" required></td>
      <td><input type="number" step="0.01" name="items[${index}][price]" class="form-control item-price" value="10.00" oninput="calculateOrderTotal()" required></td>
      <td class="item-subtotal">$10.00</td>
      <td><button type="button" class="btn btn-danger" onclick="this.closest('tr').remove(); calculateOrderTotal();">&times;</button></td>
    </tr>
  `;
  container.insertAdjacentHTML('beforeend', template);
  calculateOrderTotal();
}
