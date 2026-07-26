/**
 * KernelWorx Client-Side XLSX / CSV Export Script
 * Uses SheetJS in browser to convert JSON endpoints to XLSX/CSV files.
 */

async function exportToXLSX(dataUrl, filename) {
  try {
    const res = await fetch(dataUrl, { credentials: 'include' });
    const data = await res.json();
    if (typeof XLSX === 'undefined') {
      alert('SheetJS library failed to load.');
      return;
    }
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Orders');
    XLSX.writeFile(wb, filename);
  } catch (err) {
    alert('Export failed: ' + err.message);
  }
}

async function exportToCSV(dataUrl, filename) {
  try {
    const res = await fetch(dataUrl, { credentials: 'include' });
    const data = await res.json();
    if (typeof XLSX === 'undefined') {
      alert('SheetJS library failed to load.');
      return;
    }
    const ws = XLSX.utils.json_to_sheet(data);
    const csv = XLSX.utils.sheet_to_csv(ws);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Export failed: ' + err.message);
  }
}
