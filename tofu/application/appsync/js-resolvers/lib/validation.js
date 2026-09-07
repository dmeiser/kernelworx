export function validatePhone(phone) {
    if (typeof phone !== 'string' || !phone.trim()) {
        return { valid: false, error: 'Phone number is required when provided' };
    }
    let cleaned = '';
    for (const c of phone) {
        if (c >= '0' && c <= '9') {
            cleaned += c;
        }
    }
    if (cleaned.length === 11 && cleaned[0] === '1') {
        cleaned = cleaned.substring(1);
    }
    if (cleaned.length !== 10) {
        return { valid: false, error: 'Phone number must be a valid 10-digit US number' };
    }
    return { valid: true, value: '+1' + cleaned };
}

export function validateAddress(address) {
    if (!address || typeof address !== 'object') {
        return { valid: false, error: 'Address is missing required fields' };
    }
    const required = ['street', 'city', 'state', 'zipCode'];
    const missing = required.filter((field) => !address[field] || (typeof address[field] === 'string' && !address[field].trim()));
    if (missing.length > 0) {
        return { valid: false, error: 'Address is missing required fields: ' + missing.join(', ') };
    }
    const rawZip = address.zipCode;
    const zip = rawZip == null ? '' : `${rawZip}`.trim();
    let zipDigits = '';
    for (const c of zip) {
        if (c >= '0' && c <= '9') {
            zipDigits += c;
        }
    }
    if (zipDigits.length !== 5 && zipDigits.length !== 9) {
        return { valid: false, error: 'ZIP code must be 5 or 9 digits' };
    }
    return { valid: true };
}
